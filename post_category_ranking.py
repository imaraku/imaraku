#!/usr/bin/env python3
"""
post_category_ranking.py
曜日別にカテゴリTOP3を楽天Ichiba検索APIから取得し、X(Twitter)に投稿する。

【機能】
  ・曜日別カテゴリ（category_ranking.json）に基づいて検索キーワード決定
  ・楽天 IchibaItem/Search/20170706 API でレビュー数降順 TOP3 取得
  ・商品説明 (itemCaption) から推しポイント自動抽出
  ・アフィリエイトURL ラッピング
  ・1日1回まで（同日重複投稿防止）

【全自動】
  - 商品ピック: API のレビュー数降順 (人気順)
  - 推しポイント: itemCaption の最初の文 + レビュー平均/件数情報
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


def _compose_single_url(header: str, items: list, footer: str, name_limit: int) -> str:
    """1ツイート組み立て（URL は TOP1 商品のみ、TOP2/3 はテキストのみ）。
    X の spam検出回避のため、ツイート内URLは1本に抑える。
    消費者心理に応えるため、商品名+評価は3商品ぶん全部見せる。
    """
    rank_emojis = ["①", "②", "③"]
    body_lines = []
    for i, item in enumerate(items):
        item_name = shorten_name(item['name'], name_limit)
        rating = short_rating(item)
        if rating:
            body_lines.append(f"{rank_emojis[i]} {item_name} {rating}")
        else:
            body_lines.append(f"{rank_emojis[i]} {item_name}")
        # URL は TOP1（最初の商品）にだけ付ける
        if i == 0:
            body_lines.append("👇 ①の商品ページ")
            body_lines.append(aff(item["url"]))
        body_lines.append("")
    return header + "\n".join(body_lines).rstrip() + "\n\n" + footer


def build_tweet(category: dict, items: list) -> str:
    """カテゴリ＋上位アイテムからツイート文を作る。
    URL は TOP1 商品の1本のみに集約（403 spam検出回避）。
    商品名+⭐評価は3商品分すべて表示して、消費者の好奇心を満たす。

    フォールバック順:
      ① TOP3 + ⭐ + TOP1のみURL + tags
      ② TOP3 + ⭐ (短名) + TOP1のみURL + tags
      ③ TOP3 + ⭐ (極短名) + TOP1のみURL + tags (最終)
    """
    name = category.get("name", "TOP")
    emoji = category.get("emoji", "🏆")
    tags = hashtags(category.get("hashtags", ["core", "poikatsu"]), max_tags=3)

    header = f"{emoji} {name} TOP3\n\n"
    footer = f"\n {tags}"

    # name_limit を段階的に短くしてフィット試行
    candidates = [
        _compose_single_url(header, items[:3], footer, name_limit=22),
        _compose_single_url(header, items[:3], footer, name_limit=18),
        _compose_single_url(header, items[:3], footer, name_limit=14),
        _compose_single_url(header, items[:3], footer, name_limit=10),
    ]
    for c in candidates:
        if weighted_length(c) <= 280:
            return c
    return candidates[-1]


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


# ── メイン ──
def main():
    now = datetime.datetime.now(JST)
    today_str = now.strftime("%Y-%m-%d")
    weekday = now.weekday()  # 0=月..6=日
    print(f"=== カテゴリTOP3 {today_str} (weekday={weekday}) ===")

    # 重複投稿チェック
    posted = load_posted()
    if posted.get("last_posted_date") == today_str:
        print("  → 本日は既に投稿済みのためスキップ")
        return

    # カテゴリ取得
    config = load_config()
    cat = config.get("categories", {}).get(str(weekday))
    if not cat:
        print(f"  → weekday={weekday} のカテゴリ未定義")
        return

    # active_months チェック（季節限定カテゴリ）
    active_months = cat.get("active_months")
    if active_months and now.month not in active_months:
        print(f"  → 今月({now.month})は対象外（active_months={active_months}）")
        return

    genre_id = cat.get("genreId")
    if not genre_id:
        print(f"  ⚠️ {cat.get('name')} に genreId 未設定 → スキップ")
        return
    keyword_filter = cat.get("keyword_filter", "")
    print(f"  カテゴリ: {cat.get('name')} (genreId={genre_id}, filter={keyword_filter!r})")

    # 楽天ランキングAPIで上位アイテム取得（リアルタイムランキング）
    items = fetch_top_items(
        genre_id=genre_id,
        keyword=keyword_filter,
        hits=cat.get("hits", 20),
        min_reviews=cat.get("min_review_count", 0),
    )
    if len(items) < 3:
        print(f"  ⚠️ 該当アイテム不足: {len(items)} 件 → スキップ")
        return

    # ツイート組み立て＆投稿
    tweet = build_tweet(cat, items[:3])
    print(f"\n投稿内容:\n{tweet}\n（重み付き {weighted_length(tweet)} 文字）\n")

    if post_tweet(tweet):
        posted["last_posted_date"] = today_str
        posted["last_category"] = cat.get("name")
        save_posted(posted)
        print(f"✅ 完了")
    else:
        print("❌ post_tweet が False → exit 1（failure 通知用）", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
