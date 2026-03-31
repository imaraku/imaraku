#!/usr/bin/env python3
"""
post_marathon_alert.py
毎日 19:50 JST（= UTC 10:50）に実行。
マラソンが開催中 or まもなく開始の場合、X（Twitter）に事前告知ツイートを投稿する。
"""
 
import os
import sys
import json
import requests
from requests_oauthlib import OAuth1
 
# ── 認証情報（GitHub Secrets から取得）──────────────────────────────────
API_KEY             = os.environ["TWITTER_API_KEY"]
API_SECRET          = os.environ["TWITTER_API_SECRET"]
ACCESS_TOKEN        = os.environ["TWITTER_ACCESS_TOKEN"]
ACCESS_TOKEN_SECRET = os.environ["TWITTER_ACCESS_TOKEN_SECRET"]
 
CAMPAIGN_STATUS_FILE = "campaign_status.json"
SITE_URL = "https://imaraku.github.io/imaraku/imaraku.html"
 
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept-Language": "ja,en;q=0.9",
}
 
MARATHON_URL = "https://event.rakuten.co.jp/campaign/point-up/marathon/"
 
 
def check_marathon_active() -> bool:
    """マラソンが開催中 or 間もなく開始かをチェック。"""
    try:
        r = requests.get(MARATHON_URL, headers=HEADERS, timeout=15)
        text = r.text
        end_kw    = ["終了しました", "キャンペーンは終了", "受付終了"]
        active_kw = ["エントリーする", "エントリー受付中", "買いまわり", "マラソン開催中",
                     "エントリー期間"]
        if any(kw in text for kw in end_kw):
            return False
        if any(kw in text for kw in active_kw):
            return True
    except Exception as e:
        print(f"マラソン確認エラー: {e}", file=sys.stderr)
        # ローカルの campaign_status.json をフォールバックとして参照
        if os.path.exists(CAMPAIGN_STATUS_FILE):
            with open(CAMPAIGN_STATUS_FILE) as f:
                return json.load(f).get("marathon", False)
    return False
 
 
def post_tweet(text: str) -> bool:
    """X API v2 でツイートを投稿する。"""
    auth = OAuth1(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
    resp = requests.post(
        "https://api.twitter.com/2/tweets",
        auth=auth,
        json={"text": text},
        headers={"Content-Type": "application/json"},
    )
    if resp.status_code == 201:
        tweet_id = resp.json()["data"]["id"]
        print(f"✅ ツイート投稿成功！ ID: {tweet_id}")
        return True
    else:
        print(f"❌ 投稿失敗: {resp.status_code} {resp.text}", file=sys.stderr)
        return False
 
 
def main():
    print("=== マラソン事前告知チェック ===")
 
    active = check_marathon_active()
    print(f"マラソン開催状況: {'開催中/間もなく開始' if active else '非開催'}")
 
    if not active:
        print("マラソン非開催のため、投稿をスキップします。")
        return
 
    tweet = (
        "🏃‍♂️ 今日20時からお買物マラソン開始！\n"
        "\n"
        "注文前に必ずエントリーを✅\n"
        "\n"
        "エントリーなし→通常ポイント\n"
        "エントリーあり→最大16倍以上！\n"
        "\n"
        "20時になったら「今楽」でまとめてエントリー👇\n"
        f"{SITE_URL}\n"
        "\n"
        "#楽天 #お買物マラソン #ポイ活 #節約術"
    )
 
    print(f"投稿内容:\n{tweet}\n")
    post_tweet(tweet)
 
 
if __name__ == "__main__":
    main()
 
