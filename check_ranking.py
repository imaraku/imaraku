#!/usr/bin/env python3
"""
check_ranking.py
楽天ランキング上位アイテムをチェックし、X(Twitter)に投稿する。

【動作ロジック】
  1. ランキングページをスクレイピングして上位アイテムを取得
  2. 前回キャッシュと比較して「新規ランクイン」を検出
  3. レアアイテム（ゲーム・シール等）が新規ランクインしたら即ツイート
  4. 定期的に「常連アイテム」の便利さをアピール（月・水・金）
"""

import os
import re
import sys
import json
import datetime
import requests
from urllib.parse import quote
from bs4 import BeautifulSoup
from requests_oauthlib import OAuth1

from hashtag_helper import hashtags

# ── 認証情報 ─────────────────────────────────────────────────────────────────
API_KEY             = os.environ["TWITTER_API_KEY"]
API_SECRET          = os.environ["TWITTER_API_SECRET"]
ACCESS_TOKEN        = os.environ["TWITTER_ACCESS_TOKEN"]
ACCESS_TOKEN_SECRET = os.environ["TWITTER_ACCESS_TOKEN_SECRET"]

# 楽天ウェブサービスの認証情報（無料登録: https://webservice.rakuten.co.jp/）
# 2024年以降の新APIは applicationId + accessKey + Origin ヘッダの3点セットが必要。
# 未設定時はスクレイピングへフォールバック（ranking.rakuten.co.jp は Bot 遮断で 403）。
RAKUTEN_APP_ID     = os.environ.get("RAKUTEN_APP_ID", "").strip()
RAKUTEN_ACCESS_KEY = os.environ.get("RAKUTEN_ACCESS_KEY", "").strip()
RAKUTEN_ORIGIN     = os.environ.get("RAKUTEN_ORIGIN", "https://imaraku.github.io").strip()

# ── 定数 ─────────────────────────────────────────────────────────────────────
JST          = datetime.timezone(datetime.timedelta(hours=9))
RANKING_BASE = "https://ranking.rakuten.co.jp/"
RANKING_URL  = RANKING_BASE + "?scid=af_pc_etc&sc2id=af_101_0_0"
SITE_URL     = "https://imaraku.github.io/imaraku/imaraku.html"
CACHE_FILE   = "ranking_cache.json"

# レアアイテム検出キーワード（新規ランクインしたら即ツイート）
# 注: 「カード」「グッズ」「限定」などの一般名詞は誤検出を招くため、
# 固有名詞・プラットフォーム名に絞り込んでいる
RARE_KEYWORDS = [
    # ゲーム機・ソフト関連（Nintendo は単体でも対応、商品名【Switch】等の括弧記号回避）
    "Nintendo", "Switch2", "PlayStation", "PS5", "Xbox",
    # 人気ゲームソフトフランチャイズ
    "ゼルダ", "スーパーマリオ", "どうぶつの森", "スプラトゥーン", "スマブラ",
    "トモダチコレクション", "ファイアーエムブレム", "ポケモンSV", "ポケモンレジェンズ",
    # ポケモン・鬼滅・ジャンプ系人気IP（英字・カナ両対応）
    "ポケモン", "ポケットモンスター", "鬼滅", "ワンピース", "ONE PIECE", "推しの子",
    "ドラゴンボール", "DRAGON BALL", "呪術廻戦",
    # アニメ・漫画 IP（最新トレンド枠 2026-05追加）
    "ハイキュー", "葬送のフリーレン", "薬屋のひとりごと", "キングダム", "ガンダム",
    "Apple", "iPhone", "iPad", "AirPods", "Meta Quest",
    # トレカ系（ポケカ・遊戯王・MTG 等）
    "ポケカ", "ポケモンカードゲーム", "遊戯王", "マジック：ザ・ギャザリング",
    # 推し活・コレクター人気
    "たまごっち", "Tamagotchi", "サンリオ", "ちいかわ",
    "ドロップシール", "プチドロップ", "ぷくキラ", "ぬいぐるみ ぬいば",
    # 音楽・アイドル（リリース日にランキング急上昇する人気アクト）
    "Snow Man", "SnowMan", "なにわ男子", "King & Prince", "SixTONES",
    "Travis Japan", "Aぇ! group", "Number_i", "timelesz",
    "BTS", "NewJeans", "TWICE", "SEVENTEEN", "Stray Kids",
    "YOASOBI", "Mrs. GREEN APPLE", "King Gnu", "Ado", "米津玄師",
    "Official髭男dism", "back number",
    # マラソン期に急上昇しがちな注目ショップ（相棒お気に入り）
    "DRIP COFFEE FACTORY",
    # コーヒー（相棒の趣味枠 + マラソン期に上位入りで ポイントUP チャンスのサイン）
    "コーヒー",
    # イベント・抽選系
    "抽選販売", "予約受付", "先行予約",
]

