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
    "marathon":   ["#お買い物マラソン", "#楽天マラソン", "#楽天お買い物マラソン"],
    "entry":      ["#エントリー必須", "#エントリー忘れずに"],

    # スーパーSALE
    "supersale":  ["#楽天スーパーセール", "#楽天スーパーSALE", "#スーパーセール"],

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

    # トラベル / 楽天ペイ（2026-06-11: 参照されていたのにプール未定義だったので追加）
    "travel":     ["#楽天トラベル", "#国内旅行", "#旅行好きな人と繋がりたい"],
    "rakutenpay": ["#楽天ペイ", "#キャッシュレス", "#楽天ポイント"],

    # カテゴリTOP1系（2026-07-05 監査: category_ranking.json から参照されるのに未定義で
    # タグが3本→2本にサイレント縮退していたため追加）
    "health":     ["#健康管理", "#ボディメイク", "#セルフケア"],
    "food":       ["#お取り寄せ", "#おうちごはん", "#お取り寄せグルメ"],
    "sweets":     ["#お取り寄せスイーツ", "#おやつ", "#スイーツ好きな人と繋がりたい"],
    "pet":        ["#ペットのいる暮らし", "#犬のいる暮らし", "#猫のいる暮らし"],

    # 季節モーメント投稿（seasonal_moments.json の tag_pool から参照・2026-07-09）
    "natsuyasumi": ["#夏休み", "#夏休みの過ごし方", "#子どもとおでかけ"],
    "hanabi":      ["#花火大会", "#夏祭り", "#浴衣"],
    "obon":        ["#お盆", "#帰省", "#手土産"],
    "shingakki":   ["#新学期", "#新学期準備", "#入学準備"],
    # 年間カレンダー分（2026-07-09 拡張）
    "bousai":      ["#防災", "#防災グッズ", "#備蓄"],
    "keirou":      ["#敬老の日", "#敬老の日ギフト", "#プレゼント"],
    "undoukai":    ["#運動会", "#行楽弁当", "#秋のおでかけ"],
    "halloween":   ["#ハロウィン", "#ハロウィン仮装", "#ハロウィンパーティー"],
    "fuyujitaku":  ["#冬支度", "#鍋料理", "#こたつ"],
    "oosouji":     ["#大掃除", "#年末大掃除", "#収納術"],
    "juken":       ["#受験生", "#受験生応援", "#勉強垢さんと繋がりたい"],
    "kafun":       ["#花粉症", "#花粉対策", "#花粉症対策"],
    "shinseikatsu": ["#新生活", "#引越し", "#一人暮らし準備"],
    "gw":          ["#ゴールデンウィーク", "#こどもの日", "#GWの過ごし方"],
    "tsuyu":       ["#梅雨", "#梅雨対策", "#部屋干し"],
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
