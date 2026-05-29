#!/usr/bin/env python3
"""
post_category_ranking.py
曜日×週ローテーションで決まるサブカテゴリの「リアルタイムランキング1位」を
楽天 Ichiba Ranking API から取得し、X(Twitter)に投稿する。

【機能】
  ・曜日別サブカテゴリ（category_ranking.json weekdays スキーマ）を週ローテーションで選択
  ・楽天 IchibaItem/Ranking/20220601 API（realtime, hits上限20）でジャンル別TOP取得
  ・商品名 whitelist/blacklist でカテゴリゲーミング（別ジャンル商品の混入）を除去
  ・当番サブが TOP20 に1件も出ない週は同曜日の他サブへフォールバック（必ず1投稿）
  ・TOP1 のみ集中投下（CTR最大化）＋ アフィリエイトURL ラッピング
  ・1日1回まで（category_posted.json で同日重複投稿防止）

⚠️ 地雷#10: realtime ランキングは hits>20 で 400。fetch_top_items が hits を 20 に clamp する。
"""

import os
import re
import sys
import json
import datetime
import requests
from urllib.parse import quote
from requests_oauthlib import OAuth1

from hashtag_helper import hashtags

# ── 認証情報 ──
API_KEY             = os.environ["TWITTER_API_KEY"]
API_SECRET          = os.environ["TWITTER_API_SECRET"]
ACCESS_TOKEN        = os.environ["TWITTER_ACCESS_TOKEN"]
ACCESS_TOKEN_SECRET = os.environ["TWITTER_ACCESS_TOKEN_SECRET"]
RAKUTEN_APP_ID      = os.environ.get("RAKUTEN_APP_ID", "").strip()
RAKUTEN_ACCESS_KEY  = os.environ.get("RAKUTEN_ACCESS_KEY", "").strip()
RAKUTEN_ORIGIN      = os.environ.get("RAKUTEN_ORIGIN", "https://imaraku.github.io").strip()

# ── 定数 ──
JST = datetime.timezone(datetime.timedelta(hours=9))
SITE_URL = "https://imaraku.github.io/imaraku/imaraku.html"
CONFIG_FILE = "category_ranking.json"
POSTED_FILE = "category_posted.json"
RAKUTEN_AFFILIATE_ID = "1c52abea.36641b1e.1c52abeb.f5f67f16"
# 新ランキングAPI（旧 Search API は applicationId 拒否で動かないため移行）
RAKUTEN_API = "https://openapi.rakuten.co.jp/ichibaranking/api/IchibaItem/Ranking/20220601"


# ── アフィリエイト ──
def aff(url: str) -> str:
    if not url or 'rakuten' not in url:
        return url
    if 'hb.afl.rakuten.co.jp' in url or 'a.r10.to' in url:
        return url
    encoded = quote(url, safe='')
    return f"https://hb.afl.rakuten.co.jp/hgc/{RAKUTEN_AFFILIATE_ID}/?pc={encoded}&m={encoded}"


# ── 設定読み込み ──
def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return {"categories": {}}
    with open(CONFIG_FILE, encoding='utf-8') as f:
        return json.load(f)