# 常連アイテムのツイートテンプレート（月・水・金でローテーション）
# 【2026-05-23 改修】 (body, tags) tuple から dict に変更し、
# その場でリアルタイムランキング上位の具体商品を埋め込む方式へ。
# 読者がランキングページを開く手間を省き、CTRを上げる狙い（相棒の提案）。
#
# 各エントリ:
#   body:            ツイート本文（"✨ランキング上位商品✨" 行の前で終わる）
#   tags:            ハッシュタグカテゴリ（hashtags() に渡す）
#   genre_id:        該当ジャンルの top-level genreId（None なら総合 = 0）
#   filter_keywords: 商品名にいずれか1語を含むものだけ採用（ジャンルゲーミング対策と同じ思想）
#   rank_label:      "リアルタイムランキング {rank_label} X位⏰" の差し込み語
REGULAR_TWEETS = [
    # コンタクトレンズ
    {
        "name": "コンタクトレンズ",
        "body": (
            "👁 コンタクトレンズ、楽天で買ってる？\n"
            "\n"
            "実は市販・眼科より楽天市場の方が\n"
            "安いことがほとんど💡\n"
            "ポイントも貯まる＆使えてお得🏆"
        ),
        "tags": ["core", "contact", "poikatsu"],
        "genre_id": 100934,  # 医薬品・コンタクト・介護
        "filter_keywords": ["コンタクト", "ワンデー", "1day", "1DAY", "アキュビュー", "レンズ", "シード", "メニコン", "クーパー"],
        "rank_label": "医薬品・コンタクト",
    },
    # お水・炭酸水
    {
        "name": "お水・炭酸水",
        "body": (
            "💧 重い飲料こそ楽天で！\n"
            "\n"
            "お水・炭酸水を箱買いしても\n"
            "玄関まで届くから体への負担ゼロ✨\n"
            "スーパーより安く、ポイントも👍"
        ),
        "tags": ["core", "water", "poikatsu"],
        "genre_id": 100533,  # 食品
        "filter_keywords": ["炭酸水", "ミネラルウォーター", "天然水", "シリカ水", "強炭酸", "OZA SODA", "ウィルキンソン", "サンガリア", "南アルプス"],
        "rank_label": "食品",
    },
    # ティッシュ・トイレットペーパー
    {
        "name": "ティッシュ・トイレットペーパー",
        "body": (
            "🧻 かさばる日用品も楽天にお任せ！\n"
            "\n"
            "ティッシュ・トイレットペーパーは\n"
            "重くてかさばって大変…😅\n"
            "楽天なら玄関まで届きます✨\n"
            "まとめ買いでさらにお得💡"
        ),
        "tags": ["core", "daily", "poikatsu"],
        "genre_id": 100939,  # 日用品雑貨・文房具・手芸
        "filter_keywords": ["ティッシュ", "トイレットペーパー", "キッチンペーパー", "鼻セレブ", "エリエール", "スコッティ", "ネピア"],
        "rank_label": "日用品",
    },
    # お米
    {
        "name": "お米",
        "body": (
            "🍚 重いお米も楽天でお得に！\n"
            "\n"
            "5kg・10kgのお米を運ぶのは重労働…\n"
            "楽天なら玄関まで届きます🏠\n"
            "ポイントも貯まる＆定期便割引も💡"
        ),
        "tags": ["core", "rice", "poikatsu"],
        "genre_id": 100533,  # 食品
        "filter_keywords": ["米 ", " 米", "白米", "玄米", "新米", "コシヒカリ", "あきたこまち", "ひとめぼれ", "つや姫", "ゆめぴりか", "ササニシキ"],
        "rank_label": "食品",
    },
    # 洗剤・柔軟剤
    {
        "name": "洗剤・柔軟剤",
        "body": (
            "🫧 洗剤・柔軟剤も楽天でまとめ買い！\n"
            "\n"
            "重くてかさばる洗剤こそ宅配が便利✨\n"
            "ポイントが貯まって\n"
            "スーパーよりお得なことも💡"
        ),
        "tags": ["core", "detergent", "daily"],
        "genre_id": 100939,  # 日用品
        "filter_keywords": ["洗剤", "柔軟剤", "アタック", "アリエール", "ボールド", "ナノックス", "ハミング", "ファーファ", "レノア"],
        "rank_label": "日用品",
    },
    # ランキング全般（総合 TOP の旬を投げる）
    {
        "name": "総合ランキング",
        "body": (
            "🏆 楽天ランキング、チェックしてる？\n"
            "\n"
            "毎日リアルタイムで更新されるから\n"
            "買い物のヒントにもなります🛒\n"
            "エントリー併用でポイント最大化💡"
        ),
        "tags": ["core", "ranking", "poikatsu"],
        "genre_id": 0,           # 総合
        "filter_keywords": None,  # フィルタなし = TOP1 をそのまま採用
        "rank_label": "総合",
    },
]


