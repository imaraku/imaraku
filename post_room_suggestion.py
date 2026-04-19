#!/usr/bin/env python3
"""
post_room_suggestion.py
楽天ROOM投稿用に「ふるさと納税の人気商品」を1件選出し、
Claude Haiku にアピール文を生成させて Gmail にメールで通知する。

【動作ロジック】
  1. 楽天APIでふるさと納税ランキングTOPを取得（新API→検索APIへフォールバック）
  2. キャッシュと突き合わせて未通知の上位1品を選出
  3. Claude Haiku 4.5 にアピール文(2-3行)を生成させる
  4. メール本文を組み立てて Gmail SMTP 経由で送信
  5. キャッシュ更新（直近30件の商品URLを保持して重複回避）
"""

import os
import sys
import json
import datetime
import smtplib
import ssl
from email.mime.text import MIMEText
from email.header import Header

import requests

# ── 認証情報 ─────────────────────────────────────────────────────────────────
RAKUTEN_APP_ID     = os.environ.get("RAKUTEN_APP_ID", "").strip()
RAKUTEN_ACCESS_KEY = os.environ.get("RAKUTEN_ACCESS_KEY", "").strip()
RAKUTEN_ORIGIN     = os.environ.get("RAKUTEN_ORIGIN", "https://imaraku.github.io").strip()

ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "").strip()
GMAIL_USER         = os.environ.get("GMAIL_USER", "mochiki.kengo@gmail.com").strip()
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]  # 必須
MAIL_TO            = os.environ.get("MAIL_TO", "mochiki.kengo@gmail.com").strip()

# ── 定数 ─────────────────────────────────────────────────────────────────────
JST                = datetime.timezone(datetime.timedelta(hours=9))
CACHE_FILE         = "room_post_cache.json"
CACHE_HISTORY_MAX  = 30
AFFILIATE_SUFFIX   = "scid=af_pc_etc&sc2id=af_101_0_0"
CLAUDE_MODEL       = "claude-haiku-4-5-20251001"

# ── ユーティリティ ─────────────────────────────────────────────────────────────

def add_affiliate(url: str) -> str:
    """楽天URLにアフィリエイトパラメータを付与する。"""
    if not url or "rakuten" not in url:
        return url
    sep = "&" if "?" in url else "?"
    return url + sep + AFFILIATE_SUFFIX


def strip_name_prefix(name: str) -> str:
    """【...】【...】で始まる商品名プレフィックスを軽く整形。"""
    import re
    pattern = re.compile(r'^[【［\[][^】］\]]*[】］\]]\s*')
    while True:
        m = pattern.match(name)
        if not m:
            break
        stripped = name[m.end():]
        if not stripped.strip():
            break
        name = stripped
    return name.strip()


def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"sent_urls": [], "last_sent_date": ""}


def save_cache(cache: dict) -> None:
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


# ── ランキング取得 ─────────────────────────────────────────────────────────────

def _normalize_item(it: dict) -> dict:
    name = (it.get("itemName") or "").strip()
    url  = (it.get("itemUrl") or "").strip()
    price = it.get("itemPrice") or 0
    shop = (it.get("shopName") or "").strip()
    caption = (it.get("itemCaption") or "").strip()
    return {
        "name": name,
        "url": url,
        "price": int(price) if price else 0,
        "shop": shop,
        "caption": caption[:400],
    }


def _is_furusato(name: str) -> bool:
    """商品名にふるさと納税らしいキーワードが含まれるか。"""
    name_low = name
    for kw in ("ふるさと納税", "ふるさと 納税", "【ふるさと"):
        if kw in name_low:
            return True
    return False


