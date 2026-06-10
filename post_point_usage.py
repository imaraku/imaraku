#!/usr/bin/env python3
"""
post_point_usage.py
楽天ポイント付与日（多くは毎月15日頃）の翌日にあたる16日に
ポイント活用ヒントを発信する。

【設計】
  ・月別に6種類のヒントをローテーション → 飽きさせない
  ・通常ポイント vs 期間限定ポイント の使い分けに焦点
  ・SPU還元を落とさない使い方を中心に、相棒オリジナルの知見も含む
"""

import os
import re
import sys
import json
import time
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
POSTED_FILE = "point_usage_posted.json"


# ── 6種類のヒント（月別ローテーション） ───────────────────────────
# キー = 月 (1-12)、値 = (intro, body) のペア
# 1月・7月、2月・8月... のように月差6で同じヒントが回る → 1ヒント= 1年で2回登場

def tip_efficiency() -> str:
    """SPU効率温存テク"""
    return (
        "💡 ポイント効率を落とさない使い方\n"
        "\n"
        "楽天市場のSPUは「100円(税抜)につき1pt」基準。\n"
        "例: 1,280円の買い物なら80ptだけ使う\n"
        "→ 残り1,200円分はSPU還元対象のまま✨\n"
        "\n"
        "細かいけど、年間で見ると差が出る😉\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'poikatsu', 'spu'], max_tags=3)}"
    )


def tip_regular_uses() -> str:
    """通常ポイントの使い道3選"""
    return (
        "💡 通常ポイントの賢い使い道3選\n"
        "\n"
        "✅ 楽天ペイで街使い（還元継続）\n"
        "✅ 楽天キャッシュへチャージ\n"
        "✅ 楽天証券で投資信託購入\n"
        "\n"
        "⚠️ 楽天市場で支払いに使うと\n"
        "   その分のSPU還元が消えるので注意\n"
        "\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'poikatsu', 'rakutenpoint'], max_tags=3)}"
    )


def tip_pay_kogai() -> str:
    """楽天ペイ街使い（期間限定救済）"""
    return (
        "💡 期間限定ポイント、街で使い切ろう\n"
        "\n"
        "楽天ペイ設定すれば\n"
        "コンビニ・コメダ・松屋などで\n"
        "ポイント=支払いに使える🛍️\n"
        "\n"
        "失効する前に楽天ペイで救出💪\n"
        "（楽天キャッシュチャージは通常pt限定）\n"
        "\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'rakutenpay', 'poikatsu'], max_tags=3)}"
    )


def tip_invest() -> str:
    """ポイント投資"""
    return (
        "💡 通常ポイントで投資信託\n"
        "\n"
        "楽天証券に口座あれば\n"
        "1pt = 1円としてファンド購入OK✨\n"
        "SPU楽天証券条件にもなって一石二鳥🎯\n"
        "\n"
        "「使わない通常ポイント」の最適解💡\n"
        "（期間限定ptは投信不可）\n"
        "\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'poikatsu', 'rakutenshouken'], max_tags=3)}"
    )


def tip_cash_charge() -> str:
    """楽天キャッシュチャージ"""
    return (
        "💡 楽天キャッシュ経由で +0.5%\n"
        "\n"
        "通常ポイント\n"
        "→ 楽天キャッシュへチャージ\n"
        "→ 楽天ペイで支払い = +0.5%還元\n"
        "\n"
        "ポイントを使いながら増やすテク🔁\n"
        "（期間限定ptはチャージ不可・要注意）\n"
        "\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'rakutencash', 'poikatsu'], max_tags=3)}"
    )


def tip_mobile_payment() -> str:
    """楽天モバイル料金充当"""
    return (
        "💡 楽天モバイル ユーザー特権\n"
        "\n"
        "楽天モバイル料金は\n"
        "✅ 通常ポイント\n"
        "✅ 期間限定ポイント\n"
        "両方で支払いOK✨\n"
        "\n"
        "毎月の固定費を実質ポイントで賄える💪\n"
        "期限切れ救済にもなる便利技\n"
        "\n"
        f"{SITE_URL}\n"
        f" {hashtags(['core', 'rakutenmobile', 'poikatsu'], max_tags=3)}"
    )


# 月別ヒント割り当て（月1〜12 → 6種ヒントを2巡）
TIP_FUNCS = [
    tip_efficiency,        # 1月, 7月
    tip_regular_uses,      # 2月, 8月
    tip_pay_kogai,         # 3月, 9月
    tip_invest,            # 4月, 10月
    tip_cash_charge,       # 5月, 11月
    tip_mobile_payment,    # 6月, 12月
]


def weighted_length(text: str) -> int:
    text_for_count = re.sub(r'https?://\S+', 'X' * 23, text)
    n = 0
    for ch in text_for_count:
        n += 1 if ord(ch) < 0x80 else 2
    return n


_POST_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def post_tweet(text: str) -> bool:
    """X 投稿。Cloudflare 403 / 429 / 5xx は最大3回リトライ（地雷#15）。"""
    auth = OAuth1(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
    headers = {"Content-Type": "application/json", "User-Agent": _POST_UA}
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


def main():
    now = datetime.datetime.now(JST)
    today_str = now.strftime("%Y-%m-%d")
    month_key = now.strftime("%Y-%m")
    print(f"=== ポイント活用ヒント {now.strftime('%Y-%m-%d %H:%M JST')} ===")

    # 16日のみ実行
    if now.day != 16:
        print(f"  → {now.day}日は対象外（16日にのみ投稿）→ スキップ")
        return

    # 月次重複排除
    posted = {}
    if os.path.exists(POSTED_FILE):
        try:
            with open(POSTED_FILE, encoding='utf-8') as f:
                posted = json.load(f)
        except Exception:
            pass
    if posted.get("last_posted_month") == month_key:
        print(f"  → 今月({month_key})は既に投稿済 → スキップ")
        return

    # 月別ヒント選択
    tip_idx = (now.month - 1) % len(TIP_FUNCS)
    tip_func = TIP_FUNCS[tip_idx]
    tweet = tip_func()
    print(f"\n選択ヒント: {tip_func.__name__}")
    print(f"投稿内容 ({weighted_length(tweet)}字):\n{tweet}\n")

    if post_tweet(tweet):
        posted["last_posted_month"] = month_key
        posted["last_fired_at"] = now.isoformat()
        posted["last_tip"] = tip_func.__name__
        with open(POSTED_FILE, 'w', encoding='utf-8') as f:
            json.dump(posted, f, ensure_ascii=False, indent=2)
    else:
        print("❌ post_tweet が False → exit 1（failure 通知用）", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
