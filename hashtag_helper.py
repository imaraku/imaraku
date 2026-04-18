#!/usr/bin/env python3
"""
hashtag_helper.py
ツイート用ハッシュタグの中央管理モジュール。
post_daily_tweet.py / post_marathon_alert.py / check_ranking.py から共有利用。

目的:
  - 毎回同じ組み合わせを避け、検索流入の多様化を図る（Twitterのリーチは
    同一タグの連投で下がる傾向があるため）
  - カテゴリ単位で指定できるようにし、タグ追加/入替を一箇所で管理する
"""

import datetime

JST = datetime.timezone(datetime.timedelta(hours=9))

# カテゴリ別プール（日付シードでローテーション選択される）
HASHTAG_POOLS = {
    # コア系
    "core":       ["#楽天", "#楽天経済圏", "#楽天市場"],
    "poikatsu":   ["#ポイ活", "#ポイ活初心者", "#ポイ活主婦", "#ポイ活生活"],
    "saving":     ["#節約", "#節約術", "#家計管理", "#貯金生活", "#お得情報"],

    # マラソン関連
    "marathon":   ["#お買物マラソン", "#楽天マラソン", "#楽天お買物マラソン"],
    "entry":      ["#エントリー必須", "#エントリー忘れずに"],

    # 特別日
    "wonderful":  ["#ワンダフルデー"],
    "ichibaday":  ["#楽天市場の日"],
    "zerogo":     ["#0と5のつく日"],
    "furusato":   ["#ふるさと納税", "#ふるさと納税返礼品"],

    # スポーツ
    "eagles":     ["#楽天イーグルス", "#勝ったら倍"],
    "vissel":     ["#ヴィッセル神戸", "#勝ったら倍"],

    # ブランド
    "adidas":     ["#adidas", "#アディダス", "#スニーカー"],
    "nike":       ["#NIKE", "#ナイキ", "#スニーカー"],

    # 季節イベント
    "christmas":  ["#クリスマス", "#クリスマスプレゼント"],
    "newyear":    ["#新年", "#お年玉", "#初売り"],
    "valentine":  ["#バレンタイン", "#チョコレート"],
    "whiteday":   ["#ホワイトデー", "#お返しギフト"],
    "mothers":    ["#母の日", "#母の日ギフト"],
    "fathers":    ["#父の日", "#父の日ギフト"],

    # ランキング/商品カテゴリ
    "ranking":    ["#楽天ランキング", "#ランキング", "#売れ筋"],
    "contact":    ["#コンタクトレンズ", "#コンタクト"],
    "water":      ["#ミネラルウォーター", "#炭酸水", "#宅配"],
    "rice":       ["#お米", "#米", "#ごはん"],
    "daily":      ["#日用品", "#まとめ買い"],
    "detergent":  ["#洗剤", "#日用品"],
    "coupon":     ["#楽天クーポン", "#クーポン"],

    # 期間限定ポイント失効注意（月末2日）
    "pointexpire": ["#期間限定ポイント", "#楽天ポイント", "#ポイント失効"],
}


def hashtags(categories, now=None, max_tags=5):
    """カテゴリ名のリストから実際のタグ文字列を組み立てる。
    month+day でローテーションし、毎回同じ組み合わせにならないようにする。

    Args:
        categories: HASHTAG_POOLS のキー名リスト
        now: 基準日時（省略時は現在JST）
        max_tags: 最大タグ数（Twitterの推奨は2〜5程度）

    Returns:
        "#タグ1 #タグ2 #タグ3" 形式の文字列
    """
    if now is None:
        now = datetime.datetime.now(JST)
    seed = now.month * 31 + now.day
    result = []
    seen = set()
    for cat in categories:
        pool = HASHTAG_POOLS.get(cat, [])
        if not pool:
            continue
        tag = pool[seed % len(pool)]
        if tag not in seen:
            result.append(tag)
            seen.add(tag)
        if len(result) >= max_tags:
            break
    return " ".join(result)