def load_posted() -> dict:
    if not os.path.exists(POSTED_FILE):
        return {}
    try:
        with open(POSTED_FILE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_posted(data: dict):
    with open(POSTED_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── 楽天API ──
def fetch_top_items(genre_id: int, keyword: str = "", hits: int = 20, min_reviews: int = 0) -> list:
    """楽天 Ichiba Ranking API で genreId のジャンル別ランキングを取得。
    keyword が指定されていれば itemName で部分一致フィルタも適用。"""
    if not RAKUTEN_APP_ID or not RAKUTEN_ACCESS_KEY:
        print("⚠️ RAKUTEN_APP_ID / RAKUTEN_ACCESS_KEY が未設定", file=sys.stderr)
        return []
    # ⚠️ 地雷#10: realtime ランキングは hits 上限 20。21 以上を渡すと API が 400 を返し
    # 全件取得失敗 → 毎回スキップする。caller が何を渡しても 20 を超えさせない安全弁。
    hits = min(int(hits or 20), 20)
    headers = {"Origin": RAKUTEN_ORIGIN}

    def _call(gid: int):
        params = {
            "format": "json",
            "applicationId": RAKUTEN_APP_ID,
            "accessKey": RAKUTEN_ACCESS_KEY,
            "genreId": gid,
            "period": "realtime",
            "hits": hits,
        }
        return requests.get(RAKUTEN_API, params=params, headers=headers, timeout=20)

    try:
        r = _call(genre_id)
        # genreId にランキングデータが無い場合は genreId=0 にフォールバック
        if r.status_code == 404 and genre_id != 0:
            print(f"  ⚠️ genreId={genre_id} ランキング無し → genreId=0 で再取得", file=sys.stderr)
            r = _call(0)
        if r.status_code != 200:
            print(f"⚠️ 楽天API エラー: {r.status_code} {r.text[:200]}", file=sys.stderr)
            return []
        data = r.json()
    except Exception as e:
        print(f"⚠️ 楽天API 取得失敗: {e}", file=sys.stderr)
        return []

    items = []
    for entry in data.get("Items", []):
        it = entry.get("Item", {})
        name = (it.get("itemName") or "").strip()
        # キーワードフィルタ（任意・絞り込み用）
        if keyword and keyword not in name:
            continue
        # 新ランキングAPIは値を文字列で返すため数値変換
        try:
            review_count = int(it.get("reviewCount") or 0)
        except (ValueError, TypeError):
            review_count = 0
        if review_count < min_reviews:
            continue
        items.append({
            "name": name,
            "url": it.get("itemUrl") or "",
            "caption": (it.get("itemCaption") or "").strip(),
            "reviewAverage": it.get("reviewAverage", 0),
            "reviewCount": review_count,
            "shopName": (it.get("shopName") or "").strip(),
        })
    return items


# ── 推しポイント自動抽出 ──
NOISE_PATTERNS = [
    r'[■◆★☆▼▽◇◎●○※]+',
    r'【[^】]*】',
    r'\([^)]*送料[^)]*\)',
    r'<[^>]+>',
    r'https?://\S+',
]

POSITIVE_KEYWORDS = [
    "送料無料", "あす楽", "翌日", "ポイント", "リピート",
    "人気", "売れ筋", "ランキング", "コスパ", "高評価",
    "楽天1位", "限定", "選べる", "まとめ買い", "大容量",
    "ふるさと納税",
]


def clean_text(text: str) -> str:
    """商品説明からノイズ除去"""
    for pattern in NOISE_PATTERNS:
        text = re.sub(pattern, ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def short_rating(item: dict) -> str:
    """⭐4.6(1.2万) のような超短い評価表記を返す（インライン表示用）。
    楽天新ランキングAPIは reviewAverage/reviewCount を文字列で返すため
    数値変換が必須。"""
    try:
        avg = float(item.get("reviewAverage") or 0)
        count = int(item.get("reviewCount") or 0)
    except (ValueError, TypeError):
        return ""
    if count <= 0 or avg <= 0:
        return ""
    if count >= 10000:
        count_str = f"{count // 1000 / 10:.1f}万".replace(".0万", "万")
    elif count >= 1000:
        count_str = f"{count // 100 / 10:.1f}千".replace(".0千", "千")
    else:
        count_str = str(count)
    return f"⭐{avg:.1f}({count_str})"


def extract_feature(item: dict) -> str:
    """商品から推しポイント1行を自動抽出（itemCaption から本文抽出）。
    ⭐評価表記は別途 short_rating() で取得すること。"""
    caption = clean_text(item.get("caption", ""))
    if not caption:
        return ""
    sentences = re.split(r'[。！？\n]+', caption)
    sentences = [s.strip() for s in sentences if 8 <= len(s.strip()) <= 60]

    best = None
    for s in sentences:
        if any(kw in s for kw in POSITIVE_KEYWORDS):
            best = s
            break
    if not best and sentences:
        best = sentences[0]
    return best or ""


# ── ツイート組み立て ──
def shorten_name(name: str, max_len: int = 30) -> str:
    """商品名を読みやすく短縮（先頭の【】や送料表記を削除）"""
    name = re.sub(r'^[【\[（(].*?[】\]）)]\s*', '', name)
    name = re.sub(r'[（(]送料[^）)]*[）)]', '', name)
    name = name.strip()
    if len(name) > max_len:
        name = name[:max_len] + "…"
    return name


def weighted_length(text: str) -> int:
    """Twitter 重み付き文字数を計算（ASCII=1, 全角=2, URL=23固定）"""
    text_for_count = re.sub(r'https?://\S+', 'X' * 23, text)
    n = 0
    for ch in text_for_count:
        n += 1 if ord(ch) < 0x80 else 2
    return n


def _compose_top1_tweet(header: str, item: dict, tail: str, footer: str, name_limit: int) -> str:
    """TOP1 のみツイート組み立て（2026-05-26 改修: TOP3 → TOP1 集中投下）。
    商品名 + ⭐評価 + 商品ページURL + 推しメッセージ + ハッシュタグ。
    """
    item_name = shorten_name(item['name'], name_limit)
    rating = short_rating(item)
    body_lines = [f"🏆 {item_name}"]
    if rating:
        body_lines.append(rating)
    body_lines.append("")
    body_lines.append("👇 商品ページ")
    body_lines.append(aff(item["url"]))
    if tail:
        body_lines.append("")
        body_lines.append(tail)
    return header + "\n".join(body_lines).rstrip() + footer


def build_tweet(category: dict, items: list) -> str:
    """カテゴリ＋TOP1アイテムからツイート文を作る（2026-05-26 改修）。
    変更点:
      - TOP3 表示 → TOP1 のみ（実測で押されるのは #1 だけだったため CTR 最大化目的）
      - サブカテゴリ細分化（例: 飲み物 → ジュース / ミネラルウォーター / 炭酸水 ...）
        週ごとに別サブが当番になる
    """
    name = category.get("name", "TOP")
    emoji = category.get("emoji", "🏆")
    tail = category.get("tail_message", "")
    tags = hashtags(category.get("hashtags", ["core", "poikatsu"]), max_tags=3)

    header = f"{emoji} {name} ランキング1位\n\n"
    footer = f"\n\n {tags}"
    top = items[0]

    # name_limit を段階的に短くして280字制限にフィット
    for limit in (40, 32, 26, 20, 14):
        c = _compose_top1_tweet(header, top, tail, footer, name_limit=limit)
        if weighted_length(c) <= 280:
            return c
    return _compose_top1_tweet(header, top, tail, footer, name_limit=10)


# ── X 投稿 ──
def post_tweet(text: str) -> bool:
    auth = OAuth1(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
    resp = requests.post(
        "https://api.twitter.com/2/tweets",
        auth=auth,
        json={"text": text},
        headers={"Content-Type": "application/json"},
    )
    if resp.status_code == 201:
        print(f"✅ 投稿成功: {resp.json()['data']['id']}")
        return True
    print(f"❌ 投稿失敗: {resp.status_code} {resp.text}", file=sys.stderr)
    return False


# ── カテゴリゲーミング対策フィルタ ─────────────────────────────────
def filter_items(cat: dict, items: list) -> list:
    """商品名で2段フィルタしてカテゴリミスマッチを弾く。
    楽天は出店者が任意ジャンルでランキング登録できる（例: マッサージ器を
    「スイーツ」ジャンルに登録するショップが実在）。
      1. blacklist のいずれか1語でも商品名に含まれていれば除外（誤爆ストッパー）
      2. whitelist が指定されている場合、いずれか1語が商品名に含まれている必要あり
    """
    name_whitelist = cat.get("filter_keywords") or cat.get("name_must_contain_any") or []
    name_blacklist = cat.get("name_must_not_contain_any", []) or []
    if not (name_blacklist or name_whitelist):
        return items
    before = len(items)
    filtered = []
    rejected_examples = []
    for it in items:
        nm = it.get("name", "")
        if any(bw in nm for bw in name_blacklist):
            if len(rejected_examples) < 3:
                rejected_examples.append(f"NG(blacklist): {nm[:50]}")
            continue
        if name_whitelist and not any(ww in nm for ww in name_whitelist):
            if len(rejected_examples) < 3:
                rejected_examples.append(f"NG(not in whitelist): {nm[:50]}")
            continue
        filtered.append(it)
    print(f"  ゲーミング対策フィルタ: {before} → {len(filtered)} 件")
    for ex in rejected_examples:
        print(f"    {ex}")
    return filtered


def collect_items_for_sub(cat: dict) -> list:
    """1サブカテゴリ分の「フェッチ＋ゲーミング対策フィルタ済み」アイテムを返す。"""
    # 新スキーマは genre_id / 旧スキーマは genreId の両方を許容
    genre_id = cat.get("genre_id") or cat.get("genreId")
    if not genre_id:
        print(f"  ⚠️ {cat.get('name')} に genre_id 未設定 → スキップ")
        return []
    name_whitelist = cat.get("filter_keywords") or cat.get("name_must_contain_any") or []
    name_blacklist = cat.get("name_must_not_contain_any", []) or []
    print(f"  カテゴリ: {cat.get('name')} (genre_id={genre_id}, "
          f"whitelist={len(name_whitelist)}語, blacklist={len(name_blacklist)}語)")
    items = fetch_top_items(
        genre_id=genre_id,
        keyword=cat.get("keyword_filter", ""),
        hits=cat.get("hits", 20),  # realtime は hits 上限 20（地雷#10）。fetch 側でも clamp 済
        min_reviews=cat.get("min_review_count", 0),
    )
    return filter_items(cat, items)


# ── メイン ──
def main():
    now = datetime.datetime.now(JST)
    today_str = now.strftime("%Y-%m-%d")
    weekday = now.weekday()  # 0=月..6=日
    print(f"=== カテゴリTOP1 {today_str} (weekday={weekday}) ===")

    # 重複投稿チェック
    posted = load_posted()
    if posted.get("last_posted_date") == today_str:
        print("  → 本日は既に投稿済みのためスキップ")
        return

    # カテゴリ取得 (2026-05-26 新スキーマ: weekdays[曜日] = サブカテゴリリスト)
    config = load_config()
    weekdays = config.get("weekdays", {})
    subs = weekdays.get(str(weekday), [])
    if not subs:
        # 旧スキーマ (categories[曜日] = 単一カテゴリ) との後方互換
        legacy_cat = config.get("categories", {}).get(str(weekday))
        if legacy_cat:
            subs = [legacy_cat]
        else:
            print(f"  → weekday={weekday} のカテゴリ未定義")
            return

    # 週ローテーション: 同じ曜日でも (週of年) で当番サブカテゴリを切り替え。
    # ただし当番サブが realtime TOP20 に1件も出てこない週がある（例: スイーツ
    # ジャンルTOP20 に「和菓子」が並ばない）。その場合は黙ってスキップせず、
    # 同じ曜日の他サブへ順にフォールバックして「必ず1投稿」を担保する（地雷#10再発防止）。
    week_of_year = now.isocalendar()[1]
    sub_index = week_of_year % len(subs)
    order = list(range(sub_index, len(subs))) + list(range(0, sub_index))

    chosen_cat = None
    chosen_items = None
    for n, i in enumerate(order):
        cat = subs[i]
        # active_months チェック（季節限定カテゴリ）
        active_months = cat.get("active_months")
        if active_months and now.month not in active_months:
            print(f"  [{i}] {cat.get('name')}: 今月({now.month})対象外 "
                  f"active_months={active_months} → 次サブへ")
            continue
        label = "当番" if n == 0 else f"フォールバック#{n}"
        print(f"  [{label}] 週={week_of_year} サブ[{i}/{len(subs)}] = {cat.get('name')}")
        items = collect_items_for_sub(cat)
        if len(items) >= 1:
            chosen_cat, chosen_items = cat, items
            break
        print(f"    ⚠️ 該当0件 → 次のサブへフォールバック")

    if not chosen_cat:
        print("  ⚠️ 全サブで該当アイテム0件 → 本日は投稿スキップ")
        return

    # ツイート組み立て＆投稿（TOP1 のみ集中投下）
    tweet = build_tweet(chosen_cat, chosen_items[:1])
    print(f"\n投稿内容:\n{tweet}\n（重み付き {weighted_length(tweet)} 文字）\n")

    if post_tweet(tweet):
        posted["last_posted_date"] = today_str
        posted["last_category"] = chosen_cat.get("name")
        save_posted(posted)
        print(f"✅ 完了")
    else:
        print("❌ post_tweet が False → exit 1（failure 通知用）", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
