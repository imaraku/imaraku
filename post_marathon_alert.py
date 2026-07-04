#!/usr/bin/env python3
"""
post_marathon_alert.py
毎日 19:50 JST（= UTC 10:50）に実行。
マラソンが開催中 or まもなく開始の場合、X（Twitter）に事前告知ツイートを投稿する。
"""
 
import os
import re
import sys
import time
import json
import html as _html
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
 
 
def _post_once(text: str) -> tuple:
    """X API v2 でツイートを投稿する。(成功フラグ, ステータスコード)。
    api.twitter.com の Cloudflare マネージドチャレンジ(403 "Just a moment")対策として
    ブラウザ風 User-Agent を付与＋一時エラー(403CF/429/5xx)を最大3回リトライ（2026-05-31）。"""
    auth = OAuth1(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0.0.0 Safari/537.36"),
    }
    last_status = 0
    for attempt in range(1, 4):
        try:
            resp = requests.post(
                "https://api.twitter.com/2/tweets",
                auth=auth, json={"text": text}, headers=headers, timeout=20,
            )
        except requests.RequestException as e:
            print(f"❌ 投稿例外(試行{attempt}/3): {e}", file=sys.stderr)
            if attempt < 3:
                time.sleep(5 * attempt)
                continue
            return False, 0
        if resp.status_code == 201:
            tweet_id = resp.json()["data"]["id"]
            print(f"✅ ツイート投稿成功！ ID: {tweet_id}")
            return True, 201
        last_status = resp.status_code
        is_cf = resp.status_code == 403 and (
            "Just a moment" in resp.text or "cloudflare" in resp.text.lower()
            or "cf_chl" in resp.text)
        transient = is_cf or resp.status_code in (429, 500, 502, 503)
        reason = "Cloudflareチャレンジ" if is_cf else resp.text[:160]
        print(f"❌ 投稿失敗(試行{attempt}/3): {resp.status_code} {reason}", file=sys.stderr)
        if attempt < 3 and transient:
            time.sleep(5 * attempt)
            continue
        return False, resp.status_code
    return False, last_status


# imaraku.github.io URL の reputation 回復ガード（2026-05-22〜23 連続 403 経緯）。
# 6/1 までは事前削除、以降は試行 → 403 なら fallback。daily-tweet / check_ranking と同期。
URL_INCLUDE_FROM = datetime.date(2026, 6, 1)


def _strip_imaraku_url_lines(text: str) -> str:
    kept = [line for line in text.split("\n") if "imaraku.github.io" not in line]
    return "\n".join(kept).rstrip() + "\n" if kept else ""


def post_tweet(text: str) -> bool:
    today_jst = datetime.datetime.now(JST).date()
    if today_jst < URL_INCLUDE_FROM:
        no_url = _strip_imaraku_url_lines(text)
        if no_url != text:
            print(f"  [URL gate] {today_jst} < {URL_INCLUDE_FROM} のため imaraku URL を事前除去", file=sys.stderr)
        ok, _ = _post_once(no_url)
        return ok
    ok, status = _post_once(text)
    if ok:
        return True
    if status != 403:
        return False
    fallback_text = _strip_imaraku_url_lines(text)
    if fallback_text == text:
        return False
    print(f"  [403 fallback] imaraku URL を除去して再投稿…", file=sys.stderr)
    ok2, _ = _post_once(fallback_text)
    return ok2
 
 
WD_JP = ["月", "火", "水", "木", "金", "土", "日"]


def _fmt_dt(dt):
    return f"{dt.month}/{dt.day}({WD_JP[dt.weekday()]}){dt.hour}:{dt.minute:02d}"


def marathon_period_str():
    """marathon_schedule.json の pointup 期間を「M/D(曜)H:MM〜M/D(曜)H:MM」で返す。無ければ None。"""
    if not os.path.exists(MARATHON_SCHEDULE_FILE):
        return None
    try:
        with open(MARATHON_SCHEDULE_FILE) as f:
            s = json.load(f)
        ps = datetime.datetime.fromisoformat(s["pointup_start"])
        pe = datetime.datetime.fromisoformat(s["pointup_end"])
        if ps.tzinfo is None:
            ps = ps.replace(tzinfo=JST)
        if pe.tzinfo is None:
            pe = pe.replace(tzinfo=JST)
        return f"{_fmt_dt(ps)}〜{_fmt_dt(pe)}"
    except Exception:
        return None