def fetch_top_ranked_item(genre_id: int, filter_keywords=None, hits: int = 30):
    """指定ジャンルのリアルタイムランキングから、filter_keywords のいずれかに
    マッチする最上位アイテム＋順位を返す。
    Returns: {"name", "url", "rank"} または None
    """
    if not RAKUTEN_APP_ID or not RAKUTEN_ACCESS_KEY:
        return None
    url = "https://openapi.rakuten.co.jp/ichibaranking/api/IchibaItem/Ranking/20220601"
    params = {
        "format": "json",
        "applicationId": RAKUTEN_APP_ID,
        "accessKey": RAKUTEN_ACCESS_KEY,
        "period": "realtime",
        "hits": min(hits, 30),
        "genreId": genre_id,
    }
    try:
        r = requests.get(url, params=params, headers={"Origin": RAKUTEN_ORIGIN}, timeout=20)
        if r.status_code != 200:
            print(f"  ⚠️ ランキング取得失敗(genre={genre_id}): {r.status_code} body={r.text[:200]}", file=sys.stderr)
            return None
        data = r.json()
    except Exception as e:
        print(f"  ⚠️ ランキング取得例外(genre={genre_id}): {e}", file=sys.stderr)
        return None
    for idx, entry in enumerate(data.get("Items", []), 1):
        it = entry.get("Item", {})
        name = (it.get("itemName") or "").strip()
        item_url = (it.get("itemUrl") or "").strip()
        if not name or not item_url:
            continue
        if filter_keywords and not any(kw in name for kw in filter_keywords):
            continue
        return {"name": name, "url": add_affiliate(item_url), "rank": idx}
    return None


def build_regular_tweet(entry: dict) -> str:
    """REGULAR_TWEETS の1エントリから、TOP商品付きツイートを組み立てる。
    ランキング取得失敗・該当無しの場合は本文＋ハッシュタグだけのシンプル版にフォールバック。"""
    body = entry["body"]
    tags = entry["tags"]
    genre_id = entry.get("genre_id", 0)
    filters = entry.get("filter_keywords")
    rank_label = entry.get("rank_label", "")

    top = fetch_top_ranked_item(genre_id, filters)
    if top:
        return (
            f"{body}\n"
            f"\n"
            f"✨ランキング上位商品✨\n"
            f"{top['url']}\n"
            f"\n"
            f"現在、リアルタイムランキング{rank_label} {top['rank']}位⏰\n"
            f" {hashtags(tags, max_tags=3)}"
        )
    # フォールバック: 該当商品取得できなかった場合は シンプル本文 + ハッシュタグのみ
    # （ランキングページURLを載せると imaraku 経路と類似してXがflag気味なので URL なしで様子見）
    print(f"  ℹ️ {entry['name']}: TOP商品取得不可 → URL なしフォールバック", file=sys.stderr)
    return f"{body}\n\n {hashtags(tags, max_tags=3)}"


# 人気IP/ブランド → ハッシュタグ 自動検出辞書
# 商品名にキーワードが含まれていたら該当タグを付与してファン層の検索流入を狙う。
# 最初にマッチした1タグのみ付与（多重タグで雑多な印象にしない）。
# 並び順＝優先度: より具体的なもの（ポケカ > ポケモン）を上に。
IP_HASHTAGS = [
    (["鬼滅の刃", "鬼滅"],                      "#鬼滅の刃"),
    (["ONE PIECE", "ワンピース", "OP-"],        "#ワンピース"),
    (["ポケモンカード", "ポケカ"],              "#ポケモンカード"),
    (["ポケットモンスター", "ポケモン"],        "#ポケモン"),
    (["呪術廻戦"],                              "#呪術廻戦"),
    (["推しの子"],                              "#推しの子"),
    (["ちいかわ"],                              "#ちいかわ"),
    (["ドラゴンボール"],                        "#ドラゴンボール"),
    (["SPY×FAMILY", "スパイファミリー"],        "#SPYFAMILY"),
    (["NARUTO", "ナルト"],                      "#NARUTO"),
    (["Switch2", "Nintendo Switch"],            "#NintendoSwitch"),
    (["PlayStation5", "PS5"],                   "#PS5"),
    (["iPhone"],                                "#iPhone"),
    (["iPad"],                                  "#iPad"),
    (["AirPods"],                               "#AirPods"),
    (["遊戯王"],                                "#遊戯王"),
]


