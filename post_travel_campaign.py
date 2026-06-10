#!/usr/bin/env python3
"""
post_travel_campaign.py
0と5のつく日（マラソン非開催時）に楽天トラベル特集をツイートする。
月に最大2回まで（travel_posted.json で重複排除）。
"""

import os
import re
import sys
import json
import time
import datetime
import requests
from urllib.parse import quote
from requests_oauthlib import OAuth1

from hashtag_helper import hashtags
from link_guard import filter_alive  # リンク先の生存チェック（終了ページを投稿しない・地雷#19）

# ── 認証情報 ──
API_KEY             = os.environ["TWITTER_API_KEY"]
API_SECRET          = os.environ["TWITTER_API_SECRET"]
ACCESS_TOKEN        = os.environ["TWITTER_ACCESS_TOKEN"]
ACCESS_TOKEN_SECRET = os.environ["TWITTER_ACCESS_TOKEN_SECRET"]

JST = datetime.timezone(datetime.timedelta(hours=9))
SITE_URL = "https://imaraku.github.io/imaraku/imaraku.html"
CONFIG_FILE = "travel_campaigns.json"
POSTED_FILE = "travel_posted.json"
CAMPAIGN_STATUS = "campaign_status.json"
RAKUTEN_AFFILIATE_ID = "1c52abea.36641b1e.1c52abeb.f5f67f16"

MAX_POSTS_PER_MONTH = 2


def aff(url: str) -> str:
    """楽天ドメインのURLをアフィリエイトハブ経由に変換"""
    if not url or 'rakuten' not in url:
        return url
    if 'hb.afl.rakuten.co.jp' in url or 'a.r10.to' in url:
        return url
    encoded = quote(url, safe='')
    return f"https://hb.afl.rakuten.co.jp/hgc/{RAKUTEN_AFFILIATE_ID}/?pc={encoded}&m={encoded}"


def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def weighted_length(text: str) -> int:
    text_for_count = re.sub(r'https?://\S+', 'X' * 23, text)
    n = 0
    for ch in text_for_count:
        n += 1 if ord(ch) < 0x80 else 2
    return n


UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def post_tweet(text: str) -> bool:
    """X 投稿。Cloudflare 403 / 429 / 5xx は最大3回リトライ（地雷#15）。"""
    auth = OAuth1(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
    headers = {"Content-Type": "application/json", "User-Agent": UA}
    for attempt in range(1, 4):
        try:
            resp = requests.post("https://api.twitter.com/2/tweets",
                                 auth=auth, json={"text": text}, headers=headers, timeout=20)
        except requests.RequestException as ex:
            print(f"❌ 投稿例外(試行{attempt}/3): {ex}", file=sys.stderr)
            if attempt < 3:
                time.sleep(5 * attempt)
                continue
            return False
        if resp.status_code == 201:
            print(f"✅ 投稿成功: {resp.json()['data']['id']}")
            return True
        is_cf = resp.status_code == 403 and (
            "Just a moment" in resp.text or "cloudflare" in resp.text.lower() or "cf_chl" in resp.text)
        transient = is_cf or resp.status_code in (429, 500, 502, 503)
        print(f"❌ 投稿失敗(試行{attempt}/3): {resp.status_code} "
              f"{'Cloudflareチャレンジ' if is_cf else resp.text[:160]}", file=sys.stderr)
        if attempt < 3 and transient:
            time.sleep(5 * attempt)
            continue
        return False
    return False


def is_zero_or_five_day(day: int) -> bool:
    """0または5のつく日: 5, 10, 15, 20, 25, 30"""
    return day % 5 == 0 and day >= 5


def is_marathon_active() -> bool:
    """campaign_status.json で marathon が開催中か"""
    status = load_json(CAMPAIGN_STATUS, {})
    return bool(status.get("marathon", False))


def build_tweet(now: datetime.datetime, tweet_def: dict) -> str:
    """value-first・リンク1本のツイートを作る。
    旧形式（item毎に生アフィURLを羅列）は hb.afl... の長い文字列が並んでスパムに
    見えるため廃止（2026-06-11 相棒指摘）。先頭キャンペーンだけリンクし、残りはテキスト紹介。
    items は呼び出し側で link_guard 済み（生きているリンクのみ）の前提。"""
    items = tweet_def.get("items", [])
    if not items:
        return ""
    today_label = f"{now.month}/{now.day}"
    featured = items[0]
    others = [it.get("label", "") for it in items[1:] if it.get("label")]

    def compose(featured_label: str, include_others: bool) -> str:
        lines = [
            f"✈️ {today_label}は楽天トラベルがお得！（0と5のつく日）",
            "",
            featured_label,
            "詳細・予約はこちら👇",
            aff(featured.get("url", "")),
        ]
        if include_others and others:
            lines += ["", "ほかにも👀 " + "／".join(others)]
        lines += ["", f" {hashtags(['core', 'travel', 'poikatsu'], max_tags=3)}"]
        return "\n".join(lines)

    tweet = compose(featured.get("label", ""), True)
    if weighted_length(tweet) > 280:
        tweet = compose(featured.get("label", ""), False)   # 「ほかにも」行を落とす
    if weighted_length(tweet) > 280:
        tweet = compose(featured.get("label", "")[:20] + "…", False)
    return tweet


def main():
    now = datetime.datetime.now(JST)
    today_str = now.strftime("%Y-%m-%d")
    month_key = now.strftime("%Y-%m")
    print(f"=== 楽天トラベル特集 {now.strftime('%Y-%m-%d %H:%M JST')} ===")

    # 0または5のつく日チェック
    if not is_zero_or_five_day(now.day):
        print(f"  → {now.day}日は対象外（5,10,15,20,25,30 のみ）→ スキップ")
        return

    # マラソン非開催チェック
    if is_marathon_active():
        print(f"  → マラソン開催中 → トラベル特集は控える（マラソン優先）")
        return

    # 月次重複排除
    posted = load_json(POSTED_FILE, {})
    posts_this_month = posted.get(month_key, [])
    if today_str in posts_this_month:
        print(f"  → 本日({today_str})は既に投稿済み → スキップ")
        return
    if len(posts_this_month) >= MAX_POSTS_PER_MONTH:
        print(f"  → 今月既に{len(posts_this_month)}回投稿済み（上限{MAX_POSTS_PER_MONTH}）→ スキップ")
        return

    # 設定読み込み
    config = load_json(CONFIG_FILE, {})
    tweet_defs = config.get("tweets", [])
    if not tweet_defs:
        print("  → travel_campaigns.json が空 → スキップ")
        return

    print(f"  対象ツイート定義: {len(tweet_defs)} 件")

    # ツイート組み立て＆投稿（リンク先の生存チェック→生きているものだけで構成）
    success_count = 0
    for i, td in enumerate(tweet_defs, start=1):
        print(f"\n[{i}] リンク先の生存チェック中…")
        alive_items = filter_alive(td.get("items", []))
        if not alive_items:
            print(f"[{i}] 生きているリンクが1本も無い → このツイートはスキップ（終了ページを案内しない）")
            continue
        tweet = build_tweet(now, {**td, "items": alive_items})
        print(f"\n[{i}] ({weighted_length(tweet)}字):\n{tweet}\n")
        if post_tweet(tweet):
            success_count += 1
        time.sleep(3)  # API rate limit 配慮

    if success_count > 0:
        posts_this_month.append(today_str)
        posted[month_key] = posts_this_month
        with open(POSTED_FILE, 'w', encoding='utf-8') as f:
            json.dump(posted, f, ensure_ascii=False, indent=2)
        print(f"\n✅ {success_count}/{len(tweet_defs)} 投稿完了。今月の投稿: {len(posts_this_month)}回目")


if __name__ == "__main__":
    main()
