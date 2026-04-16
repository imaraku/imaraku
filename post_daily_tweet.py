#!/usr/bin/env python3
"""
post_daily_tweet.py
毎朝 9:00 JST（= 0:00 UTC）に実行。
今日のキャンペーン状況・曜日・日付に応じたツイートを投稿する。

【優先度順】
  1. マラソン × 特別日（0と5のつく日 or ワンダフルデー）→ ビッグチャンス
  2. マラソン開催中                                      → eギフト活用ヒント
  3. ワンダフルデー（18日）                              → ワンダフルデー告知
  4. 0と5のつく日（5/10/15/20/25/30日）                  → 0と5のつく日告知
  5. 楽天イーグルス勝利ボーナス開催中                    → 勝利ボーナス告知
  6. 土曜日                                              → adidas 特集
  7. 日曜日                                              → NIKE 特集
  8. 通常日                                              → 39ショップ・リピート・ゲリラ告知
"""

import os
import sys
import json
import datetime
import requests
from requests_oauthlib import OAuth1

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
    """今日の特別なキャンペーン日を返す。"""
    day = now.day
    special = []
    if day % 5 == 0:          # 5, 10, 15, 20, 25, 30日
        special.append("0と5のつく日")
    if day == 18:
        special.append("ワンダフルデー")
        special.append("楽天市場の日")
    return special


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

def tweet_marathon_big_chance(special_days: list) -> str:
    events = "・".join(special_days)
    return (
        f"🔥 今日はビッグチャンス！\n"
        f"マラソン × {events} が重なってます✨\n"
        "\n"
        "今日のお買い物でポイントをまとめて稼ごう💡\n"
        "\n"
        "買いたいものがなくても楽券・Appleギフトで買い周りOK！\n"
        "\n"
        "まとめてエントリーはこちら👇\n"
        f"{SITE_URL}\n"
        "\n"
        "#楽天 #お買物マラソン #ポイ活 #節約術"
    )


def tweet_marathon_entry_only() -> str:
    """エントリー期間中だがポイントアップ期間まだ開始していない場合"""
    return (
        "🏃 お買物マラソン、エントリー受付中！\n"
        "\n"
        "⚠️ ただし今はまだ「エントリー期間」です\n"
        "ポイントアップが始まるのはもう少し後。\n"
        "\n"
        "✅ でも今のうちに【エントリーだけ】はしておこう！\n"
        "エントリーしないとポイントアップ対象外になります。\n"
        "\n"
        "ポイントアップ期間が始まったら\n"
        "一気に複数ショップで買いまわりがお得🛒\n"
        "\n"
        "まとめてエントリーはこちら👇\n"
        f"{SITE_URL}\n"
        "\n"
        "#楽天 #お買物マラソン #ポイ活 #節約術"
    )


def tweet_marathon_normal() -> str:
    return (
        "🏃 お買物マラソン開催中！\n"
        "\n"
        "買いたいものがない方も\n"
        "📦 楽券(eギフト)→ローソン・ファミマ・コメダ等で使えます\n"
        f"{RAKKEN_URL}\n"
        "🍎 Appleギフトカードも対象！\n"
        f"{APPLE_URL}\n"
        "\n"
        "エントリーまとめ👇\n"
        f"{SITE_URL}\n"
        "\n"
        "#楽天 #お買物マラソン #ポイ活"
    )


def tweet_wonderful_day() -> str:
    return (
        "🎉 今日はワンダフルデー＆楽天市場の日！\n"
        "（毎月18日限定のお得な日です）\n"
        "\n"
        "39ショップなど定番エントリーも忘れずに✨\n"
        "エントリーするだけでポイントがお得に！\n"
        "\n"
        "まとめてエントリーはこちら👇\n"
        f"{SITE_URL}\n"
        "\n"
        "#楽天 #ワンダフルデー #楽天市場の日 #ポイ活"
    )


def tweet_zero_five_day() -> str:
    return (
        "📅 今日は0と5のつく日！\n"
        "楽天カード利用で【ふるさと納税】もポイント+1倍💳\n"
        "\n"
        "💡 物価高の今こそ、早めのふるさと納税がお得！\n"
        "・年末より今のほうが品数が圧倒的に豊富\n"
        "・年末の駆け込みは人気返礼品が売り切れ続出😰\n"
        "・今なら選び放題でじっくり検討できます✨\n"
        "\n"
        "ふるさと納税キャンペーンはこちら👇\n"
        f"{POINTDAY_URL}\n"
        "\n"
        "エントリーまとめ👇\n"
        f"{SITE_URL}\n"
        "\n"
        "#楽天 #ふるさと納税 #0と5のつく日 #ポイ活 #節約術"
    )