# ── ユーティリティ ─────────────────────────────────────────────────────────────

def strip_name_prefix(name: str) -> str:
    """商品名の冒頭に連続する【...】プレフィックスを除去する。

    例: 「【新品未開封】【楽天ブックス限定配送BOX】鬼滅の刃 …」
        → 「鬼滅の刃 …」

    全角【】・半角[]・角括弧［］のいずれにも対応。
    剥がし過ぎて空になる事故を避けるため、最終的に空文字になったら
    元の名前を尊重する運用にする（呼び出し側でフォールバック）。
    """
    pattern = re.compile(r'^[【［\[][^】］\]]*[】］\]]\s*')
    while True:
        m = pattern.match(name)
        if not m:
            break
        name = name[m.end():]
    return name.strip()


def detect_ip_hashtag(name: str) -> str:
    """商品名から人気IP/ブランドを検出してハッシュタグを返す。
    該当なしなら空文字。最初にマッチした1件のみ返す。"""
    for keywords, tag in IP_HASHTAGS:
        if any(kw in name for kw in keywords):
            return tag
    return ""


def is_rakuten_books(url: str) -> bool:
    """商品URLが楽天ブックスのものか判定する。
    楽天ブックスは独自ドメイン（books.rakuten.co.jp）と
    item.rakuten.co.jp/book/ 配下の2パターンがある。
    楽天ブックスで1回3,000円以上購入すると SPU+0.5% が効くため、
    ランキングツイートで店舗キーワードを強調する価値がある。"""
    if not url:
        return False
    u = url.lower()
    return ("books.rakuten.co.jp" in u) or ("item.rakuten.co.jp/book/" in u)


# 在庫あり判定（肯定的シグナル）：商品ページに購入導線が存在すれば在庫ありとみなす
# 楽天市場の商品ページは在庫がある時のみ「カートに入れる」「ご購入手続きへ」ボタンが表示される
IN_STOCK_INDICATORS = [
    "カートに入れる",
    "ご購入手続きへ",
    "購入手続きへ",
    "買い物かごに入れる",
]

# 売り切れ判定（否定的シグナル）：在庫表示が明確に売り切れになっているケース
# 注: ページ全体にこれらの文言があるだけでは判定しない。「カートに入れる」が無い時のみ参照
SOLD_OUT_INDICATORS = [
    "この商品は売り切れました",
    "販売を終了しました",
    "販売終了しました",
    "現在お取り扱いできません",
    "入荷お待ち",
    "再入荷お待ち",
]


def is_in_stock(url: str, timeout: int = 10):
    """商品ページを取得して在庫があるか判定する。

    判定ロジック（肯定的シグナル優先）:
      1. 「カートに入れる」等の購入ボタンが存在 → 在庫あり（確定）
      2. 購入ボタンなし & 明確な売り切れ文言あり → 売り切れ
      3. どちらも判定できない → 在庫ありとみなす（楽観・機会損失防止）

    戻り値:
      True  = 在庫あり（楽観的に True を返す）
      False = 明確に売り切れ
      None  = ページ取得失敗
    """
    if not url or 'rakuten' not in url.lower():
        return True  # 楽天以外は判定不能 → 楽観的に true

    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        ),
        'Accept-Language': 'ja,en;q=0.9',
    }
    try:
        r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        if r.status_code != 200:
            return None  # 404 など → 判定不能（呼び出し側で楽観扱い）
        text = r.text
    except Exception as e:
        print(f"    ⚠️ 在庫チェック取得失敗: {e}", file=sys.stderr)
        return None

    # ① 購入ボタンの存在で「在庫あり」を確定判定（最優先）
    if any(kw in text for kw in IN_STOCK_INDICATORS):
        return True

    # ② 購入ボタンが無い & 明確な売り切れ文言がある場合のみ「売り切れ」確定
    if any(kw in text for kw in SOLD_OUT_INDICATORS):
        print(f"    ✗ 売り切れ確定（購入導線なし）")
        return False

    # ③ どちらも判定できない（カート系UIが特殊な店舗等）→ 楽観扱い
    print(f"    ? 在庫判定不能 → 楽観的に在庫ありとみなす")
    return True


def pick_in_stock_item(candidates: list):
    """候補リストの先頭から順に在庫チェックを行い、最初の在庫ありアイテムを返す。
    全て売り切れなら None を返す。ページ取得失敗（None）は「在庫あり扱い」にして
    ツイート機会を逃さない（楽観側）。"""
    for item in candidates:
        print(f"  📦 在庫チェック: {item['name'][:30]}...")
        status = is_in_stock(item.get('url', ''))
        if status is False:
            print(f"    → スキップ（売り切れ）")
            continue
        print(f"    → {'在庫あり' if status else '判定不能・在庫ありとみなす'}")
        return item
    return None


