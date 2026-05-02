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
import time
import datetime
import requests
from urllib.parse import quote, urljoin
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
RAKUTEN_AFFILIATE_ID = "1c52abea.36641b1e.1c52abeb.f5f67f16"
PAY_CAMPAIGN_PAGE = "https://pay.rakuten.co.jp/campaign/?l-id=wi_pay_btn_campaign_detail"


# ── アフィリエイト ──
def aff(url: str) -> str:
    """楽天ドメインのURLをアフィリエイトハブ経由に変換"""
    if not url or 'rakuten' not in url:
        return url
    if 'hb.afl.rakuten.co.jp' in url or 'a.r10.to' in url:
        return url
    encoded = quote(url, safe='')
    return f"https://hb.afl.rakuten.co.jp/hgc/{RAKUTEN_AFFILIATE_ID}/?pc={encoded}&m={encoded}"


# ── 楽天ペイ キャンペーン情報取得 ──
# pay.rakuten.co.jp/campaign/ は JS レンダリングで動的抽出不可のため、
# ユーザーが手動キュレートした URL リスト (pay_campaigns.json) から
# 各URLを fetch して title を自動抽出する設計。
PAY_CAMPAIGNS_FILE = "pay_campaigns.json"

# 終了判定（過去キャンペーン誤抽出回避）
STRICT_END_PHRASES = [
    "本キャンペーンは終了",
    "このキャンペーンは終了",
    "このキャンペーンは終了しました",
    "本キャンペーンは終了しました",
    "ご応募の受付は終了",
    "お買い物ありがとうございました",
    "ご利用ありがとうございました",
]

# 「ページ内にこれらが見つかれば、終了句があっても active 扱い」
# 楽天ペイ等は終了メッセージを事前 HTML に埋め込んで JS で条件表示するため、
# エントリーボタンが現役で出ているなら active と判定する。
ACTIVE_SIGNALS = [
    "js_cp_entry_btn",
    "js-cp-entry-btn",
    "CT-Campaign-Entry",
    "entry-button",
    "rexEntryButtonPermission",   # 楽天ペイ系の Entry ボタン
    "campaignStep__itemTitle",    # 楽天ペイ系の「まずはエントリー！」見出し
    "エントリーする</a>",
    "エントリーする</button>",
    "エントリーはこちら",
    "エントリー受付中",
    "今すぐエントリー",
    "エントリー必要",
    "まずはエントリー",
]


def clean_campaign_title(raw_title: str) -> str:
    """ページの<title>からノイズを除去し短縮"""
    title = raw_title.strip()
    # サフィックス削除（「 - 楽天ペイアプリ」「｜楽天ポイントカード」等）
    title = re.sub(r'\s*[-｜|]\s*楽天[^-｜|]*$', '', title)
    title = re.sub(r'\s+', ' ', title).strip()
    if len(title) > 30:
        title = title[:30] + '…'
    return title


def fetch_campaign_info(url: str) -> dict:
    """1キャンペーンURLを取得し、有効性チェック後に {name, url} を返す。
    無効・終了・取得失敗の場合は None。"""
    try:
        r = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept-Language": "ja,en;q=0.9",
            },
            timeout=10,
            allow_redirects=True,
        )
        if r.status_code != 200:
            print(f"  ⚠️ HTTP {r.status_code} → スキップ: {url}")
            return None
        # 文字コード自動判定（楽天ページは UTF-8 だが Content-Type で
        # charset未指定のとき requests が ISO-8859-1 と誤推定する）
        if r.encoding is None or r.encoding.lower() in ('iso-8859-1', 'us-ascii'):
            r.encoding = r.apparent_encoding or 'utf-8'
        html = r.text
    except Exception as e:
        print(f"  ⚠️ 取得失敗 → スキップ: {url} ({e})")
        return None

    # 終了確定チェック（active シグナルがあれば誤検出回避）
    has_end = any(p in html for p in STRICT_END_PHRASES)
    has_active = any(s in html for s in ACTIVE_SIGNALS)
    if has_end and not has_active:
        print(f"  🚫 終了確定 → スキップ: {url}")
        return None

    # title 抽出
    m = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
    if not m:
        print(f"  ⚠️ titleなし → スキップ: {url}")
        return None
    name = clean_campaign_title(m.group(1))
    if not name or len(name) < 5:
        print(f"  ⚠️ title不正 → スキップ: {url}")
        return None

    print(f"  ✓ {name}")
    return {"name": name, "url": url}


