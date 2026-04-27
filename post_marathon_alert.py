#!/usr/bin/env python3
"""
post_marathon_alert.py
毎日 19:50 JST（= UTC 10:50）に実行。
マラソンが開催中 or まもなく開始の場合、X（Twitter）に事前告知ツイートを投稿する。
"""
 
import os
import sys
import json
import datetime
import requests
from requests_oauthlib import OAuth1

from hashtag_helper import hashtags

# ── 認証情報（GitHub Secrets から取得）──────────────────────────────────
API_KEY             = os.environ["TWITTER_API_KEY"]
API_SECRET          = os.environ["TWITTER_API_SECRET"]
ACCESS_TOKEN        = os.environ["TWITTER_ACCESS_TOKEN"]
ACCESS_TOKEN_SECRET = os.environ["TWITTER_ACCESS_TOKEN_SECRET"]
 
CAMPAIGN_STATUS_FILE   = "campaign_status.json"
MARATHON_SCHEDULE_FILE = "marathon_schedule.json"
PREANNOUNCE_FIRED_FILE = "preannounce_fired.json"
SITE_URL  = "https://imaraku.github.io/imaraku/imaraku.html"
RAKKEN_URL = "https://event.rakuten.co.jp/rakken/?l-id=top_normal_menu_scene69"
APPLE_URL  = "https://event.rakuten.co.jp/computer/itunes/"
 
JST = datetime.timezone(datetime.timedelta(hours=9))
 
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
        if os.path.exists(CAMPAIGN_STATUS_FILE):
            with open(CAMPAIGN_STATUS_FILE) as f:
                return json.load(f).get("marathon", False)
    return False
 
 
def get_special_days(now: datetime.datetime) -> list:
    """今日の特別なキャンペーン日を返す。"""
    day = now.day
    special = []
    if day % 5 == 0:
        special.append("0と5のつく日")
    if day == 1:
        special.append("ワンダフルデー")
    if day == 18:
        special.append("楽天市場の日")
    return special
 
 
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
 
 
def build_tweet(special_days: list) -> str:
    """状況に応じたツイート文を生成する。"""
 
    if special_days:
        # マラソン × 特別日 → ビッグチャンス！
        events = "・".join(special_days)
        return (
            f"🔥 今夜20時からマラソン開始 & {events}！\n"
            "ポイントを最大限稼げるビッグチャンス🎯\n"
            "\n"
            "エントリーまとめ👇\n"
            f"{SITE_URL}\n"
            f" {hashtags(['core', 'marathon', 'poikatsu'], max_tags=3)}"
        )

    # 通常のマラソン事前告知（SPU控えめ、eギフト追記）
    return (
        "🏃 今夜20時からお買物マラソン開始！\n"
        "\n"
        "注文前に必ずエントリーを✅\n"
        "\n"
        "買いたいものがない方も\n"
        "楽券・Appleギフトで買い周りOK！\n"
        "\n"
        "20時から「今楽」でまとめて👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'marathon', 'entry'], max_tags=3)}"
    )
 
 
def is_pre_pointup_eve(now: datetime.datetime) -> bool:
    """事前告知を流すべき「ポイントアップ開始の当日（19:50時点）」かを判定。
    ── ガード設計（恒久対策）──
      1. campaign_status.json の marathon_pointup が True なら既に開始済 → 流さない
      2. marathon_schedule.json の pointup_start が読めれば、その当日のみ True
      3. schedule が null/取得不能 → 安全側で True（従来動作）にフォールバック
    """
    # ① 既にポイントアップ期間中なら絶対に流さない（今回の事故の直接の原因）
    status = {}
    if os.path.exists(CAMPAIGN_STATUS_FILE):
        try:
            with open(CAMPAIGN_STATUS_FILE) as f:
                status = json.load(f)
        except Exception:
            pass
    if status.get("marathon_pointup", False):
        print("  → marathon_pointup=true（既に開始済）→ 事前告知スキップ")
        return False

    # ② スケジュール JSON がある場合、ポイントアップ開始日と一致するときだけ True
    sched = {}
    if os.path.exists(MARATHON_SCHEDULE_FILE):
        try:
            with open(MARATHON_SCHEDULE_FILE) as f:
                sched = json.load(f)
        except Exception:
            pass
    p_start_str = sched.get("pointup_start")
    if p_start_str:
        try:
            p_start = datetime.datetime.fromisoformat(p_start_str)
            if p_start.tzinfo is None:
                p_start = p_start.replace(tzinfo=JST)
            if now.date() != p_start.date():
                print(f"  → 今日({now.date()}) ≠ pointup開始日({p_start.date()}) → 事前告知スキップ")
                return False
            print(f"  → 今日はポイントアップ開始日({p_start.date()})！告知GO")
            return True
        except Exception:
            pass

    # ③ schedule null → 既存ロジック（marathon=true で告知）にフォールバック
    print("  → schedule 未取得。marathon_pointup=false なので従来動作で告知GO")
    return True


def main():
    print("=== マラソン事前告知チェック ===")

    active = check_marathon_active()
    print(f"マラソン開催状況: {'開催中/間もなく開始' if active else '非開催'}")

    if not active:
        print("マラソン非開催のため、投稿をスキップします。")
        return

    now = datetime.datetime.now(JST)

    # 🛡️ 恒久ガード: ポイントアップ開始の前夜（=当日19:50）以外は流さない
    if not is_pre_pointup_eve(now):
        print("事前告知タイミングではないため、投稿をスキップします。")
        return

    # 🛡️ 冗長cron対策: 同じ日に複数のcronがfireしても1回しか投稿しない
    today = now.strftime("%Y-%m-%d")
    fired = {}
    if os.path.exists(PREANNOUNCE_FIRED_FILE):
        try:
            with open(PREANNOUNCE_FIRED_FILE) as f:
                fired = json.load(f)
        except Exception:
            pass
    if fired.get("last_fired_date") == today:
        print(f"  → 本日({today})は既に事前告知済 → スキップ")
        return

    special_days = get_special_days(now)
    print(f"特別な日: {special_days if special_days else 'なし'}")
 
    tweet = build_tweet(special_days)
    print(f"\n投稿内容:\n{tweet}\n")
    if post_tweet(tweet):
        try:
            with open(PREANNOUNCE_FIRED_FILE, "w") as f:
                json.dump({"last_fired_date": today, "fired_at": now.isoformat()}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"  ⚠️ 履歴保存失敗: {e}", file=sys.stderr)
 
 
if __name__ == "__main__":
    main()
 