RAKUTEN_AFFILIATE_ID = "1c52abea.36641b1e.1c52abeb.f5f67f16"


def add_affiliate(url: str) -> str:
    """楽天URLを公式アフィリエイトハブ経由のURLに変換する。
    imaraku.html の aff() と同じ形式で、@ima_raku_entry のアフィリエイト
    アカウントにクリックを帰属させる。
    """
    if not url or 'rakuten' not in url:
        return url
    # 既に hb.afl 経由の URL なら二重ラップしない
    if 'hb.afl.rakuten.co.jp' in url:
        return url
    # a.r10.to 短縮URLは内部にアフィリエイトID埋め込み済みなのでそのまま返す
    if 'a.r10.to' in url:
        return url
    encoded = quote(url, safe='')
    return f"https://hb.afl.rakuten.co.jp/hgc/{RAKUTEN_AFFILIATE_ID}/?pc={encoded}&m={encoded}"


def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {"items": [], "regular_index": 0, "last_regular_date": ""}


def save_cache(cache: dict):
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _post_once(text: str) -> tuple[bool, int]:
    auth = OAuth1(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
    resp = requests.post(
        "https://api.twitter.com/2/tweets",
        auth=auth,
        json={"text": text},
        headers={"Content-Type": "application/json"},
    )
    if resp.status_code == 201:
        print(f"✅ 投稿成功: {resp.json()['data']['id']}")
        return True, 201
    print(f"❌ 投稿失敗: {resp.status_code} {resp.text}", file=sys.stderr)
    return False, resp.status_code


# imaraku.github.io URL の reputation 回復ガード（2026-05-22〜23 連続 403 経緯）。
# 6/1 までは事前削除、以降は試行 → 403 なら fallback。daily-tweet と同期。
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


# ── ランキング取得 ─────────────────────────────────────────────────────────────

def fetch_ranking_via_api(pages: list = None, period: str = "realtime") -> list[dict]:
    """楽天ランキングAPI を 総合・男性・女性 × 指定ページ数で取得し合算する。

    pages: 取得するページ番号リスト。デフォルト [1]（=各軸 TOP30、計90件）。
           [1, 2, 3, 4] で各軸 TOP120 まで深掘り。
    period: "realtime" がデフォルト。リアルタイムは pagination 非対応のため
            page>1 を渡すと 400 になる → step.2 の深掘り時は "daily" を指定する。
    新API（openapi.rakuten.co.jp）は applicationId + accessKey + Origin が必須。
    """
    if pages is None:
        pages = [1]
    if not RAKUTEN_APP_ID or not RAKUTEN_ACCESS_KEY:
        return []
    url = "https://openapi.rakuten.co.jp/ichibaranking/api/IchibaItem/Ranking/20220601"
    headers = {"Origin": RAKUTEN_ORIGIN}
    # 取得軸: (ラベル, クエリ追加項目)
    # ※ 2026-05-12 にRakuten API側で validation が厳格化:
    #    - genreId と sex を同時に渡すと 400
    #    - sex は 0 か 1 のみ受け付け (0=男性, 1=女性)
    #    - sex+age 組み合わせは realtime にはデータが存在せず 404 ("DataNotFound")
    #    → sex/age 軸は諦め、ジャンル別 realtime ランキングを並列取得して
    #      レア検出範囲を広げる方針へ転換（2026-05-20改修）。
    #
    # 【ジャンル選定の狙い】
    # 総合 TOP30 は楽天全体のトラフィックが集中して "上位=即売り切れ" になりやすい。
    # カテゴリ別ランキングは細分化されてるので、ポケカ/Snow Man/ONE PIECE 系の
    # ヒット商品が「ジャンル内 TOP10-30」に来た段階で = まだ在庫がある段階で
    # 拾える期待値が高い（在庫切れツイートで読者を失望させないため）。
    axes = [
        ("総合",        {"genreId": 0}),       # 楽天市場全体
        ("おもちゃ",    {"genreId": 562637}),  # ポケカ・たまごっち・ドロップシール・キャラグッズ
        ("CD/DVD",      {"genreId": 101240}),  # Snow Man/アイドル/邦楽
        ("本雑誌",      {"genreId": 101266}),  # ONE PIECE magazine / 漫画 / アイドル写真集 等（200163は誤り→パソコン関連だった）
        ("テレビ家電",  {"genreId": 200162}),  # Switch ソフト・新作ガジェット
        ("食品",        {"genreId": 100533}),  # 限定スイーツ・コラボ食品
    ]
    seen_urls = set()
    items = []
    for label, axis_params in axes:
        per_axis = 0
        for page in pages:
            params = {
                "format": "json",
                "applicationId": RAKUTEN_APP_ID,
                "accessKey": RAKUTEN_ACCESS_KEY,
                "period": period,
                "hits": 20,  # 楽天ランキングAPI（realtime）は hits 上限 20。30 を渡すと 400 になる
            }
            params.update(axis_params)
            # realtime は page 渡すと 400。1ページ目はキーごと省略する。
            if page > 1:
                params["page"] = page
            try:
                r = requests.get(url, params=params, headers=headers, timeout=20)
                if r.status_code != 200:
                    print(f"  ⚠️ ランキング({label} {period} p{page}) 取得エラー: {r.status_code} body={r.text[:250]}", file=sys.stderr)
                    continue
                data = r.json()
            except Exception as e:
                print(f"  ⚠️ ランキング({label} {period} p{page}) 取得失敗: {e}", file=sys.stderr)
                continue

            for entry in data.get("Items", []):
                it = entry.get("Item", {})
                name = (it.get("itemName") or "").strip()
                item_url = (it.get("itemUrl") or "").strip()
                if not name or not item_url:
                    continue
                normalized = item_url.split('?')[0]
                if normalized in seen_urls:
                    continue
                seen_urls.add(normalized)
                items.append({"name": name[:80], "url": add_affiliate(item_url)})
                per_axis += 1
        print(f"  API取得({label} {period}): +{per_axis} 件")
    print(f"  API取得 合計: {len(items)} 件（ユニーク, period={period}, pages={pages}）")
    return items


def fetch_ranking() -> list[dict]:
    """ランキング取得。API が使えればそれを優先、ダメならスクレイピングへフォールバック。

    【TOP100 拡張試行の経緯 2026-05-23】
    相棒の依頼「100位まで範囲を広げたい」を受けて、レガシーAPI
    (app.rakuten.co.jp/services/api/IchibaItem/Ranking/20170628) で daily + page1-3
    の深掘りを試したが、全 6 ジャンルが `specify valid applicationId` で 400 エラー。
    楽天が新規 applicationId を旧 API で受け付けない仕様変更を行ったため使えない。
    新 API (openapi.rakuten.co.jp/ichibaranking) は realtime 専用かつ pagination 非対応。

    結論: 現状の 6ジャンル realtime ランキング = 各 28-30 件 = 合計 ~170 件 が上限。
    十分広い網が張れているのでこれで運用継続。
    """
    api_items = fetch_ranking_via_api()
    if api_items:
        return api_items

    if not RAKUTEN_APP_ID:
        print("  ℹ️  RAKUTEN_APP_ID 未設定: スクレイピングを試行（現状 403 で失敗する可能性大）")

    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        )
    }
    try:
        resp = requests.get(RANKING_BASE, headers=headers, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"⚠️ ランキングページ取得失敗: {e}", file=sys.stderr)
        return []

    soup = BeautifulSoup(resp.text, 'html.parser')
    items = []

    # 複数セレクターで柔軟に対応
    selectors = [
        'li.rankingItem',
        '.rnk-item',
        '[class*="ranking-item"]',
        '[class*="rankItem"]',
        '.item-box',
    ]
    elements = []
    for sel in selectors:
        elements = soup.select(sel)
        if elements:
            print(f"  セレクター '{sel}' でアイテム {len(elements)} 件取得")
            break

    # セレクターで取れない場合はリンクから商品URLを探す
    if not elements:
        print("  セレクター不一致、リンクから商品を探します...")
        links = soup.find_all('a', href=True)
        for a in links:
            href = a['href']
            if 'item.rakuten.co.jp' in href or 'rakuten.co.jp/gold' in href:
                name = a.get_text(strip=True)
                if name and len(name) > 4:
                    items.append({"name": name[:80], "url": add_affiliate(href)})
                    if len(items) >= 20:
                        break
        return items

    for el in elements[:20]:
        # 商品名を取得
        name_el = el.select_one(
            '.itemName, .item-name, [class*="name"], a'
        )
        name = name_el.get_text(strip=True) if name_el else el.get_text(strip=True)
        name = name[:80].strip()

        # 商品URLを取得
        link_el = el.select_one('a[href]')
        url = ""
        if link_el:
            url = link_el.get('href', '')
            if url.startswith('/'):
                url = 'https://ranking.rakuten.co.jp' + url
            url = add_affiliate(url)

        if name:
            items.append({"name": name, "url": url})

    return items


