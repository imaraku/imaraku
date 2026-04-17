#!/usr/bin/env python3
"""
post_pokemon_lottery.py
楽天ブックス ポケモンカード抽選情報をスレッド形式でXに投稿する（手動実行用）。
"""

import os
import sys
import requests
from requests_oauthlib import OAuth1

API_KEY             = os.environ["TWITTER_API_KEY"]
API_SECRET          = os.environ["TWITTER_API_SECRET"]
ACCESS_TOKEN        = os.environ["TWITTER_ACCESS_TOKEN"]
ACCESS_TOKEN_SECRET = os.environ["TWITTER_ACCESS_TOKEN_SECRET"]

def aff(url: str) -> str:
    """楽天ブックスURLにアフィリエイトパラメータを付与する。"""
    sep = "&" if "?" in url else "?"
    return url + sep + "scid=af_pc_etc&sc2id=af_101_0_0"

# ── 対象商品リスト ────────────────────────────────────────────────────────────
PRODUCTS = [
    ("ニンジャスピナー",                       "https://books.rakuten.co.jp/rb/18460920/"),
    ("ムニキスゼロ",                           "https://books.rakuten.co.jp/rb/18401985/"),
    ("スタートデッキ100 バトルコレクション5個", "https://books.rakuten.co.jp/rb/18548589/"),
    ("MEGAドリームex",                         "https://books.rakuten.co.jp/rb/18343992/"),
    ("インフェルノX",                          "https://books.rakuten.co.jp/rb/18287437/"),
    ("メガブレイブ",                           "https://books.rakuten.co.jp/rb/18182237/"),
    ("メガシンフォニア",                       "https://books.rakuten.co.jp/rb/18182238/"),
    ("ブラックボルト",                         "https://books.rakuten.co.jp/rb/18084512/"),
    ("ホワイトフレア",                         "https://books.rakuten.co.jp/rb/18084513/"),
    ("ロケット団の栄光",                       "https://books.rakuten.co.jp/rb/18061661/"),
    ("熱風のアリーナ",                         "https://books.rakuten.co.jp/rb/18061660/"),
    ("バトルパートナーズ",                     "https://books.rakuten.co.jp/rb/17970166/"),
    ("テラスタルフェスex",                     "https://books.rakuten.co.jp/rb/17930728/"),
    ("超電ブレイカー",                         "https://books.rakuten.co.jp/rb/17962868/"),
    ("スペシャルカードセット MEGAエルレイドex", "https://books.rakuten.co.jp/rb/18401986/"),
    ("スターターセットMEGA メガゲンガーex",    "https://books.rakuten.co.jp/rb/18182244/"),
    ("プレミアムトレーナーボックス MEGA",      "https://books.rakuten.co.jp/rb/18182239/"),
]

# ── スレッド本文 ──────────────────────────────────────────────────────────────
def build_thread() -> list[str]:
    # ツイート1: 概要
    tweet1 = (
        "🎴 楽天ブックスでポケモンカード抽選受付中！\n"
        "\n"
        "📅 受付: 4/17(金)10時〜4/20(月)9:59\n"
        "🛒 購入: 4/27(月)〜5/1(金)\n"
        "🚛 発送: 4月下旬予定\n"
        "\n"
        f"新弾・人気パック{len(PRODUCTS)}種がラインナップ🎯\n"
        "各商品のエントリーリンクは続くツイートから👇\n"
        "\n"
        "#楽天ブックス #ポケモンカード #ポイ活"
    )

    # ツイート2〜4: 商品リストを6件ずつに分割
    product_tweets = []
    chunk_size = 6
    chunks = [PRODUCTS[i:i+chunk_size] for i in range(0, len(PRODUCTS), chunk_size)]
    for idx, chunk in enumerate(chunks, 1):
        lines = [f"【対象商品 {idx}/{len(chunks)}】"]
        for name, url in chunk:
            lines.append(f"・{name}")
            lines.append(aff(url))
        product_tweets.append("\n".join(lines))

    return [tweet1] + product_tweets


# ── 投稿処理 ──────────────────────────────────────────────────────────────────
def post_tweet(text: str) -> str | None:
    auth = OAuth1(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
    resp = requests.post(
        "https://api.twitter.com/2/tweets",
        auth=auth,
        json={"text": text},
        headers={"Content-Type": "application/json"},
    )
    if resp.status_code == 201:
        tweet_id = resp.json()["data"]["id"]
        print(f"✅ 投稿成功: {tweet_id}")
        return tweet_id
    print(f"❌ 投稿失敗: {resp.status_code} {resp.text}", file=sys.stderr)
    return None


def main():
    tweets = build_thread()
    print(f"=== ポケモンカード抽選投稿 ({len(tweets)}件) ===\n")

    for i, text in enumerate(tweets, 1):
        print(f"── ツイート {i}/{len(tweets)} ──")
        print(text)
        print()
        tweet_id = post_tweet(text)
        if tweet_id is None:
            print("投稿に失敗したため中断します。", file=sys.stderr)
            sys.exit(1)

    print("\n🎉 投稿完了！")


if __name__ == "__main__":
    main()
