#!/usr/bin/env python3
"""
post_daily_tweet.py
毎朝 9:00 JST（= 0:00 UTC）に実行。
今日のキャンペーン状況・曜日・日付に応じたツイートを投稿する。

【優先度順】
  1. マラソン × W勝利 × 特別日                           → トリプル役満（W勝利版）
  2. マラソン × W勝利                                    → マラソン×W勝利
  3. マラソン × 片チーム勝利                             → マラソン×単勝利
  4. マラソン × 特別日 × adidas開催中                    → トリプル役満（adidas）
  5. マラソン × 特別日 × nike開催中                      → トリプル役満（NIKE）
  6. マラソン × 特別日                                   → ビッグチャンス
  7. マラソン（ポイントアップ中）                        → eギフト活用ヒント
  8. マラソン（エントリー期間のみ）                      → 事前エントリー促進
  9. 月末2日（前日・最終日）※マラソン無し時              → 期間限定ポイント失効注意
 10. W勝利/片勝利 × 特別日                               → レアチャンス
 11. 季節イベント（母の日・父の日・クリスマス等）       → 季節イベント告知
 12. ワンダフルデー（1日）/ 楽天市場の日（18日）         → 各特別日告知
 13. 0と5のつく日                                        → ふるさと納税アピール
 14. W勝利 / 片勝利                                      → 勝利ボーナス告知
 15. 土曜 × adidas / 日曜 × NIKE                         → 各ブランド特集
 16. 通常日                                              → 39ショップ・リピート・ゲリラ告知
"""

import os
import sys
import time
import json
import datetime
import requests
from urllib.parse import quote
from requests_oauthlib import OAuth1

from hashtag_helper import hashtags

# ── アフィリエイト ──
RAKUTEN_AFFILIATE_ID = "1c52abea.36641b1e.1c52abeb.f5f67f16"


def aff(url: str) -> str:
    """楽天URLを公式アフィリエイトハブ経由に変換（imaraku.html aff() と同形式）。
    既に hb.afl 経由 / a.r10.to 短縮URL / 楽天以外のドメインはそのまま返す。
    """
    if not url or 'rakuten' not in url:
        return url
    if 'hb.afl.rakuten.co.jp' in url or 'a.r10.to' in url:
        return url
    encoded = quote(url, safe='')
    return f"https://hb.afl.rakuten.co.jp/hgc/{RAKUTEN_AFFILIATE_ID}/?pc={encoded}&m={encoded}"

# ── 認証情報（GitHub Secrets から取得）──────────────────────────────────
API_KEY             = os.environ["TWITTER_API_KEY"]
API_SECRET          = os.environ["TWITTER_API_SECRET"]
ACCESS_TOKEN        = os.environ["TWITTER_ACCESS_TOKEN"]
ACCESS_TOKEN_SECRET = os.environ["TWITTER_ACCESS_TOKEN_SECRET"]

CAMPAIGN_STATUS_FILE   = "campaign_status.json"
MARATHON_SCHEDULE_FILE = "marathon_schedule.json"

# ── URL 定義 ────────────────────────────────────────────────────────────
SITE_URL_BASE = "https://imaraku.github.io/imaraku/imaraku.html"   # 自サイト（ラップ不要）
# 日替わり cache-buster クエリ付き URL。
# X は同じURL文字列を高頻度で投稿すると content-similarity / spam検出で 403 を返すことがある
# (2026-05-22 確認: ranking-check は別ドメインURLで成功、daily-tweet だけ imaraku URL で連続403)。
# モジュール load 時に今日の日付を埋め込むことで、cron 各 fire で literal URL を毎日変える。
# リンク先は同じページに着地するのでユーザー体験は無変化。
# 【注意】このモジュールトップレベル評価式は JST 定数定義より前に位置するため、
# tzinfo はインラインで構築する（後段の JST = ... に依存しない）。
_JST_FOR_URL = datetime.timezone(datetime.timedelta(hours=9))
SITE_URL = f"{SITE_URL_BASE}?d={datetime.datetime.now(_JST_FOR_URL).strftime('%Y%m%d')}"
# 期間限定ポイント残高チェック（月末失効注意ツイート用・相棒のアフィリエイト経由）
POINT_CHECK_URL = aff("https://point.rakuten.co.jp/")
# 楽天系URLは aff() でラップして使う（直接定義は raw URL）
SPORTS_URL    = aff("https://event.rakuten.co.jp/campaign/sports/?l-id=top_normal_flashbnr_10_EECDCECB_160268_0")
RAKKEN_URL    = aff("https://event.rakuten.co.jp/rakken/")
APPLE_URL     = aff("https://event.rakuten.co.jp/computer/itunes/")
POINTDAY_URL  = aff("https://event.rakuten.co.jp/card/pointday/")

# adidas（既に a.r10.to 短縮URL = アフィリエイトID埋め込み済）
ADIDAS_50   = "https://a.r10.to/h5AdfJ"
ADIDAS_40   = "https://a.r10.to/h5s1YF"
ADIDAS_30   = "https://a.r10.to/hYB6gY"
ADIDAS_20   = "https://a.r10.to/h5WwCG"

# NIKE
NIKE_URL    = aff("https://item.rakuten.co.jp/nike-official/cj9583-100/")

JST = datetime.timezone(datetime.timedelta(hours=9))


# ── ユーティリティ ────────────────────────────────────────────────────────