# ── ツイート文 生成 ─────────────────────────────────────────────────────────────

def tweet_rare_item(items: list) -> str:
    """レアアイテム新規ランクインのツイートを生成する。

    ・冒頭の【...】プレフィックスを剥がして本題（鬼滅の刃/ワンピース等）を前面に
    ・人気IPを検出したら専用ハッシュタグを追加してファン層の検索流入を狙う
    ・楽天ブックス商品は「楽天ブックスで」本文＋#楽天ブックス タグ＋SPU+0.5%特典訴求
    ・40字で切り詰め、280字に収まるようベースタグ数を調整
    """
    top = items[0]
    raw_name = top['name']
    item_url = top['url'] or RANKING_URL

    # ① 冒頭の【新品未開封】【楽天ブックス限定配送BOX】… を剥がす
    cleaned = strip_name_prefix(raw_name)
    # 剥がし過ぎて空になったら元の名前にフォールバック
    name = cleaned if cleaned else raw_name

    # ② IP検出は "剥がす前" の生データで走査（プレフィックスにヒントがあるケースも拾う）
    ip_tag = detect_ip_hashtag(raw_name)

    # ③ 楽天ブックス判定（SPU+0.5%のメリットを訴求）
    books = is_rakuten_books(top.get('url', ''))

    # ④ 切り詰め：楽天ブックス版は「📚 楽天ブックスで」分だけ短めに
    name_cap = 35 if books else 40
    if len(name) > name_cap:
        name = name[:name_cap - 2] + "…"

    # ⑤ タグ数調整：books+ip両方あるとタグが重くなるので段階的に削る
    if books and ip_tag:
        base_max = 1
    elif books or ip_tag:
        base_max = 2
    else:
        base_max = 3
    base_tags = hashtags(['core', 'ranking', 'poikatsu'], max_tags=base_max)
    tag_parts = []
    if books:
        tag_parts.append("#楽天ブックス")
    if ip_tag:
        tag_parts.append(ip_tag)
    tag_parts.append(base_tags)
    tag_line = " ".join(tag_parts)

    # ⑥ 本文：商品 URL 1本のみに集約（相棒の意向 2026-05-23）。
    # 以前は ▶商品 と ▶エントリー の 2URL 構成だったが、本筋は商品紹介なので
    # 商品 URL に絞って読者を迷わせない（imaraku URL は副次経路でフォロー獲得を狙う）。
    if books:
        body = (
            f"🚨 楽天ランキングに急上昇！\n"
            f"📚 楽天ブックスで「{name}」\n"
            "\n"
            "人気アイテムはすぐ売り切れも💦\n"
            "💡3,000円以上でSPU+0.5%🎁\n"
            "\n"
            f"▶ 商品\n{item_url}\n"
            f" {tag_line}"
        )
    else:
        body = (
            f"🚨 楽天ランキングに急上昇！\n"
            f"「{name}」\n"
            "\n"
            "人気アイテムはすぐ売り切れも💦\n"
            "気になる方はお早めに✨\n"
            "\n"
            f"▶ 商品\n{item_url}\n"
            f" {tag_line}"
        )
    return body