def fetch_via_search_api(hits: int = 30, sort: str = "-reviewCount") -> list[dict]:
    """旧公開Search API (app.rakuten.co.jp) でふるさと納税キーワード検索。
    Originヘッダ付与でOrigin制限されたappIdにも対応。"""
    if not RAKUTEN_APP_ID:
        return []
    url = "https://app.rakuten.co.jp/services/api/IchibaItem/Search/20220601"
    params = {
        "format": "json",
        "applicationId": RAKUTEN_APP_ID,
        "keyword": "ふるさと納税",
        "sort": sort,
        "hits": hits,
    }
    headers = {"Origin": RAKUTEN_ORIGIN} if RAKUTEN_ORIGIN else {}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=20)
        if r.status_code != 200:
            print(f"⚠️ Search API {r.status_code}: {r.text[:200]}", file=sys.stderr)
            return []
        data = r.json()
    except Exception as e:
        print(f"⚠️ Search API失敗: {e}", file=sys.stderr)
        return []

    items = []
    for entry in data.get("Items", []):
        it = _normalize_item(entry.get("Item", {}))
        if it["name"] and it["url"] and _is_furusato(it["name"]):
            items.append(it)
    if items:
        print(f"  Search API取得: {len(items)} 件（sort={sort}、ふるさと納税フィルタ済）")
    return items


def fetch_via_ranking_probe() -> list[dict]:
    """Ranking API を複数条件で叩いて、商品名に「ふるさと納税」を含むものだけ集める。
    Search APIが401/404で使えない場合のフォールバック。"""
    if not RAKUTEN_APP_ID or not RAKUTEN_ACCESS_KEY:
        return []
    url = "https://openapi.rakuten.co.jp/ichibaranking/api/IchibaItem/Ranking/20220601"
    headers = {"Origin": RAKUTEN_ORIGIN}
    probes = [
        (0, "realtime", 1),
        (0, "daily", 1),
        (0, "daily", 2),
        (0, "daily", 3),
        (552612, "realtime", 1),
        (552612, "daily", 1),
    ]
    seen = set()
    results = []
    for gid, period, page in probes:
        params = {
            "format": "json",
            "applicationId": RAKUTEN_APP_ID,
            "accessKey": RAKUTEN_ACCESS_KEY,
            "genreId": gid,
            "period": period,
            "hits": 30,
            "page": page,
        }
        try:
            r = requests.get(url, params=params, headers=headers, timeout=20)
            if r.status_code != 200:
                print(f"  ⚠️ probe gid={gid} period={period} page={page}: {r.status_code}", file=sys.stderr)
                continue
            data = r.json()
        except Exception as e:
            print(f"  ⚠️ probe err: {e}", file=sys.stderr)
            continue
        for entry in data.get("Items", []):
            it = _normalize_item(entry.get("Item", {}))
            if not (it["name"] and it["url"]):
                continue
            base = it["url"].split("?")[0]
            if base in seen:
                continue
            if _is_furusato(it["name"]):
                seen.add(base)
                results.append(it)
        print(f"  probe gid={gid} period={period} page={page}: 累計 {len(results)} 件")
        if len(results) >= 15:
            break
    return results


def fetch_furusato_items() -> list[dict]:
    """Search API → Ranking APIプローブの順で試す。"""
    items = fetch_via_search_api(hits=30, sort="-reviewCount")
    if items:
        return items
    print("  Search API空/失敗 → Ranking APIプローブへ")
    return fetch_via_ranking_probe()


# ── 商品選出 ───────────────────────────────────────────────────────────────────

def pick_item(items: list[dict], sent_urls: list[str]) -> dict | None:
    """未送信の最上位アイテムを返す。"""
    sent_set = set(sent_urls)
    for it in items:
        base_url = it["url"].split("?")[0]
        if base_url not in sent_set:
            return it
    return None


# ── アピール文生成 ─────────────────────────────────────────────────────────────