def fetch_main_campaigns(max_count: int = 6) -> list:
    """pay_campaigns.json のURLリストから、有効なキャンペーン情報を集めて返す。"""
    if not os.path.exists(PAY_CAMPAIGNS_FILE):
        print(f"  ⚠️ {PAY_CAMPAIGNS_FILE} が見つからない → スキップ")
        return []
    try:
        with open(PAY_CAMPAIGNS_FILE, encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"  ⚠️ {PAY_CAMPAIGNS_FILE} 読み込み失敗: {e}")
        return []

    urls = data.get("campaigns", [])
    if not urls:
        return []

    print(f"  対象URL: {len(urls)} 件")
    campaigns = []
    for url in urls:
        info = fetch_campaign_info(url)
        if info:
            campaigns.append(info)
        if len(campaigns) >= max_count:
            break
    print(f"  有効: {len(campaigns)} 件")
    return campaigns


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


def build_tweet_routine(now: datetime.datetime) -> str:
    """ツイート①: 月初ルーティン（チェックリスト）"""
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


def _compose_campaign_tweet(now: datetime.datetime, campaigns: list, name_limit: int = 22) -> str:
    """ツイート②候補: 主要キャンペーンURL付きリスト"""
    intro = f"🎉 {now.month}月の楽天ペイ メインキャンペーン\n\n"
    body_lines = []
    for c in campaigns:
        name = c["name"]
        if len(name) > name_limit:
            name = name[:name_limit] + "…"
        body_lines.append(f"▸ {name}")
        body_lines.append(aff(c["url"]))
        body_lines.append("")
    footer = f"\nまとめ👇\n{SITE_URL}\n {hashtags(['core', 'rakutenpay', 'coupon'], max_tags=3)}"
    return intro + "\n".join(body_lines).rstrip() + footer


def build_tweet_campaigns(now: datetime.datetime, campaigns: list) -> list:
    """主要キャンペーンを 280字以内のツイートに分割。
    返り値: 投稿すべきツイート文字列のリスト（複数 = 連投）"""
    if not campaigns:
        return []

    # 1ツイートに収まる範囲で詰め込む。収まらない分は次のツイートへ。
    tweets = []
    chunk = []
    for c in campaigns:
        candidate = chunk + [c]
        if weighted_length(_compose_campaign_tweet(now, candidate)) <= 280:
            chunk = candidate
        else:
            # 現chunkを確定 → 新しいchunkでこのcから始める
            if chunk:
                tweets.append(_compose_campaign_tweet(now, chunk))
            # 単独でも収まるかチェック（名前を縮める）
            if weighted_length(_compose_campaign_tweet(now, [c], name_limit=18)) <= 280:
                chunk = [c]
            else:
                # 入らない → スキップ
                chunk = []
    if chunk:
        tweets.append(_compose_campaign_tweet(now, chunk))
    return tweets


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

    # ── ツイート①: 月初ルーティン ──
    tweet1 = build_tweet_routine(now)
    print(f"\n[1] ルーティンツイート ({weighted_length(tweet1)}字):\n{tweet1}\n")
    success1 = post_tweet(tweet1)

    # ── ツイート②以降: 主要キャンペーン（自動抽出） ──
    print("\n── 楽天ペイ主要キャンペーンを抽出中 ──")
    campaigns = fetch_main_campaigns(max_count=6)
    success_campaigns = []
    if campaigns:
        campaign_tweets = build_tweet_campaigns(now, campaigns)
        for i, ctweet in enumerate(campaign_tweets, start=2):
            print(f"\n[{i}] キャンペーンツイート ({weighted_length(ctweet)}字):\n{ctweet}\n")
            time.sleep(3)  # API rate limit 配慮
            ok = post_tweet(ctweet)
            success_campaigns.append(ok)

    # 主投稿が成功していれば履歴記録（連投失敗は許容）
    if success1:
        posted["last_posted_month"] = today_str
        posted["last_fired_at"] = now.isoformat()
        posted["last_campaign_count"] = len([s for s in success_campaigns if s])
        with open(POSTED_FILE, 'w', encoding='utf-8') as f:
            json.dump(posted, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