# ── メイン ────────────────────────────────────────────────────────────────────

def main():
    now = datetime.datetime.now(JST)
    today_str = now.strftime('%Y-%m-%d')
    weekday = now.weekday()  # 0=月 … 6=日

    print(f"=== ランキングチェック {now.strftime('%Y-%m-%d %H:%M JST')} ===")

    # 【2026-05-23】 daily-tweet 減量の補填として5月だけ ranking-check を 1.5倍 fire。
    # cron は常時 JST 9,12,15,18,20,22 の 6 fire/日 だが、6月以降は 9時/15時 fire を
    # スクリプト側で skip して原来の 4 fire/日 (12,18,20,22) に戻す。
    # ※ 手動 dispatch (workflow_dispatch) や schedule = "Scheduled" は両方とも skip対象
    EXTRA_FIRE_HOURS = {9, 15}  # 5月だけ有効な追加fire
    if now.month != 5 and now.hour in EXTRA_FIRE_HOURS:
        print(f"  通常月の追加fire時間外 ({now.hour}時) → スキップ")
        return

    cache = load_cache()
    prev_names = set(cache.get("items", []))
    regular_index = cache.get("regular_index", 0)
    last_regular_date = cache.get("last_regular_date", "")

    # ① ランキング取得 → レアアイテム検出（失敗しても定期ツイートは続行）
    ranking_items = fetch_ranking()
    current_names = [item['name'] for item in ranking_items]

    if not ranking_items:
        print("⚠️ ランキングアイテム取得できず、レアアイテムチェックをスキップ")
    else:
        print(f"  取得アイテム数: {len(ranking_items)}")
        for i, item in enumerate(ranking_items[:5]):
            print(f"  {i+1}. {item['name']}")

        # 新規ランクイン（レアアイテム）検出 → 即ツイート
        # ※ 初回実行（キャッシュ空）は全件が"新規"扱いになるため、誤ツイートを避けてスキップ
        if not prev_names:
            print("  初回実行（キャッシュ空）のため、レアアイテム検出はスキップ")
        else:
            def detect_rare(items_pool):
                new_items = [i for i in items_pool if i['name'] not in prev_names]
                return [
                    i for i in new_items
                    if any(kw in i['name'] for kw in RARE_KEYWORDS)
                ]

            # step.1: 現状ロジック（各軸TOP30＝最大90件）で検出
            rare_new = detect_rare(ranking_items)

            # step.2 (旧深掘り) は廃止: openapi.rakuten.co.jp の Ranking API は realtime 専用で、
            # period=daily/weekly/monthly はすべて 400 "set period from realtime" を返す。
            # realtime は pagination もサポートしないため、TOP30（総合 hits=20×実質1ページ）が上限。
            # 代替案として将来 app.rakuten.co.jp/services/api/IchibaItem/Search で keyword 検索する
            # 案もあるが、リアルタイム性が落ちるので current run の総合TOP30で十分とする。

            if rare_new:
                print(f"  🚨 レアアイテム新規ランクイン候補: {[i['name'] for i in rare_new]}")
                # 売り切れ商品を紹介しても読者が失望するだけなので、在庫確認して最初の在庫ありを選ぶ
                in_stock = pick_in_stock_item(rare_new)
                if in_stock:
                    tweet = tweet_rare_item([in_stock])
                    print(f"\n投稿内容（レアアイテム・在庫あり）:\n{tweet}\n")
                    post_tweet(tweet)
                else:
                    print("  全て売り切れのため、ツイートを見送り")
            else:
                print("  step.1/step.2 ともに新規レアアイテムなし")

    # ② 定期ツイート（日曜以外の週6日 かつ 今日まだ投稿していない場合）
    # ※ ランキング取得の成否に関わらず実行する
    # 日曜は基本 post_daily_tweet.py 側のNIKE特集ツイートと住み分けで休み
    # ただし マラソン期間中の日曜は、お祭り騒ぎなので定期ツイートも発射する
    # （アクセスが集中して普段と違う商品がランクインしやすいため情報価値が高い）
    marathon_active = False
    try:
        if os.path.exists("campaign_status.json"):
            with open("campaign_status.json", encoding='utf-8') as f:
                marathon_active = bool(json.load(f).get("marathon", False))
    except Exception as e:
        print(f"  ⚠️ campaign_status.json 読み取り失敗: {e}", file=sys.stderr)

    allowed_weekdays = [0, 1, 2, 3, 4, 5, 6] if marathon_active else [0, 1, 2, 3, 4, 5]

    # プライムタイム・ゲート：人が楽天で買い物しつつXを見てる時間帯（17:00-22:59 JST）に集中投下する。
    # 深夜帯（0/3時）に定期ツイートが飛んでしまう問題の対策でもある。
    # ただし 22:00 の run まで投稿できてなかった場合は、翌日持ち越しを避けるため最後の保険として投げる。
    hour = now.hour
    in_prime_time = 17 <= hour <= 22
    is_last_chance = hour == 22   # 22時の run = 本日最後の機会

    should_post_regular = (
        weekday in allowed_weekdays
        and last_regular_date != today_str
        and (in_prime_time or is_last_chance)
    )

    if should_post_regular:
        entry = REGULAR_TWEETS[regular_index % len(REGULAR_TWEETS)]
        tweet = build_regular_tweet(entry)
        print(f"\n投稿内容（定期・{entry['name']}）:\n{tweet}\n")
        post_tweet(tweet)
        regular_index += 1
        cache["last_regular_date"] = today_str
        cache["regular_index"] = regular_index
    else:
        reason = []
        if weekday not in allowed_weekdays:
            reason.append(f"weekday={weekday}非対象")
        if last_regular_date == today_str:
            reason.append("本日投稿済")
        if not in_prime_time:
            reason.append(f"プライムタイム外({hour}時)")
        print(f"  定期ツイートはスキップ（{' / '.join(reason) or '条件未達'}）")

    # キャッシュ更新（ランキング取得できた場合のみアイテムリストを更新）
    if current_names:
        cache["items"] = current_names
    save_cache(cache)
    print("✅ キャッシュを更新しました")


if __name__ == "__main__":
    main()
