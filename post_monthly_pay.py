#!/usr/bin/env python3
"""
post_monthly_pay.py
毎月2日に楽天ペイ月初ルーティンをツイート。
冗長感を避けるため、月毎にイントロ／締め文を季節合わせでローテーション。
"""

import os
import re
import sys
import json
import datetime
import requests
from requests_oauthlib import OAuth1

from hashtag_helper import hashtags

# ── 認証情報 ──
API_KEY             = os.environ["TWITTER_API_KEY"]
API_SECRET          = os.environ["TWITTER_API_SECRET"]
ACCESS_TOKEN        = os.environ["TWITTER_ACCESS_TOKEN"]
ACCESS_TOKEN_SECRET = os.environ["TWITTER_ACCESS_TOKEN_SECRET"]

JST = datetime.timezone(datetime.timedelta(hours=9))
SITE_URL = "https://imaraku.github.io/imaraku/imaraku.html"
POSTED_FILE = "monthly_pay_posted.json"


# ── 月別の文言ローテーション ──
# (intro, close) のペアを月ごとに用意。冗長を避ける狙い。
MONTHLY_VARIATIONS = {
    1:  ("🎍 新年の楽天ペイ仕切り直し",
         "今年もポイ活、コツコツ積もう✨"),
    2:  ("❄️ 2月の楽天ペイ整え月",
         "短い月だからこそ取りこぼしゼロを目指そう"),
    3:  ("🌸 3月のキャッシュレス整え",
         "新生活前に楽天ペイ周りも見直そう"),
    4:  ("🌷 新年度の楽天ペイ初期設定",
         "今年度もエントリー＆チャージから✨"),
    5:  ("🌿 GW中の楽天ペイ仕切り直し",
         "連休後半の支払いも楽天ペイで還元アップ"),
    6:  ("🌧️ ボーナス前の楽天ペイ準備",
         "夏ボーナスをポイントで増幅させよう"),
    7:  ("🎋 夏セール前の楽天ペイ仕込み",
         "セール本番までに上限まで活用しよう"),
    8:  ("🌻 夏休みの楽天ペイ点検",
         "旅行支払いも楽天ペイで還元アップ"),
    9:  ("🍂 秋の楽天ペイ仕切り直し",
         "新セール期に向けてエントリー一巡"),
    10: ("🍁 10月の楽天ペイ点検",
         "年末商戦前に取りこぼし防止"),
    11: ("🦃 ブラックフライデー前の準備",
         "11月後半の大型セールに備えよう"),
    12: ("🎄 年末の楽天ペイ駆け込み点検",
         "今年最後の取りこぼしゼロへ"),
}


def build_tweet(now: datetime.datetime) -> str:
    month = now.month
    intro, close = MONTHLY_VARIATIONS.get(month, ("💳 月初ルーティン", "今月もポイ活コツコツ✨"))

    body = (
        f"{intro}\n"
        "\n"
        f"💳 {month}月の楽天ペイ初期設定\n"
        "\n"
        "✅ SPU楽天ペイ条件 → 今月もエントリー\n"
        "✅ 楽天キャッシュ経由チャージ +0.5%\n"
        "✅ 5と0のつく日は楽天ペイ払いに\n"
        "\n"
        f"{close}\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'rakutenpay', 'poikatsu'], max_tags=3)}"
    )
    return body


def weighted_length(text: str) -> int:
    text_for_count = re.sub(r'https?://\S+', 'X' * 23, text)
    n = 0
    for ch in text_for_count:
        n += 1 if ord(ch) < 0x80 else 2
    return n


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


def main():
    now = datetime.datetime.now(JST)
    today_str = now.strftime("%Y-%m")  # 月単位で重複チェック
    print(f"=== 楽天ペイ月初ルーティン {now.strftime('%Y-%m-%d %H:%M JST')} ===")

    # 月初2日のみ実行（cron で日付指定するが、念のため日付ガード）
    if now.day != 2:
        print(f"  → 今日({now.day}日)は対象外。2日にのみ投稿")
        return

    # 同月内重複防止
    posted = {}
    if os.path.exists(POSTED_FILE):
        try:
            with open(POSTED_FILE, encoding='utf-8') as f:
                posted = json.load(f)
        except Exception:
            pass
    if posted.get("last_posted_month") == today_str:
        print(f"  → 今月({today_str})は既に投稿済 → スキップ")
        return

    tweet = build_tweet(now)
    print(f"\n投稿内容:\n{tweet}\n（重み付き {weighted_length(tweet)} 文字）\n")

    if post_tweet(tweet):
        posted["last_posted_month"] = today_str
        posted["last_fired_at"] = now.isoformat()
        with open(POSTED_FILE, 'w', encoding='utf-8') as f:
            json.dump(posted, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