def generate_appeal(item: dict) -> str:
    """Claude Haiku にアピール文を生成させる。失敗時はフォールバック文を返す。"""
    fallback = "人気ランキングから厳選！ふるさと納税でお得に手に入れるチャンスだよ。"
    if not ANTHROPIC_API_KEY:
        print("  ⚠️ ANTHROPIC_API_KEY 未設定 → フォールバック", file=sys.stderr)
        return fallback

    try:
        from anthropic import Anthropic
    except ImportError:
        print("  ⚠️ anthropic パッケージ未インストール → フォールバック", file=sys.stderr)
        return fallback

    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""以下は楽天ふるさと納税の人気商品です。楽天ROOM投稿用のアピール文を日本語で生成してください。

# 商品情報
- 商品名: {item['name']}
- ショップ: {item['shop']}
- 寄付額: {item['price']:,}円
- 商品説明(冒頭): {item['caption'][:200]}

# 要件
- 2〜3行、合計100文字以内
- 購買意欲をそそる、温かみのある口調
- 「お得」「節税」「美味しそう」など自然な訴求
- 先頭に絵文字1つ付けてOK（不要なら無し）
- 過剰な煽り(！！！、【超激安】等)は禁止
- 本文のみ返答。前置きや後書きは不要
"""

    try:
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        return text or fallback
    except Exception as e:
        print(f"  ⚠️ Claude API失敗: {e} → フォールバック", file=sys.stderr)
        return fallback


# ── メール組み立て & 送信 ──────────────────────────────────────────────────────

def build_email(item: dict, appeal: str, aff_url: str) -> tuple[str, str]:
    clean_name = strip_name_prefix(item["name"])
    short_name = clean_name[:50]
    subject = f"【今日のROOM投稿】{short_name}"

    body_name = clean_name[:80]
    tags = "#楽天ROOM #ふるさと納税 #楽天ふるさと納税 #節税 #お得"

    body = f"""━━━ 今日の楽天ROOM投稿候補 ━━━

📮 {body_name}
💰 寄付額 {item['price']:,}円
🏪 {item['shop']}

──────────────────
【投稿文コピペ用 ↓ここから↓】

{appeal}

🔗 {aff_url}

{tags}
【↑ここまで↑】
──────────────────

🎯 月¥10,000を目指してコツコツ投稿
📅 生成: {datetime.datetime.now(JST).strftime('%Y-%m-%d %H:%M')} JST

━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    return subject, body


def send_email(subject: str, body: str) -> None:
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = GMAIL_USER
    msg["To"] = MAIL_TO

    context = ssl.create_default_context()
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
        server.starttls(context=context)
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.send_message(msg)
    print(f"✅ メール送信成功 → {MAIL_TO}")


# ── メイン ─────────────────────────────────────────────────────────────────────

def main() -> int:
    print("🚀 post_room_suggestion.py 開始")

    items = fetch_furusato_items()
    if not items:
        print("❌ ふるさと納税アイテムを1件も取得できなかった", file=sys.stderr)
        return 1

    cache = load_cache()
    item = pick_item(items, cache.get("sent_urls", []))
    if item is None:
        print("  全て送信済み → キャッシュをリセットしてTOPを採用")
        cache["sent_urls"] = []
        item = items[0]

    print(f"  選出: {item['name'][:60]}")
    print(f"  寄付額: {item['price']:,}円")

    aff_url = add_affiliate(item["url"])
    appeal = generate_appeal(item)
    print(f"  アピール文: {appeal}")

    subject, body = build_email(item, appeal, aff_url)

    if os.environ.get("DRY_RUN") == "1":
        print("── DRY RUN (メール送信スキップ) ──")
        print(f"件名: {subject}")
        print(body)
        return 0

    send_email(subject, body)

    # キャッシュ更新
    base_url = item["url"].split("?")[0]
    sent = cache.get("sent_urls", [])
    sent.insert(0, base_url)
    cache["sent_urls"] = sent[:CACHE_HISTORY_MAX]
    cache["last_sent_date"] = datetime.datetime.now(JST).strftime("%Y-%m-%d")
    save_cache(cache)

    print("🏁 完了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