def tweet_w_victory() -> str:
    """イーグルス＆ヴィッセル神戸W勝利 → ポイント3倍"""
    return (
        "🎉🎉 W勝利でポイント3倍！！\n"
        "楽天イーグルス⚾ × ヴィッセル神戸⚽ 両チーム勝利！\n"
        "\n"
        "今日は「勝ったら倍」キャンペーンが\n"
        "なんとポイント3倍になっています🔥\n"
        "\n"
        "エントリーしてからお買い物すると\n"
        "いつもより大幅にポイントが貯まります💰\n"
        "\n"
        "エントリーはこちら👇\n"
        f"{SPORTS_URL}\n"
        "\n"
        "その他エントリーまとめ👇\n"
        f"{SITE_URL}\n"
        "\n"
        "#楽天 #楽天イーグルス #ヴィッセル神戸 #勝ったら倍 #ポイ活 #節約術"
    )


def tweet_eagles() -> str:
    """イーグルスのみ勝利 → ポイント2倍"""
    return (
        "⚾ 楽天イーグルス勝利！\n"
        "「勝ったら倍」キャンペーンでポイント2倍🎉\n"
        "\n"
        "エントリーしてからお買い物するだけでOK✅\n"
        "忘れずにエントリーを👇\n"
        f"{SPORTS_URL}\n"
        "\n"
        "その他エントリーまとめ👇\n"
        f"{SITE_URL}\n"
        "\n"
        "#楽天 #楽天イーグルス #勝ったら倍 #ポイ活"
    )


def tweet_vissel() -> str:
    """ヴィッセル神戸のみ勝利 → ポイント2倍"""
    return (
        "⚽ ヴィッセル神戸勝利！\n"
        "「勝ったら倍」キャンペーンでポイント2倍🎉\n"
        "\n"
        "エントリーしてからお買い物するだけでOK✅\n"
        "忘れずにエントリーを👇\n"
        f"{SPORTS_URL}\n"
        "\n"
        "その他エントリーまとめ👇\n"
        f"{SITE_URL}\n"
        "\n"
        "#楽天 #ヴィッセル神戸 #勝ったら倍 #ポイ活"
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
        "お買物マラソンと組み合わせてさらにお得🔥\n"
        f"エントリーはこちら👇 {SITE_URL}\n"
        "\n"
        "#楽天 #adidas #ポイ活"
    )


def tweet_nike() -> str:
    return (
        "👟 NIKE 最大60%OFF開催中！\n"
        "\n"
        "お買物マラソンと組み合わせてさらにお得🔥\n"
        f"{NIKE_URL}\n"
        "\n"
        "エントリー忘れずに👇\n"
        f"{SITE_URL}\n"
        "\n"
        "#楽天 #NIKE #ポイ活"
    )


def tweet_normal() -> str:
    return (
        "💡 楽天でお買い物する前に、まずエントリー！\n"
        "\n"
        "エントリーするだけでポイントが変わります✨\n"
        "今日のキャンペーンをまとめてチェック👇\n"
        f"{SITE_URL}\n"
        "\n"
        "クーポンも忘れずに！\n"
        "\n"
        "#楽天 #ポイ活 #節約術"
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

    print(f"  marathon={marathon}, marathon_pointup={marathon_pointup}, eagles={eagles}, vissel={vissel}, adidas={adidas_on}, nike={nike_on}, special={special_days}, weekday={weekday}")

    # 優先度順に判定
    if marathon and marathon_pointup and special_days:
        # ポイントアップ期間中 × 特別日 → 最大のビッグチャンス
        tweet = tweet_marathon_big_chance(special_days)
        label = "マラソン（ポイントアップ中）×特別日（ビッグチャンス）"

    elif marathon and marathon_pointup:
        # ポイントアップ期間中 → 今すぐ買いまわりを促す
        tweet = tweet_marathon_normal()
        label = "マラソン（ポイントアップ期間中）"

    elif marathon and not marathon_pointup:
        # エントリー期間のみ → まずエントリーを促す（まだ買わなくてOK）
        tweet = tweet_marathon_entry_only()
        label = "マラソン（エントリー期間のみ・ポイントアップ未開始）"

    elif 18 == now.day:          # ワンダフルデー / 市場の日
        tweet = tweet_wonderful_day()
        label = "ワンダフルデー"

    elif now.day % 5 == 0:       # 0と5のつく日
        tweet = tweet_zero_five_day()
        label = "0と5のつく日"

    elif eagles and vissel:      # W勝利 → 3倍（最優先）
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
