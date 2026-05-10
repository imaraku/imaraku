#!/usr/bin/env python3
"""
post_mega_chance.py
月一の「最強日」検知＆アナウンス投稿。

【最強日の定義】
  ・campaign_status.marathon_pointup == True（マラソン買いまわり中）
  ・今日が「0と5のつく日」（5,10,15,20,25,30日）
  ・かつ、当該マラソン期間中の **最初の** 0/5の日

【発火タイミング】
  毎日 7:00 JST に実行、最強日に該当する日だけ投稿。
  月一回しか発火しない（マラソン期間中の最初の0/5の日のみ）。

【独自価値】
  ・SPU上限がまだ残っているため最も還元が大きい日
  ・同じマラソン2巡目以降の0/5日より「初回」が桁違いに有利
  ・相棒のドメイン知識から得た inside info。多くのポイ活民が見落としがち
"""

import os
import re
import sys
import json
import datetime
import requests
from requests_oauthlib import OAuth1

from hashtag_helper import hashtags

API_KEY             = os.environ["TWITTER_API_KEY"]
API_SECRET          = os.environ["TWITTER_API_SECRET"]
ACCESS_TOKEN        = os.environ["TWITTER_ACCESS_TOKEN"]
ACCESS_TOKEN_SECRET = os.environ["TWITTER_ACCESS_TOKEN_SECRET"]

JST = datetime.timezone(datetime.timedelta(hours=9))
SITE_URL = "https://imaraku.github.io/imaraku/imaraku.html"
POSTED_FILE = "mega_chance_posted.json"


def load_json(path: str, default):
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return default


def is_mega_chance_today(now: datetime.datetime) -> bool:
    """今日が「月初回マラソン × 最初の0/5の日」かを判定"""
    # ① マラソン買いまわり期間中？
    status = load_json("campaign_status.json", {})
    if not status.get("marathon_pointup"):
        return False

    # ② 今日が0/5の日？
    if now.day % 5 != 0:
        return False

    # ③ マラソン pointup_start が読めて、今日が最初の0/5の日か？
    sched = load_json("marathon_schedule.json", {})
    p_start_str = sched.get("pointup_start")
    if not p_start_str:
        return False
    try:
        p_start = datetime.datetime.fromisoformat(p_start_str)
        if p_start.tzinfo is None:
            p_start = p_start.replace(tzinfo=JST)
    except Exception:
        return False

    # マラソン開始日から今日まで、毎日チェック
    # → 「今日より前に既に0/5の日があった」なら False
    cur = p_start.date()
    today = now.date()
    while cur < today:
        if cur.day % 5 == 0:
            return False  # 既に過去の0/5日が当該マラソン中にあった
        cur += datetime.timedelta(days=1)

    return True


def build_tweet(now: datetime.datetime) -> str:
    """最強日アナウンスツイート"""
    return (
        f"💎 {now.month}/{now.day} は月一の最強日🔥\n"
        "\n"
        "🏃 お買い物マラソン買いまわり中\n"
        "🎯 0と5のつく日 +1%\n"
        "\n"
        "💡 SPU上限がまだ残ってる初回が最強。\n"
        "月2回目以降より圧倒的にお得です\n"
        "\n"
        "今日のキャンペーン👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'marathon', 'poikatsu'], max_tags=3)}"
    )


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
    today_str = now.strftime("%Y-%m-%d")
    print(f"=== 最強日アナウンス {now.strftime('%Y-%m-%d %H:%M JST')} ===")

    if not is_mega_chance_today(now):
        print("  → 今日は最強日ではない → スキップ")
        return

    print("  → 今日は月一の最強日！🔥")

    # 月次重複排除（同じマラソンの最初の0/5日に複数回投稿しない）
    posted = load_json(POSTED_FILE, {})
    if posted.get("last_posted_date") == today_str:
        print(f"  → 今日({today_str})は既に投稿済 → スキップ")
        return

    tweet = build_tweet(now)
    print(f"\n投稿内容 ({weighted_length(tweet)}字):\n{tweet}\n")

    if post_tweet(tweet):
        posted["last_posted_date"] = today_str
        posted["last_fired_at"] = now.isoformat()
        with open(POSTED_FILE, 'w', encoding='utf-8') as f:
            json.dump(posted, f, ensure_ascii=False, indent=2)
    else:
        print("❌ post_tweet が False → exit 1（failure 通知用）", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