def parse_marathon_cap():
    """マラソンページから獲得上限ポイント数を抽出（例 '10,000'）。取れなければ None（行を省略）。
    スーパーSALEと同じ「獲得上限ポイント数：X,XXXポイント」ラベル想定。タグ除去後に検索。
    ※マラソン開催時にラベルを実機確認して微調整する（非開催時は取得不可で省略＝安全）。"""
    try:
        t = requests.get(MARATHON_URL, headers=HEADERS, timeout=15).text
    except Exception:
        return None
    clean = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', _html.unescape(t)))
    m = re.search(r'獲得上限ポイント数[^0-9]{0,12}([\d,]{3,7})\s*ポイント', clean)
    return m.group(1) if m else None


def build_tweet(special_days, period=None, cap=None) -> str:
    """マラソン事前告知ツイートを生成。【期間】【上限】【倍率】を付与（相棒の要望 2026-06-05）。

    ※ X 重複検出回避: 今夜の日付を本文に埋め込みマラソン毎にユニークに。
    """
    now = datetime.datetime.now(JST)
    day_jp = WD_JP[now.weekday()]   # 旧「日月火水木金土」[weekday()] は曜日が1日ズレるバグだった
    date_prefix = f"📅 今夜 {now.month}/{now.day}({day_jp}) 20:00 START!\n\n"

    info = ""
    if period:
        info += f"🛒{period}\n"
    if cap:
        info += f"【上限】{cap}ポイント\n"
    info += "【倍率】買い回り最大10倍\n"

    if special_days:
        events = "・".join(special_days)
        return (
            f"{date_prefix}"
            f"🔥お買い物マラソン × {events}！\n"
            f"{info}"
            "ポイント最大のビッグチャンス🎯\n\n"
            "エントリーまとめ👇\n"
            f"{SITE_URL}\n"
            f" {hashtags(['core', 'marathon', 'poikatsu'], max_tags=3)}"
        )

    return (
        f"{date_prefix}"
        "🏃お買い物マラソン、もうすぐ開幕！\n"
        f"{info}"
        "注文前に必ずエントリーを✅\n\n"
        "20時から「今楽」でまとめて👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'marathon', 'entry'], max_tags=3)}"
    )
 
 
def is_pre_pointup_eve(now: datetime.datetime) -> bool:
    """事前告知を流すべき「ポイントアップ開始の当日（19:50時点）」かを判定。
    ── 厳格ガード設計（誤発信ゼロ優先・2026-05-06 改訂）──
      1. campaign_status.json の marathon_pointup が True なら既に開始済 → 流さない
      2. marathon_schedule.json の pointup_start が読めれば、その当日のみ True
      3. schedule が null/取得不能 → False（誤発信を避ける）
         以前は「True フォールバック」だったが、entry-only 期間中の毎日に
         「今夜20時から開始」と誤発信する事故があり方針転換。
    """
    # ① 既にポイントアップ期間中なら絶対に流さない
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
            # 時刻ガード: 開始時刻を過ぎていたら「今夜20:00 START!」は時系列逆転になる。
            # 2026-07-04 に cron遅延(19:50→20:48着地)＋status更新ラグで、開始48分後に
            # 事前告知を投稿した事故の恒久対策（フラグ鮮度に依存しない now との直接比較）。
            if now >= p_start:
                print(f"  → 既にポイントアップ開始時刻({p_start.strftime('%H:%M')})を過ぎている → 事前告知スキップ（時系列逆転防止）")
                return False
            print(f"  → 今日はポイントアップ開始日({p_start.date()})！告知GO")
            return True
        except Exception:
            pass

    # ③ schedule 未取得 → 誤発信回避のためスキップ
    # check_campaigns.py の extract_marathon_schedule() が抽出失敗を続ける場合は
    # marathon_schedule.json を手動編集（source: "manual"）するか、抽出ロジック改善を。
    print("  → schedule 未取得 → 安全のため事前告知スキップ（誤発信防止）")
    return False


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
    period = marathon_period_str()
    cap = parse_marathon_cap()
    print(f"特別な日: {special_days if special_days else 'なし'} / 期間: {period} / 上限: {cap}")
 
    tweet = build_tweet(special_days, period, cap)
    print(f"\n投稿内容:\n{tweet}\n")
    if post_tweet(tweet):
        try:
            with open(PREANNOUNCE_FIRED_FILE, "w") as f:
                json.dump({"last_fired_date": today, "fired_at": now.isoformat()}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"  ⚠️ 履歴保存失敗: {e}", file=sys.stderr)
    else:
        print("❌ post_tweet が False → exit 1（failure 通知用）", file=sys.stderr)
        sys.exit(1)
 
 
if __name__ == "__main__":
    main()
 