def load_status() -> dict:
    if os.path.exists(CAMPAIGN_STATUS_FILE):
        try:
            with open(CAMPAIGN_STATUS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def load_marathon_schedule() -> dict:
    if os.path.exists(MARATHON_SCHEDULE_FILE):
        try:
            with open(MARATHON_SCHEDULE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


KICKOFF_FIRED_FILE = "kickoff_fired.json"
POSTED_SLOTS_FILE  = "posted_slots.json"


# ── スロット別の時間帯挨拶（X の重複検出を回避するための差分化） ──
# 【方針】単純な固定intro だけでは X の重複検出を回避しきれなかったため、
# 日付（M/D） + 曜日 + 時間帯 を組み合わせて毎回100%ユニークなintroを生成する。
# 4スロット × 365日 = 1460種類の組み合わせが自動生成される。
SLOT_TIME_PHRASES = {
    "0":  ("🌙", "おやすみ前のエントリーチェック"),
    "12": ("☀️", "お昼のエントリー忘れずに"),
    "18": ("🌆", "夕方の買い物前にエントリー"),
    "20": ("🌃", "今夜の買い物前にエントリー"),
}

WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]


def with_slot_intro(tweet: str, slot: str, now: datetime.datetime = None) -> str:
    """スロット別の挨拶を先頭に付けて、テキストを毎回ユニークにする。
    日付＋曜日を含めることで、X の重複投稿検出を確実に回避する。
    例: 🌃 5/9(土) 今夜の買い物前にエントリー

    ⚠️ 二段ヘッダ防止: 大半のテンプレは本文先頭で daily_lead_in() の
    「📅 M/D(曜) …チェック」ヘッダを既に持つ。本関数のヘッダと重なると
    日付行が二段になり不自然なので、先頭の daily_lead_in 段落を剥がして
    から付け直し、「日付＋曜日＋スロット文脈」を一段に集約する。
    （kickoff だけは with_slot_intro を通さず daily_lead_in をそのまま使う）
    """
    pair = SLOT_TIME_PHRASES.get(slot)
    if not pair:
        return tweet
    emoji, phrase = pair
    if now is None:
        now = datetime.datetime.now(JST)
    weekday_jp = WEEKDAY_JP[now.weekday()]
    intro = f"{emoji} {now.month}/{now.day}({weekday_jp}) {phrase}"
    # 既に同じ intro が付いていれば二重付与しない
    if tweet.startswith(intro):
        return tweet
    # daily_lead_in() の「📅 …」ヘッダ段落が先頭にあれば剥がす（二段ヘッダ防止）
    if tweet.startswith("📅 "):
        parts = tweet.split("\n\n", 1)
        if len(parts) == 2:
            tweet = parts[1]
    return f"{intro}\n\n{tweet}"


# ── 時間帯スロット重複排除 ──────────────────────────────────────────────
# GitHub Actions の cron は best-effort で取りこぼされることがある。
# 各スロットに複数の cron を仕込んで冗長化する代わりに、ここで
# 「今日のこのスロットは既に投稿済か」を判定して二重投稿を防ぐ。

# 各スロットの「許容投稿時間帯」: スロット名 → (開始hour, 終了hour)
# 通常日のスロット: 昼+夕の2投稿。窓は cron 遅延着地(地雷#5/#16)も拾えるよう広めに取る。
NORMAL_SLOTS = [
    ("12", 10, 16),  # 昼スロット JST 10:00-15:59
    ("18", 16, 22),  # 夕スロット JST 16:00-21:59（遅延着地20-21時も救済）
]
# 最強の日(=大型セール×0と5の日)のスロット: 昼+夕+夜の3投稿で露出を増やす。
# 夕(18)を16-20に狭め、夜(20)を20-23に新設して窓を重複させない。
PEAK_SLOTS = [
    ("12", 10, 16),  # 昼スロット JST 10:00-15:59
    ("18", 16, 20),  # 夕スロット JST 16:00-19:59
    ("20", 20, 23),  # 夜スロット JST 20:00-22:59（ピーク日のみ）
]


def is_peak_day(now: datetime.datetime, status: dict) -> bool:
    """最強の日 = 大型セール(マラソンpointup or スーパーSALE)開催中 × 0と5のつく日。
    相棒の定義: 月1回目マラソン×0と5 / スーパーSALEの最初の0と5 が最強クラス。
    （ここでは「セール×0と5」で広く判定。1日/18日は通常スロットで big_chance になる）"""
    sale = status.get("marathon_pointup", False) or status.get("supersale", False)
    return bool(sale) and (now.day % 5 == 0)


def current_slot(now: datetime.datetime, peak: bool = False):
    """現在時刻がどのスロットに該当するかを返す（該当なしなら None）。
    peak=True（最強の日）なら夜20時スロットを加えた3枠で判定する。"""
    h = now.hour
    windows = PEAK_SLOTS if peak else NORMAL_SLOTS
    for name, start, end in windows:
        if start <= h < end:
            return name
    return None


def load_posted_slots() -> dict:
    if os.path.exists(POSTED_SLOTS_FILE):
        try:
            with open(POSTED_SLOTS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def is_slot_posted(slot: str, today: str) -> bool:
    data = load_posted_slots()
    return slot in data.get(today, [])


def mark_slot_posted(slot: str, today: str) -> None:
    data = load_posted_slots()
    today_slots = data.setdefault(today, [])
    if slot not in today_slots:
        today_slots.append(slot)
    # 7日より古い履歴を掃除
    cutoff = (datetime.datetime.now(JST) - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    for k in list(data.keys()):
        if k < cutoff:
            del data[k]
    try:
        with open(POSTED_SLOTS_FILE, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  ⚠️ posted_slots保存失敗: {e}", file=sys.stderr)


def is_marathon_kickoff(now: datetime.datetime) -> bool:
    """ポイントアップ開始から 90 分以内なら True（＝ヨーイドン枠）。
    ── 三重ガード ──
      1. schedule.json に pointup_start が無ければ False（暴発防止）
      2. 「pointup_start から -10分 〜 +90分」の窓内
      3. 「同じ pointup_start に対して既に発火済」なら False（再発火防止）
    """
    sched = load_marathon_schedule()
    p_start_str = sched.get("pointup_start")
    if not p_start_str:
        return False
    try:
        p_start = datetime.datetime.fromisoformat(p_start_str)
    except Exception:
        return False
    if p_start.tzinfo is None:
        p_start = p_start.replace(tzinfo=JST)

    # 当日縛り（暴発防止）
    if now.date() != p_start.date():
        return False

    # 時間窓（-10分 〜 +90分）
    delta = (now - p_start).total_seconds()
    if not (-600 <= delta <= 5400):
        return False

    # 既に発火済かチェック（同じ pointup_start に対しては1回限り）
    fired = {}
    if os.path.exists(KICKOFF_FIRED_FILE):
        try:
            with open(KICKOFF_FIRED_FILE) as f:
                fired = json.load(f)
        except Exception:
            pass
    if fired.get("pointup_start") == p_start_str:
        print(f"  → kickoff 既発火済（{p_start_str}）→ スキップ")
        return False

    return True


def mark_kickoff_fired(p_start_str: str) -> None:
    """ヨーイドン発火履歴を記録（同じ pointup_start での再発火を防ぐ）。"""
    try:
        with open(KICKOFF_FIRED_FILE, "w") as f:
            json.dump({"pointup_start": p_start_str, "fired_at": datetime.datetime.now(JST).isoformat()}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  ⚠️ kickoff履歴の保存失敗: {e}", file=sys.stderr)


def get_special_days(now: datetime.datetime) -> list:
    """今日の特別なキャンペーン日を返す（マラソン×特別日の判定に使用）。"""
    day = now.day
    special = []
    if day % 5 == 0:          # 5, 10, 15, 20, 25, 30日
        special.append("0と5のつく日")
    if day == 1:
        special.append("ワンダフルデー")
    if day == 18:
        special.append("楽天市場の日")
    return special


def get_month_end_phase(now: datetime.datetime) -> str | None:
    """月末2日間の判定。
       - 前日（最後から2日目）: "eve"
       - 最終日                : "last"
       - それ以外              : None
       月の日数に応じて自動計算（31日月/30日月/2月28日/2月29日すべて対応）。
    """
    import calendar
    last_day = calendar.monthrange(now.year, now.month)[1]
    if now.day == last_day - 1:
        return "eve"
    if now.day == last_day:
        return "last"
    return None


def get_season_event(now: datetime.datetime) -> str | None:
    """今日の季節イベントを返す（なければNone）。"""
    year, month, day = now.year, now.month, now.day
    weekday = now.weekday()   # 0=月 … 6=日
    today = datetime.date(year, month, day)

    if month == 1 and 1 <= day <= 3:
        return "年始"
    if month == 2 and day == 14:
        return "バレンタイン"
    if month == 3 and day == 14:
        return "ホワイトデー"
    if month == 5 and weekday == 6:   # 5月の日曜
        first = datetime.date(year, 5, 1)
        offset = (6 - first.weekday()) % 7
        if today == first + datetime.timedelta(days=offset + 7):
            return "母の日"
    if month == 6 and weekday == 6:   # 6月の日曜
        first = datetime.date(year, 6, 1)
        offset = (6 - first.weekday()) % 7
        if today == first + datetime.timedelta(days=offset + 14):
            return "父の日"
    if month == 12 and day == 24:
        return "クリスマスイブ"
    if month == 12 and day == 25:
        return "クリスマス"
    return None


def _post_once(text: str) -> tuple[bool, int]:
    """1回 X に投げる（Cloudflare 403/429/5xx は最大3回リトライ）。(成功, ステータス) を返す。
    api.twitter.com の Cloudflare マネージドチャレンジ(403 "Just a moment")対策として
    ブラウザ風 User-Agent を付与＋一時エラーをリトライ（2026-05-31）。"""
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
            print(f"✅ 投稿成功: {resp.json()['data']['id']}")
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


# imaraku.github.io URL を本文に含めるかの日付ゲート。
# 2026-05-22〜23 に X が daily-tweet の URL を flag → 連続 403 を喰らった経緯から、
# reputation 回復のために 6/1 まで URL なし投稿に固定する。6/1 以降は試行→403なら fallback で耐える。
URL_INCLUDE_FROM = datetime.date(2026, 6, 1)


def _strip_imaraku_url_lines(text: str) -> str:
    """imaraku.github.io を含む行を全部削除する。URL なし版本文を返す。"""
    kept = [line for line in text.split("\n") if "imaraku.github.io" not in line]
    return "\n".join(kept).rstrip() + "\n" if kept else ""


def _strip_all_url_lines(text: str) -> str:
    """http(s):// を含む行を全部削除する（403 フォールバック用・完全 URL なし版）。"""
    kept = [line for line in text.split("\n")
            if "http://" not in line and "https://" not in line]
    return "\n".join(kept).rstrip() + "\n" if kept else ""


def post_tweet(text: str) -> bool:
    """X に投稿。

    - URL_INCLUDE_FROM より前: imaraku URL は事前削除（既知flag）。残る他URL(point等)は
      付けて試行 → 403 なら URL を全除去して再投稿（＝ツイートは必ず通す保険）
    - URL_INCLUDE_FROM 以降: URL 付きで試行 → 403 なら imaraku URL を抜いて 1度リトライ

    背景: 2026-05-22〜23 に imaraku.github.io URL を含む daily-tweet が
    cache-buster クエリを足してもなお 403 を喰らった。X 側がこのドメインを
    bot 連投と判定して flag している疑い。6/1 まで投稿を抑えて reputation 自然回復を待つ。
    ※ 月末ポイントツイート等が point.rakuten.co.jp(hb.afl) を持つので、6/1前でも
      「URL付きで試す→ダメなら URL なしで通す」フォールバックで取りこぼしを防ぐ。
    """
    today_jst = datetime.datetime.now(JST).date()

    if today_jst < URL_INCLUDE_FROM:
        # 6/1 以前: imaraku URL（既知flag）は事前除去。それ以外のURLは付けて試す。
        text2 = _strip_imaraku_url_lines(text)
        if text2 != text:
            print(f"  [URL gate] {today_jst} < {URL_INCLUDE_FROM} のため imaraku URL を事前除去", file=sys.stderr)
        ok, status = _post_once(text2)
        if ok:
            return True
        if status != 403:
            return False
        # 403: 残るURL(point等)も諦めて URL なしで再投稿 → ツイート自体は必ず通す
        bare = _strip_all_url_lines(text2)
        if bare == text2:
            return False  # 既に URL なし → これ以上手は無い
        print("  [403 fallback] 残りのURLも除去して URLなしで再投稿…", file=sys.stderr)
        ok2, _ = _post_once(bare)
        return ok2

    # 6/1 以降: URL 付きで挑戦 → 403 ならフォールバック
    ok, status = _post_once(text)
    if ok:
        return True
    if status != 403:
        return False
    fallback_text = _strip_imaraku_url_lines(text)
    if fallback_text == text:
        return False  # 元から URL なし → 再試行する意味なし
    print(f"  [403 fallback] imaraku URL を除去して再投稿…", file=sys.stderr)
    ok2, _ = _post_once(fallback_text)
    return ok2


# ── ツイート文 生成 ────────────────────────────────────────────────────────

# 現在実行中のスロット名（"12" / "18"）。main() から set される。
# テンプレ側の daily_lead_in() がスロット別の挨拶を出すために参照。
_CURRENT_SLOT: str = ""


def daily_lead_in() -> str:
    """全テンプレ先頭に挿入する日替わり文脈行。
    X の重複投稿検出（〜30日窓）回避が主目的。同時に読者に
    「今日いつ流れてきたツイートか」が一目で分かる情報価値も提供する。

    出力例:
      📅 5/21(木) 🌞 お昼チェック
      📅 5/21(木) 🌆 帰り道チェック
    """
    now = datetime.datetime.now(JST)
    # weekday() は月曜=0 始まり。"日月火…"[weekday()] だと曜日が1日ズレる
    # （金曜→"木" 等）バグだったので Mon 始まりの WEEKDAY_JP を使う。
    day_jp = WEEKDAY_JP[now.weekday()]
    if _CURRENT_SLOT == "12":
        slot_label = " 🌞 お昼チェック"
    elif _CURRENT_SLOT == "18":
        slot_label = " 🌆 帰り道チェック"
    else:
        slot_label = ""
    return f"📅 {now.month}/{now.day}({day_jp}){slot_label}\n\n"


def tweet_marathon_kickoff() -> str:
    """マラソン開始（ポイントアップ開始）直後のヨーイドン宣言ツイート。"""
    return (
        f"{daily_lead_in()}"
        "🏁 位置について、ヨーイ…\n"
        "\n"
        "🏃‍♂️ お買い物マラソン スタート！\n"
        "ポイント買いまわり、開幕💨\n"
        "\n"
        "✅ エントリー\n"
        "✅ クーポン取得\n"
        "✅ SPU確認\n"
        "\n"
        "今すぐ👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'marathon', 'poikatsu'], max_tags=3)}"
    )


def tweet_marathon_big_chance(special_days: list, season_event: str = None) -> str:
    events = season_event if season_event else "・".join(special_days)
    return (
        f"{daily_lead_in()}"
        f"🔥 ビッグチャンス！\n"
        f"マラソン × {events} 重なり✨\n"
        "\n"
        "ポイント大増量のチャンス💡\n"
        "楽券・Appleギフトで買い周りOK！\n"
        "\n"
        "エントリーまとめ👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'marathon', 'poikatsu'], max_tags=3)}"
    )


def tweet_marathon_entry_only() -> str:
    """エントリー期間中だがポイントアップ期間まだ開始していない場合。

    ※ X の重複投稿検出（30日サイクル）対策が事故源。エントリー期間中は
       同じテンプレが 2スロット×7日=14回連投されるため、毎マラソン同じ文面だと
       速攻 403 になる。本文を4バリアント × daily_lead_in（日替わり）で
       強くシャッフルして対策する。
       過去事故: 2026-05-21,22 連続で 403 Forbidden を喰らった。
    """
    # 開始日ラベル（schedule取れる場合のみ）
    sched = load_marathon_schedule()
    p_start_str = sched.get("pointup_start") if isinstance(sched, dict) else None
    start_label = ""
    if p_start_str:
        try:
            start_dt = datetime.datetime.fromisoformat(p_start_str).astimezone(JST)
            now_jst = datetime.datetime.now(JST)
            delta_days = (start_dt.date() - now_jst.date()).days
            day_jp = "日月火水木金土"[start_dt.weekday()]
            if delta_days == 0:
                start_label = f"⏰ 今夜 {start_dt.hour}時 から！\n"
            elif delta_days == 1:
                start_label = f"⏰ 明日 {start_dt.month}/{start_dt.day}({day_jp}) {start_dt.hour}時 開始！\n"
            elif 0 < delta_days <= 7:
                start_label = f"⏰ あと{delta_days}日 ({start_dt.month}/{start_dt.day}({day_jp}) {start_dt.hour}時 開始)\n"
        except Exception:
            pass

    # 本文を 4 バリアント × 日替わりで切り替え（14日 entry期間でも全部別文章になる）
    now = datetime.datetime.now(JST)
    variant = now.timetuple().tm_yday % 4
    if variant == 0:
        body = (
            "🏃 お買い物マラソン、エントリー受付中！\n"
            "\n"
            f"{start_label}"
            "⚠️ 今はまだ「エントリー期間」\n"
            "ポイントアップはまだだが、\n"
            "エントリー忘れると対象外💧\n"
            "\n"
            "✅今のうちにエントリー済ませよう！\n"
            "\n"
            "まとめて👇\n"
            f"{SITE_URL}"
        )
    elif variant == 1:
        body = (
            "📋 マラソン エントリー、できてる？\n"
            "\n"
            f"{start_label}"
            "💡 早めにポチっておくのが正解。\n"
            "ポイントアップ開始前にエントリーしないと、\n"
            "せっかくの買い物が対象外になっちゃう。\n"
            "\n"
            "👇 ボタン一発でまとめてエントリー\n"
            f"{SITE_URL}"
        )
    elif variant == 2:
        body = (
            "✋ マラソン前のチェックリスト\n"
            "\n"
            f"{start_label}"
            "□ お買い物マラソン エントリー\n"
            "□ 楽天カード SPU エントリー\n"
            "□ 0と5の日キャンペーン エントリー\n"
            "\n"
            "全部、開始前に押しておこう👇\n"
            f"{SITE_URL}"
        )
    else:
        body = (
            "🛒 マラソン スタート前にやることは1つだけ\n"
            "\n"
            f"{start_label}"
            "👉 エントリー\n"
            "\n"
            "エントリーしてないと、買っても\n"
            "ポイントアップの対象にならないからね💧\n"
            "\n"
            "👇 今のうちにまとめて\n"
            f"{SITE_URL}"
        )
    return (
        f"{daily_lead_in()}"
        f"{body}\n"
        f" {hashtags(['core', 'marathon', 'entry'], max_tags=3)}"
    )


def tweet_marathon_normal() -> str:
    """マラソンポイントアップ期間中の通常ツイート。2スロット×7日=14回連投なので
    本文を3バリアント×日替わりで強くシャッフル（X 重複検出 403 対策）。"""
    now = datetime.datetime.now(JST)
    variant = now.timetuple().tm_yday % 3
    if variant == 0:
        body = (
            "🏃 お買い物マラソン開催中！\n"
            "\n"
            "買いたいものがなくても買いまわりOK✨\n"
            "📦 楽券(eギフト)→コンビニ・コメダ等\n"
            "🍎 Appleギフトカードも対象\n"
            "\n"
            "👇 今楽でまとめてエントリー\n"
            f"{SITE_URL}"
        )
    elif variant == 1:
        body = (
            "🛒 マラソン中の買い回りテク\n"
            "\n"
            "・1ショップ1,000円以上ずつ\n"
            "・できれば10ショップで＋9倍\n"
            "・楽券/Appleギフトで嵩増しOK\n"
            "\n"
            "エントリー忘れだけ気をつけて👇\n"
            f"{SITE_URL}"
        )
    else:
        body = (
            "💰 マラソン期間中だけのお得テク\n"
            "\n"
            "ふだん買う日用品も、\n"
            "今買えばポイントが数倍に。\n"
            "\n"
            "「いつもの買い物を今日に寄せる」\n"
            "これだけで年間ポイント変わる🪙\n"
            "\n"
            f"{SITE_URL}"
        )
    return (
        f"{daily_lead_in()}"
        f"{body}\n"
        f" {hashtags(['core', 'marathon', 'poikatsu'], max_tags=3)}"
    )


def tweet_supersale_big_chance(special_days: list, season_event: str = None) -> str:
    """スーパーSALE × 特別日（0と5/1日/18日）= 最強クラスの買い時。"""
    events = season_event if season_event else "・".join(special_days)
    return (
        f"{daily_lead_in()}"
        "🔥 今日は最強クラスの買い時！\n"
        f"楽天スーパーSALE × {events}✨\n"
        "\n"
        "🛒 買い回り最大10倍\n"
        "半額・数量限定も多数💡\n"
        "\n"
        "エントリーまとめ👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'supersale', 'poikatsu'], max_tags=3)}"
    )


def tweet_supersale() -> str:
    """スーパーSALE開催中（特別日でない通常のSALE日）。"""
    return (
        f"{daily_lead_in()}"
        "🛒 楽天スーパーSALE開催中！\n"
        "\n"
        "買い回り最大10倍✨\n"
        "半額・数量限定も狙い目💡\n"
        "エントリーは早いほどお得！\n"
        "\n"
        "まとめてチェック👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'supersale', 'poikatsu'], max_tags=3)}"
    )


def tweet_wonderful_day() -> str:
    return (
        f"{daily_lead_in()}"
        "🎉 今日はワンダフルデー！（毎月1日）\n"
        "\n"
        "楽天カード利用でポイントUP✨\n"
        "エントリーするだけ！今月もお得に🛒\n"
        "\n"
        "まとめて👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'wonderful', 'poikatsu'], max_tags=3)}"
    )


def tweet_ichiba_day() -> str:
    return (
        f"{daily_lead_in()}"
        "🏪 今日は楽天市場の日！（毎月18日）\n"
        "エントリーするだけでOK！\n"
        "\n"
        "楽天カードで+1%ポイントUP✨\n"
        "\n"
        "まとめて👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'ichibaday', 'poikatsu'], max_tags=3)}"
    )


def tweet_new_year() -> str:
    return (
        "🎍 あけましておめでとうございます！\n"
        "\n"
        "今年も楽天でポイントを賢く貯めよう💡\n"
        "新年のお買い物は必ずエントリーから✅\n"
        "\n"
        "今日のエントリー👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'newyear', 'poikatsu'], max_tags=3)}"
    )


def tweet_valentine() -> str:
    return (
        "🍫 今日はバレンタイン！\n"
        "\n"
        "楽天市場でチョコを買うなら\n"
        "エントリーしてからがお得💡\n"
        "ポイントも貯まる✨\n"
        "\n"
        "まとめて👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'valentine', 'poikatsu'], max_tags=3)}"
    )


def tweet_white_day() -> str:
    return (
        "🍬 今日はホワイトデー！\n"
        "\n"
        "楽天市場でお返しギフトを探そう🎁\n"
        "エントリーしてから買えば\n"
        "ポイントもしっかり✨\n"
        "\n"
        "まとめて👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'whiteday', 'poikatsu'], max_tags=3)}"
    )


def get_mothers_day(year: int) -> datetime.date:
    """5月の第2日曜日（母の日）を返す"""
    first = datetime.date(year, 5, 1)
    offset = (6 - first.weekday()) % 7
    return first + datetime.timedelta(days=offset + 7)


def get_fathers_day(year: int) -> datetime.date:
    """6月の第3日曜日（父の日）を返す"""
    first = datetime.date(year, 6, 1)
    offset = (6 - first.weekday()) % 7
    return first + datetime.timedelta(days=offset + 14)


def tweet_mothers_day_countdown(days_until: int) -> str:
    """母の日まで何日かを伝える + 早めの準備を促す"""
    if days_until == 0:
        return tweet_mothers_day()
    when = "明日" if days_until == 1 else f"{days_until}日後"
    return (
        f"🌸 母の日は {when} （5月第2日曜）\n"
        "\n"
        "「気付いたら過ぎてた…」を防ぐ告知✋\n"
        "お花は早めに注文すると確実に届くよ！\n"
        "\n"
        "🎁 ギフト・お花・スイーツ etc.\n"
        "楽天で買うならエントリー忘れずに👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'mothers', 'poikatsu'], max_tags=3)}"
    )


def tweet_fathers_day_countdown(days_until: int) -> str:
    """父の日まで何日かを伝える"""
    if days_until == 0:
        return tweet_fathers_day()
    when = "明日" if days_until == 1 else f"{days_until}日後"
    return (
        f"👔 父の日は {when} （6月第3日曜）\n"
        "\n"
        "「気付いたら過ぎてた…」を防ぐ告知✋\n"
        "ビール・お酒・グルメは早めの準備が吉🍺\n"
        "\n"
        "🎁 楽天で買うならエントリーから👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'fathers', 'poikatsu'], max_tags=3)}"
    )


def tweet_mothers_day() -> str:
    return (
        "🌸 今日は母の日！\n"
        "\n"
        "楽天市場で感謝の気持ちをプレゼント🎁\n"
        "エントリーしてから買えば\n"
        "ポイントもたっぷり✨\n"
        "\n"
        "まとめて👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'mothers', 'poikatsu'], max_tags=3)}"
    )


def tweet_fathers_day() -> str:
    return (
        "👔 今日は父の日！\n"
        "\n"
        "楽天市場で日頃の感謝をプレゼント🎁\n"
        "エントリーしてから買えば\n"
        "ポイントもたっぷり✨\n"
        "\n"
        "まとめて👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'fathers', 'poikatsu'], max_tags=3)}"
    )


def tweet_christmas_eve() -> str:
    return (
        "🎄 今日はクリスマスイブ！\n"
        "\n"
        "楽天市場でクリスマスギフトを探すなら\n"
        "エントリーしてからがお得💡\n"
        "ポイント貯めてプレゼント🎁\n"
        "\n"
        "まとめて👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'christmas', 'poikatsu'], max_tags=3)}"
    )


def tweet_christmas() -> str:
    return (
        "🎅 メリークリスマス！\n"
        "\n"
        "楽天市場のお買い物は\n"
        "エントリーしてからがお得✨\n"
        "今日も忘れずに！\n"
        "\n"
        "まとめて👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'christmas', 'poikatsu'], max_tags=3)}"
    )


def tweet_zero_five_day() -> str:
    return (
        f"{daily_lead_in()}"
        "📅 今日は0と5のつく日！\n"
        "楽天カードで【ふるさと納税】+1倍💳\n"
        "\n"
        "💡 物価高の今こそ早めのふるさと納税が◎\n"
        "・年末より品数が豊富\n"
        "・人気返礼品の売り切れ回避🎯\n"
        "\n"
        "👇 まずはエントリー忘れずに\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'zerogo', 'furusato'], max_tags=3)}"
    )


def tweet_month_end_eve() -> str:
    """月末前日：期間限定ポイント失効注意（警告＋残高確認URL＋使い道提案）。
    失効注意は純粋な親切ツイートなので CTA は点残高チェックURLに一本化し、
    今楽URLは載せない（X 文字数 280 と 6/1 までの URL 抑制方針の両方に整合）。"""
    return (
        f"{daily_lead_in()}"
        "⏰月末まで残り1日！\n"
        "期間限定ポイント、失効してない？💸\n"
        "\n"
        "🔍まず確認はココ👇\n"
        f"{POINT_CHECK_URL}\n"
        "\n"
        "✅使い切り術\n"
        "・Appleギフト/楽券に交換\n"
        "・楽天ペイや日用品で消化\n"
        f" {hashtags(['core', 'pointexpire', 'poikatsu'], max_tags=3)}"
    )


def tweet_month_end_last() -> str:
    """月末当日：期間限定ポイント失効目前（緊急告知）"""
    return (
        f"{daily_lead_in()}"
        "🚨本日23:59まで！\n"
        "期間限定ポイント、失効目前💧\n"
        "\n"
        "🔍まず保有残高を確認👇\n"
        f"{POINT_CHECK_URL}\n"
        "\n"
        "✅使い切るワザ\n"
        "・Appleギフト/楽券に交換\n"
        "・ふるさと納税でお得に変換\n"
        f" {hashtags(['core', 'pointexpire', 'furusato'], max_tags=3)}"
    )


def tweet_triple_combo(special_days: list, season_event: str = None) -> str:
    """マラソン × W勝利 × 特別日/季節イベント → トリプル役満（年に数回の激レア）"""
    events = season_event if season_event else "・".join(special_days)
    return (
        f"{daily_lead_in()}"
        "🔥🔥🔥 役満デー！\n"
        f"マラソン × W勝利(⚾×⚽) × {events}\n"
        "奇跡の3重なり✨\n"
        "\n"
        "ポイント倍率が今月最大級📈\n"
        "エントリー忘れ絶対NG💰\n"
        "楽券・Appleギフトで買い周りOK！\n"
        "\n"
        "まとめ👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'marathon', 'eagles'], max_tags=3)}"
    )


def tweet_triple_combo_adidas(special_days: list, season_event: str = None) -> str:
    """マラソン × 特別日 × adidasセール開催中 → トリプル役満（adidas版）。
    ポイント倍率 + adidasセール割引のダブル効果を訴求。
    """
    events = season_event if season_event else "・".join(special_days)
    return (
        f"{daily_lead_in()}"
        "🔥🔥 トリプル役満！\n"
        f"マラソン × {events} × adidas\n"
        "\n"
        "ポイント倍率×セール割引のW効果🎯\n"
        "50/40/30/20%off ラインナップ\n"
        "人気モデルは早い者勝ち！\n"
        "\n"
        f"👇 今楽でまとめてエントリー\n{SITE_URL}\n"
        f" {hashtags(['core', 'marathon', 'adidas'], max_tags=3)}"
    )


def tweet_triple_combo_nike(special_days: list, season_event: str = None) -> str:
    """マラソン × 特別日 × NIKEセール開催中 → トリプル役満（NIKE版）。
    ポイント倍率 + NIKE最大60%OFFのダブル効果を訴求。
    """
    events = season_event if season_event else "・".join(special_days)
    return (
        f"{daily_lead_in()}"
        "🔥🔥 トリプル役満！\n"
        f"マラソン × {events} × NIKE\n"
        "\n"
        "ポイント倍率×最大60%OFFのW効果🎯\n"
        "人気モデルは早い者勝ち！\n"
        "\n"
        f"👇 今楽でまとめてエントリー\n{SITE_URL}\n"
        f" {hashtags(['core', 'marathon', 'nike'], max_tags=3)}"
    )


def tweet_marathon_x_victory(w_victory: bool, team: str = "") -> str:
    """マラソン × 勝利（W勝利 or 片チーム）"""
    if w_victory:
        head = "🔥 ビッグチャンス！\nマラソン × W勝利(⚾×⚽) ポイント大増量！"
    else:
        head = f"🔥 ビッグチャンス！\nマラソン × {team}勝利でポイント増量！"
    tag_team = 'eagles' if ('イーグルス' in team or w_victory) else 'vissel'
    return (
        f"{daily_lead_in()}"
        f"{head}\n"
        "\n"
        "勝ったら倍エントリー忘れずに、\n"
        "買いまわりで上乗せ💰\n"
        "楽券・Appleギフトで買い周りOK！\n"
        "\n"
        "まとめ👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'marathon', tag_team], max_tags=3)}"
    )


def tweet_w_victory_x_special(special_days: list, season_event: str = None) -> str:
    """W勝利 × 特別日/季節イベント → レアな組み合わせ"""
    events = season_event if season_event else "・".join(special_days)
    return (
        f"{daily_lead_in()}"
        f"🎉 レアなチャンス！\n"
        f"W勝利(⚾×⚽) × {events} 重なり✨\n"
        "\n"
        "ポイント3倍 + 特別日ボーナス💰\n"
        "「勝ったら倍」エントリー忘れずに\n"
        "\n"
        "👇 今楽でまとめてエントリー\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'eagles', 'vissel'], max_tags=3)}"
    )


def tweet_single_victory_x_special(team: str, special_days: list, season_event: str = None) -> str:
    """片チーム勝利 × 特別日/季節イベント"""
    events = season_event if season_event else "・".join(special_days)
    cat = 'eagles' if 'イーグルス' in team else 'vissel'
    return (
        f"{daily_lead_in()}"
        f"✨ お得デー！\n"
        f"{team}勝利 × {events} 合わせ技！\n"
        "\n"
        "ポイント2倍 + 特別日ボーナス💰\n"
        "「勝ったら倍」エントリー忘れずに\n"
        "\n"
        "👇 今楽でまとめてエントリー\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', cat, 'poikatsu'], max_tags=3)}"
    )


def tweet_w_victory() -> str:
    """イーグルス＆ヴィッセル神戸W勝利 → ポイント3倍"""
    return (
        f"{daily_lead_in()}"
        "🎉🎉 W勝利でポイント3倍！！\n"
        "楽天イーグルス⚾×ヴィッセル神戸⚽ 勝利✨\n"
        "\n"
        "「勝ったら倍」が3倍になる超お得日🔥\n"
        "エントリーしてから買い物しよう💰\n"
        "\n"
        "👇 今楽でまとめてエントリー\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'eagles', 'vissel'], max_tags=3)}"
    )


def tweet_eagles() -> str:
    """イーグルスのみ勝利 → ポイント2倍"""
    return (
        f"{daily_lead_in()}"
        "⚾ 楽天イーグルス勝利！\n"
        "「勝ったら倍」でポイント2倍🎉\n"
        "\n"
        "エントリーしてから買うだけでOK✅\n"
        "\n"
        "👇 今楽でまとめてエントリー\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'eagles', 'poikatsu'], max_tags=3)}"
    )


def tweet_vissel() -> str:
    """ヴィッセル神戸のみ勝利 → ポイント2倍"""
    return (
        f"{daily_lead_in()}"
        "⚽ ヴィッセル神戸勝利！\n"
        "「勝ったら倍」でポイント2倍🎉\n"
        "\n"
        "エントリーしてから買うだけでOK✅\n"
        "\n"
        "👇 今楽でまとめてエントリー\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'vissel', 'poikatsu'], max_tags=3)}"
    )


def tweet_adidas() -> str:
    return (
        f"{daily_lead_in()}"
        "👟 adidas セール開催中！\n"
        "\n"
        "50%off / 40%off / 30%off / 20%off の\n"
        "ラインナップが充実✨\n"
        "\n"
        "マラソンと組み合わせでお得🔥\n"
        f"👇 今楽でまとめてチェック\n{SITE_URL}\n"
        f" {hashtags(['core', 'adidas', 'poikatsu'], max_tags=3)}"
    )


def tweet_nike() -> str:
    return (
        f"{daily_lead_in()}"
        "👟 NIKE 最大60%OFF開催中！\n"
        "\n"
        "マラソンと組み合わせでお得🔥\n"
        "対象商品多数、好きな1足をチェック\n"
        "\n"
        "👇 今楽でまとめてエントリー\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'nike', 'poikatsu'], max_tags=3)}"
    )


def tweet_normal() -> str:
    """通常日ツイート。3 バリアントを day_of_year で回し、訴求軸を変える。
    A: 時短アングル（考えずにエントリー）
    B: 金銭アングル（ポイント還元を最大化）
    C: 発見アングル（今日限定の見逃しキャンペーン）
    """
    now = datetime.datetime.now(JST)
    variant = now.timetuple().tm_yday % 3
    if variant == 0:
        body = (
            "🛒 楽天で買う前のルーティン化、できてる？\n"
            "\n"
            "① 今楽を開く\n"
            "② エントリー一括\n"
            "③ そのまま買い物\n"
            "\n"
            "考えないでOK、3秒で完了👇\n"
            f"{SITE_URL}"
        )
        tag_cats = ['core', 'poikatsu', 'saving']
    elif variant == 1:
        body = (
            "💰 同じ商品でも、エントリー有無で\n"
            "ポイント還元は数%変わる。\n"
            "\n"
            "塵も積もれば年間数千〜数万ポイント🪙\n"
            "「エントリーした人だけがお得」設計✨\n"
            "\n"
            "今日のキャンペーン一覧👇\n"
            f"{SITE_URL}"
        )
        tag_cats = ['core', 'poikatsu', 'saving']
    else:
        body = (
            "👀 今日も見逃してるキャンペーン無い？\n"
            "\n"
            "・SPU 強化\n"
            "・限定クーポン\n"
            "・条件達成ボーナス\n"
            "\n"
            "全部まとめて1ページに集約👇\n"
            f"{SITE_URL}"
        )
        tag_cats = ['core', 'poikatsu', 'coupon']
    return (
        f"{daily_lead_in()}"
        f"{body}\n"
        f" {hashtags(tag_cats, max_tags=3)}"
    )


# ── メイン ────────────────────────────────────────────────────────────────

def main():
    now     = datetime.datetime.now(JST)
    weekday = now.weekday()   # 0=月 … 5=土 6=日
    print(f"=== 日次ツイート {now.strftime('%Y-%m-%d %H:%M JST')} ===")

    # 🛡️ スロット重複排除: 冗長cronで取りこぼし救済しつつ、二重投稿を物理的に防ぐ
    today = now.strftime("%Y-%m-%d")
    status           = load_status()
    # 最強の日(大型セール×0と5)はスロットを増やして露出を上げる（peak-day boost）
    peak = is_peak_day(now, status)
    slot = current_slot(now, peak)
    if slot is None:
        print(f"  → 投稿対象スロット外（{now.strftime('%H:%M')} JST, peak={peak}）→ スキップ")
        return
    if is_slot_posted(slot, today):
        print(f"  → 本日のスロット {slot}時 は既に投稿済 → スキップ")
        return
    print(f"  → 対象スロット: {slot}時（peak={peak}）")

    # テンプレに「日替わり文脈行」を渡すためスロット情報をモジュールスコープに公開
    global _CURRENT_SLOT
    _CURRENT_SLOT = slot

    marathon         = status.get("marathon",         False)
    marathon_pointup = status.get("marathon_pointup", False)
    eagles           = status.get("eagles",           False)
    vissel           = status.get("vissel",           False)
    adidas_on        = status.get("adidas",           False)
    nike_on          = status.get("nike",             False)
    supersale        = status.get("supersale",        False)
    special_days     = get_special_days(now)
    season_event     = get_season_event(now)
    month_end_phase  = get_month_end_phase(now)

    print(f"  marathon={marathon}, marathon_pointup={marathon_pointup}, eagles={eagles}, vissel={vissel}")
    print(f"  adidas={adidas_on}, nike={nike_on}, supersale={supersale}, special={special_days}, season={season_event}, weekday={weekday}, month_end={month_end_phase}")

    SEASON_TWEET_MAP = {
        "年始":         tweet_new_year,
        "バレンタイン": tweet_valentine,
        "ホワイトデー": tweet_white_day,
        "母の日":       tweet_mothers_day,
        "父の日":       tweet_fathers_day,
        "クリスマスイブ": tweet_christmas_eve,
        "クリスマス":   tweet_christmas,
    }

    has_special = bool(special_days) or bool(season_event)
    w_victory   = eagles and vissel
    any_victory = eagles or vissel
    victor_team = "楽天イーグルス" if eagles else ("ヴィッセル神戸" if vissel else "")

    # kickoff は schedule.pointup_start から直接判定（marathon_pointup は
    # check-campaigns の 2h cron 更新ラグで信頼できないため除外）
    kickoff = is_marathon_kickoff(now)
    print(f"  kickoff_window={kickoff}")

    # ── 優先度順に判定 ──────────────────────────────────────────────────────
    # ★★ 超最高優先: マラソン開始直後のヨーイドン枠（90分間限定・1回だけ発火）
    if kickoff:
        tweet = tweet_marathon_kickoff()
        label = "マラソン開始ヨーイドン（kickoff window）"
        # 同じ pointup_start での再発火を防ぐため履歴を記録
        sched = load_marathon_schedule()
        if sched.get("pointup_start"):
            mark_kickoff_fired(sched["pointup_start"])

    # ★ 最高優先: マラソン × W勝利 × 特別日 (年に数回の激レア役満)
    elif marathon and marathon_pointup and w_victory and has_special:
        tweet = tweet_triple_combo(special_days, season_event)
        label = f"トリプル役満（マラソン×W勝利×{'・'.join(special_days) if special_days else season_event}）"

    elif marathon and marathon_pointup and w_victory:
        tweet = tweet_marathon_x_victory(w_victory=True)
        label = "マラソン×W勝利"

    elif marathon and marathon_pointup and any_victory:
        tweet = tweet_marathon_x_victory(w_victory=False, team=victor_team)
        label = f"マラソン×{victor_team}勝利"

    elif marathon and marathon_pointup and has_special and adidas_on:
        # ポイントアップ期間中 × 特別日 × adidasセール → トリプル役満（adidas版）
        tweet = tweet_triple_combo_adidas(special_days, season_event)
        label = f"トリプル役満adidas（マラソン×{'・'.join(special_days) if special_days else season_event}×adidas）"

    elif marathon and marathon_pointup and has_special and nike_on:
        # ポイントアップ期間中 × 特別日 × NIKEセール → トリプル役満（NIKE版）
        tweet = tweet_triple_combo_nike(special_days, season_event)
        label = f"トリプル役満NIKE（マラソン×{'・'.join(special_days) if special_days else season_event}×NIKE）"

    elif marathon and marathon_pointup and has_special:
        # ポイントアップ期間中 × 特別日/季節イベント → ビッグチャンス
        tweet = tweet_marathon_big_chance(special_days, season_event)
        label = f"マラソン×{'・'.join(special_days) if special_days else season_event}（ビッグチャンス）"

    elif marathon and marathon_pointup:
        # ポイントアップ期間中 → 今すぐ買いまわりを促す
        tweet = tweet_marathon_normal()
        label = "マラソン（ポイントアップ期間中）"

    elif marathon and not marathon_pointup:
        # エントリー期間のみ → まずエントリーを促す（まだ買わなくてOK）
        tweet = tweet_marathon_entry_only()
        label = "マラソン（エントリー期間のみ・ポイントアップ未開始）"

    # ★ 楽天スーパーSALE（マラソンと並ぶ大型買い回りイベント。開催中はヘッドライン優先）
    elif supersale and has_special:
        # スーパーSALE × 特別日(0と5/1日/18日) = 最強クラスの日 → ビッグチャンス
        tweet = tweet_supersale_big_chance(special_days, season_event)
        label = f"スーパーSALE×{'・'.join(special_days) if special_days else season_event}（最強の日）"

    elif supersale:
        tweet = tweet_supersale()
        label = "スーパーSALE開催中"

    # ★ 母の日カウントダウン（D-14, D-7, D-3, D-1 の特定日のみ発火）
    elif (lambda d: d > 0 and d in (14, 7, 3, 1))(
        (get_mothers_day(now.year) - now.date()).days
    ):
        days_left = (get_mothers_day(now.year) - now.date()).days
        tweet = tweet_mothers_day_countdown(days_left)
        label = f"母の日カウントダウン（D-{days_left}）"

    # ★ 父の日カウントダウン（同上）
    elif (lambda d: d > 0 and d in (14, 7, 3, 1))(
        (get_fathers_day(now.year) - now.date()).days
    ):
        days_left = (get_fathers_day(now.year) - now.date()).days
        tweet = tweet_fathers_day_countdown(days_left)
        label = f"父の日カウントダウン（D-{days_left}）"

    # ★ 月末2日（マラソン無し時）→ 期間限定ポイント失効注意
    elif month_end_phase == "eve":
        tweet = tweet_month_end_eve()
        label = "月末前日（期間限定ポイント失効注意）"

    elif month_end_phase == "last":
        tweet = tweet_month_end_last()
        label = "月末最終日（期間限定ポイント失効目前）"

    # ★ W勝利 × 特別日/季節イベント（マラソン無し）→ レアチャンス
    elif w_victory and has_special:
        tweet = tweet_w_victory_x_special(special_days, season_event)
        label = f"W勝利×{'・'.join(special_days) if special_days else season_event}"

    elif any_victory and has_special:
        tweet = tweet_single_victory_x_special(victor_team, special_days, season_event)
        label = f"{victor_team}勝利×{'・'.join(special_days) if special_days else season_event}"

    elif season_event:           # 季節イベント（母の日・父の日・クリスマス等）
        tweet = SEASON_TWEET_MAP[season_event]()
        label = f"季節イベント（{season_event}）"

    elif now.day == 1:           # ワンダフルデー（毎月1日）
        tweet = tweet_wonderful_day()
        label = "ワンダフルデー（1日）"

    elif now.day == 18:          # 楽天市場の日（毎月18日）
        tweet = tweet_ichiba_day()
        label = "楽天市場の日（18日）"

    elif now.day % 5 == 0:       # 0と5のつく日
        tweet = tweet_zero_five_day()
        label = "0と5のつく日"

    elif w_victory:              # W勝利 → 3倍
        tweet = tweet_w_victory()
        label = "W勝利（イーグルス＆ヴィッセル）ポイント3倍"

    elif eagles:                 # イーグルスのみ勝利 → 2倍
        tweet = tweet_eagles()
        label = "イーグルス勝利 ポイント2倍"

    elif vissel:                 # ヴィッセルのみ勝利 → 2倍
        tweet = tweet_vissel()
        label = "ヴィッセル神戸勝利 ポイント2倍"

    elif weekday == 5 and adidas_on:   # 土曜 かつ adidas開催中のみ
        tweet = tweet_adidas()
        label = "adidas特集（土曜）"

    elif weekday == 6 and nike_on:     # 日曜 かつ NIKE開催中のみ
        tweet = tweet_nike()
        label = "NIKE特集（日曜）"

    else:
        tweet = tweet_normal()
        label = "通常日"

    print(f"  種別: {label}")

    # スロット別の挨拶を冒頭に付与（X 重複検出回避）
    # kickoff のみ既に独自フォーマットで「位置について…」と始まるため除外
    if not label.startswith("マラソン開始ヨーイドン"):
        tweet = with_slot_intro(tweet, slot, now)

    print(f"\n投稿内容:\n{tweet}\n")
    if post_tweet(tweet):
        mark_slot_posted(slot, today)
    else:
        # サイレントフェイル防止: post_tweet 失敗時は workflow を failure にして
        # GitHub から失敗通知メールが届くようにする
        print("❌ post_tweet が False を返したため exit 1（GitHub Actions failure 通知用）", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
