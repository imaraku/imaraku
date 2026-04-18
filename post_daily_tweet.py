#!/usr/bin/env python3
"""
post_daily_tweet.py
毎朝 9:00 JST（= 0:00 UTC）に実行。
今日のキャンペーン状況・曜日・日付に応じたツイートを投稿する。

【優先度順】
  1. マラソン × 特別日（0と5のつく日 or ワンダフルデー）→ ビッグチャンス
  2. マラソン開催中                                      → eギフト活用ヒント
  3. 月末2日（前日・最終日）※マラソン無し時              → 期間限定ポイント失効注意
  4. ワンダフルデー（18日）                              → ワンダフルデー告知
  5. 0と5のつく日（5/10/15/20/25/30日）                  → 0と5のつく日告知
  6. 楽天イーグルス勝利ボーナス開催中                    → 勝利ボーナス告知
  7. 土曜日                                              → adidas 特集
  8. 日曜日                                              → NIKE 特集
  9. 通常日                                              → 39ショップ・リピート・ゲリラ告知
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

CAMPAIGN_STATUS_FILE = "campaign_status.json"

# ── URL 定義 ────────────────────────────────────────────────────────────
SITE_URL    = "https://imaraku.github.io/imaraku/imaraku.html"
SPORTS_URL    = "https://event.rakuten.co.jp/campaign/sports/?l-id=top_normal_flashbnr_10_EECDCECB_160268_0&scid=af_pc_etc&sc2id=af_101_0_0"
RAKKEN_URL    = "https://event.rakuten.co.jp/rakken/?scid=af_pc_etc&sc2id=af_101_0_0"
APPLE_URL     = "https://event.rakuten.co.jp/computer/itunes/?scid=af_pc_etc&sc2id=af_101_0_0"
POINTDAY_URL  = "https://event.rakuten.co.jp/card/pointday/?scid=af_pc_etc&sc2id=af_101_0_0"

# adidas（アフィリエイト込み短縮URL）
ADIDAS_50   = "https://a.r10.to/h5AdfJ"
ADIDAS_40   = "https://a.r10.to/h5s1YF"
ADIDAS_30   = "https://a.r10.to/hYB6gY"
ADIDAS_20   = "https://a.r10.to/h5WwCG"

# NIKE（アフィリエイト込み）
NIKE_URL    = "https://item.rakuten.co.jp/nike-official/cj9583-100/?scid=af_pc_etc&sc2id=af_101_0_0"

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


# ── ツイート文 生成 ────────────────────────────────────────────────────────

def tweet_marathon_big_chance(special_days: list, season_event: str = None) -> str:
    events = season_event if season_event else "・".join(special_days)
    return (
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
    """エントリー期間中だがポイントアップ期間まだ開始していない場合"""
    return (
        "🏃 お買物マラソン、エントリー受付中！\n"
        "\n"
        "⚠️ 今はまだ「エントリー期間」\n"
        "ポイントアップはまだだが、\n"
        "エントリー忘れると対象外💧\n"
        "\n"
        "✅今のうちにエントリー済ませよう！\n"
        "\n"
        "まとめて👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'marathon', 'entry'], max_tags=3)}"
    )


def tweet_marathon_normal() -> str:
    return (
        "🏃 お買物マラソン開催中！\n"
        "\n"
        "買いたいものがない方も\n"
        "📦 楽券(eギフト)→コンビニ・コメダ等OK\n"
        f"{RAKKEN_URL}\n"
        "🍎 Appleギフトカードも対象\n"
        f"{APPLE_URL}\n"
        "\n"
        "エントリーまとめ👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'marathon', 'poikatsu'], max_tags=3)}"
    )


def tweet_wonderful_day() -> str:
    return (
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
        "📅 今日は0と5のつく日！\n"
        "楽天カードで【ふるさと納税】+1倍💳\n"
        "\n"
        "💡 物価高の今こそ早めのふるさと納税が◎\n"
        "・年末より品数が豊富\n"
        "・人気返礼品の売り切れ回避🎯\n"
        "\n"
        "ふるさと納税👇\n"
        f"{POINTDAY_URL}\n"
        "\n"
        "エントリー👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'zerogo', 'furusato'], max_tags=3)}"
    )


def tweet_month_end_eve() -> str:
    """月末前日：期間限定ポイント失効注意（警告＋使い道提案）"""
    return (
        "⏰月末まで残り1日\n"
        "期間限定ポイント、大丈夫？\n"
        "\n"
        "初心者が一番やらかすミスは月末失効💸\n"
        "\n"
        "✅使い切り術\n"
        "・Appleギフト・楽券を購入\n"
        f"{APPLE_URL}\n"
        "・日用品購入や楽天ペイで消化\n"
        "\n"
        "👉楽天PointClubで期限確認\n"
        "https://point.rakuten.co.jp/\n"
        f" {hashtags(['core', 'pointexpire', 'poikatsu'], max_tags=3)}"
    )


def tweet_month_end_last() -> str:
    """月末当日：期間限定ポイント失効目前（緊急告知）"""
    return (
        "🚨本日23:59期限！\n"
        "期間限定ポイント、失効目前💧\n"
        "\n"
        "使い切るワザ👇\n"
        "・Appleギフト・楽券を購入\n"
        f"{APPLE_URL}\n"
        "・楽天ふるさと納税でお得に変換\n"
        f"{POINTDAY_URL}\n"
        "\n"
        "楽天PointClubで保有ポイント確認！\n"
        f" {hashtags(['core', 'pointexpire', 'furusato'], max_tags=3)}"
    )


def tweet_triple_combo(special_days: list, season_event: str = None) -> str:
    """マラソン × W勝利 × 特別日/季節イベント → トリプル役満（年に数回の激レア）"""
    events = season_event if season_event else "・".join(special_days)
    return (
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


def tweet_marathon_x_victory(w_victory: bool, team: str = "") -> str:
    """マラソン × 勝利（W勝利 or 片チーム）"""
    if w_victory:
        head = "🔥 ビッグチャンス！\nマラソン × W勝利(⚾×⚽) ポイント大増量！"
    else:
        head = f"🔥 ビッグチャンス！\nマラソン × {team}勝利でポイント増量！"
    tag_team = 'eagles' if ('イーグルス' in team or w_victory) else 'vissel'
    return (
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
        f"🎉 レアなチャンス！\n"
        f"W勝利(⚾×⚽) × {events} 重なり✨\n"
        "\n"
        "ポイント3倍 + 特別日ボーナス💰\n"
        "\n"
        "「勝ったら倍」エントリー👇\n"
        f"{SPORTS_URL}\n"
        "\n"
        "まとめ👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'eagles', 'vissel'], max_tags=3)}"
    )


def tweet_single_victory_x_special(team: str, special_days: list, season_event: str = None) -> str:
    """片チーム勝利 × 特別日/季節イベント"""
    events = season_event if season_event else "・".join(special_days)
    cat = 'eagles' if 'イーグルス' in team else 'vissel'
    return (
        f"✨ お得デー！\n"
        f"{team}勝利 × {events} 合わせ技！\n"
        "\n"
        "ポイント2倍 + 特別日ボーナス💰\n"
        "\n"
        "「勝ったら倍」エントリー👇\n"
        f"{SPORTS_URL}\n"
        "\n"
        "まとめ👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', cat, 'poikatsu'], max_tags=3)}"
    )


def tweet_w_victory() -> str:
    """イーグルス＆ヴィッセル神戸W勝利 → ポイント3倍"""
    return (
        "🎉🎉 W勝利でポイント3倍！！\n"
        "楽天イーグルス⚾×ヴィッセル神戸⚽ 勝利✨\n"
        "\n"
        "「勝ったら倍」が3倍になる超お得日🔥\n"
        "エントリーしてから買い物しよう💰\n"
        "\n"
        "エントリー👇\n"
        f"{SPORTS_URL}\n"
        "\n"
        "まとめ👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'eagles', 'vissel'], max_tags=3)}"
    )


def tweet_eagles() -> str:
    """イーグルスのみ勝利 → ポイント2倍"""
    return (
        "⚾ 楽天イーグルス勝利！\n"
        "「勝ったら倍」でポイント2倍🎉\n"
        "\n"
        "エントリーしてから買うだけでOK✅\n"
        "エントリー👇\n"
        f"{SPORTS_URL}\n"
        "\n"
        "まとめ👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'eagles', 'poikatsu'], max_tags=3)}"
    )


def tweet_vissel() -> str:
    """ヴィッセル神戸のみ勝利 → ポイント2倍"""
    return (
        "⚽ ヴィッセル神戸勝利！\n"
        "「勝ったら倍」でポイント2倍🎉\n"
        "\n"
        "エントリーしてから買うだけでOK✅\n"
        "エントリー👇\n"
        f"{SPORTS_URL}\n"
        "\n"
        "まとめ👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'vissel', 'poikatsu'], max_tags=3)}"
    )


def tweet_adidas() -> str:
    return (
        "👟 adidas セール開催中！\n"
        "\n"
        f"50%off → {ADIDAS_50}\n"
        f"40%off → {ADIDAS_40}\n"
        f"30%off → {ADIDAS_30}\n"
        f"20%off → {ADIDAS_20}\n"
        "\n"
        "マラソンと組み合わせでお得🔥\n"
        f"エントリー👇 {SITE_URL}\n"
        f" {hashtags(['core', 'adidas', 'poikatsu'], max_tags=3)}"
    )


def tweet_nike() -> str:
    return (
        "👟 NIKE 最大60%OFF開催中！\n"
        "\n"
        "マラソンと組み合わせでお得🔥\n"
        f"{NIKE_URL}\n"
        "\n"
        "エントリー👇\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'nike', 'poikatsu'], max_tags=3)}"
    )


def tweet_normal() -> str:
    return (
        "💡 楽天でお買い物する前に、まずエントリー！\n"
        "\n"
        "エントリーするだけでポイントが変わる✨\n"
        "今日のキャンペーン👇\n"
        f"{SITE_URL}\n"
        "\n"
        "クーポンも忘れずに！\n"
        f" {hashtags(['core', 'poikatsu', 'coupon'], max_tags=3)}"
    )


# ── メイン ────────────────────────────────────────────────────────────────

def main():
    now     = datetime.datetime.now(JST)
    weekday = now.weekday()   # 0=月 … 5=土 6=日
    print(f"=== 日次ツイート {now.strftime('%Y-%m-%d %H:%M JST')} ===")

    status           = load_status()
    marathon         = status.get("marathon",         False)
    marathon_pointup = status.get("marathon_pointup", False)
    eagles           = status.get("eagles",           False)
    vissel           = status.get("vissel",           False)
    adidas_on        = status.get("adidas",           False)
    nike_on          = status.get("nike",             False)
    special_days     = get_special_days(now)
    season_event     = get_season_event(now)
    month_end_phase  = get_month_end_phase(now)

    print(f"  marathon={marathon}, marathon_pointup={marathon_pointup}, eagles={eagles}, vissel={vissel}")
    print(f"  adidas={adidas_on}, nike={nike_on}, special={special_days}, season={season_event}, weekday={weekday}, month_end={month_end_phase}")

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

    # ── 優先度順に判定 ──────────────────────────────────────────────────────
    # ★ 最高優先: マラソン × W勝利 × 特別日 (年に数回の激レア役満)
    if marathon and marathon_pointup and w_victory and has_special:
        tweet = tweet_triple_combo(special_days, season_event)
        label = f"トリプル役満（マラソン×W勝利×{'・'.join(special_days) if special_days else season_event}）"

    elif marathon and marathon_pointup and w_victory:
        tweet = tweet_marathon_x_victory(w_victory=True)
        label = "マラソン×W勝利"

    elif marathon and marathon_pointup and any_victory:
        tweet = tweet_marathon_x_victory(w_victory=False, team=victor_team)
        label = f"マラソン×{victor_team}勝利"

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
    print(f"\n投稿内容:\n{tweet}\n")
    post_tweet(tweet)


if __name__ == "__main__":
    main()
