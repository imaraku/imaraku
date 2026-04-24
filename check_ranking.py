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
    # ゲーム機・ソフト関連
    "Nintendo Switch", "Switch2", "PlayStation", "PS5", "Xbox",
    # ポケモン・鬼滅・ジャンプ系人気IP
    "ポケモン", "ポケットモンスター", "鬼滅", "ワンピース", "推しの子",
    "Apple", "iPhone", "iPad", "AirPods", "Meta Quest",
    # トレカ系（ポケカ・遊戯王・MTG 等）
    "ポケカ", "遊戯王", "マジック：ザ・ギャザリング",
    # イベント・抽選系
    "抽選販売", "予約受付", "先行予約",
]

# 常連アイテムのツイートテンプレート（月・水・金でローテーション）
# (本文, ハッシュタグカテゴリ) のタプルで持ち、投稿時にタグを動的生成する
REGULAR_TWEETS = [
    # コンタクトレンズ
    (
        "👁 コンタクトレンズ、楽天で買ってる？\n"
        "\n"
        "実は市販・眼科より楽天市場の方が\n"
        "安いことがほとんど💡\n"
        "ポイントも貯まる＆使えてお得🏆\n"
        "\n"
        f"ランキング👇\n{RANKING_URL}\n"
        f"エントリー👇\n{SITE_URL}",
        ["core", "contact", "poikatsu"],
    ),
    # お水・炭酸水
    (
        "💧 重い飲料こそ楽天で！\n"
        "\n"
        "お水・炭酸水を箱買いしても\n"
        "玄関まで届くから体への負担ゼロ✨\n"
        "スーパーより安く、ポイントも👍\n"
        "\n"
        f"ランキング👇\n{RANKING_URL}\n"
        f"エントリー👇\n{SITE_URL}",
        ["core", "water", "poikatsu"],
    ),
    # ティッシュ・トイレットペーパー
    (
        "🧻 かさばる日用品も楽天にお任せ！\n"
        "\n"
        "ティッシュ・トイレットペーパーは\n"
        "重くてかさばって大変…😅\n"
        "楽天なら玄関まで届きます✨\n"
        "まとめ買いでさらにお得💡\n"
        "\n"
        f"ランキング👇\n{RANKING_URL}\n"
        f"エントリー👇\n{SITE_URL}",
        ["core", "daily", "poikatsu"],
    ),
    # お米
    (
        "🍚 重いお米も楽天でお得に！\n"
        "\n"
        "5kg・10kgのお米を運ぶのは重労働…\n"
        "楽天なら玄関まで届きます🏠\n"
        "ポイントも貯まる＆定期便割引も💡\n"
        "\n"
        f"ランキング👇\n{RANKING_URL}\n"
        f"エントリー👇\n{SITE_URL}",
        ["core", "rice", "poikatsu"],
    ),
    # 洗剤・柔軟剤
    (
        "🫧 洗剤・柔軟剤も楽天でまとめ買い！\n"
        "\n"
        "重くてかさばる洗剤こそ宅配が便利✨\n"
        "ポイントが貯まって\n"
        "スーパーよりお得なことも💡\n"
        "\n"
        f"ランキング👇\n{RANKING_URL}\n"
        f"エントリー👇\n{SITE_URL}",
        ["core", "detergent", "daily"],
    ),
    # ランキング全般
    (
        "🏆 楽天ランキング、チェックしてる？\n"
        "\n"
        "毎日リアルタイムで更新されるから\n"
        "買い物のヒントにもなります🛒\n"
        "エントリー併用でポイント最大化💡\n"
        "\n"
        f"ランキング👇\n{RANKING_URL}\n"
        f"エントリー👇\n{SITE_URL}",
        ["core", "ranking", "poikatsu"],
    ),
]


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


# 売り切れ判定キーワード（商品ページ内にあれば在庫なし扱い）
# 誤検出を避けるため、販売終了が明確な文言のみ厳選
SOLD_OUT_KEYWORDS = [
    "売り切れました",
    "SOLD OUT",
    "在庫切れ",
    "販売を終了",
    "販売終了しました",
    "現在お取り扱いできません",
    "入荷待ち",
    "再入荷をお待ち",
]


def is_in_stock(url: str, timeout: int = 10):
    """商品ページを取得して在庫があるか判定する。
    戻り値:
      True  = 在庫あり（または判定不能 = 安全側）
      False = 明確に売り切れ／販売終了
      None  = ページ取得失敗（判定不能 → 呼び出し側判断）

    ⚠️ 取得失敗時は None を返す。呼び出し側で True（楽観）か False（慎重）を選ぶ。
    """
    if not url or 'rakuten' not in url.lower():
        return True  # 判定不能 → 安全側で true

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
            return None  # 404 など → 判定不能
        text = r.text
    except Exception as e:
        print(f"    ⚠️ 在庫チェック取得失敗: {e}", file=sys.stderr)
        return None

    for kw in SOLD_OUT_KEYWORDS:
        if kw in text:
            print(f"    ✗ 売り切れ検出: 「{kw}」")
            return False
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


def add_affiliate(url: str) -> str:
    """楽天URLにアフィリエイトパラメータを付与する。"""
    if not url or 'rakuten' not in url:
        return url
    sep = '&' if '?' in url else '?'
    return url + sep + 'scid=af_pc_etc&sc2id=af_101_0_0'


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


# ── ランキング取得 ─────────────────────────────────────────────────────────────

def fetch_ranking_via_api() -> list[dict]:
    """楽天ウェブサービス API でランキングを取得する。
    新API（openapi.rakuten.co.jp）は applicationId + accessKey + Origin が必須。"""
    if not RAKUTEN_APP_ID or not RAKUTEN_ACCESS_KEY:
        return []
    url = "https://openapi.rakuten.co.jp/ichibaranking/api/IchibaItem/Ranking/20220601"
    params = {
        "format": "json",
        "applicationId": RAKUTEN_APP_ID,
        "accessKey": RAKUTEN_ACCESS_KEY,
        "genreId": 0,            # 総合ランキング
        "period": "realtime",    # リアルタイム
        "hits": 20,
    }
    headers = {"Origin": RAKUTEN_ORIGIN}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=20)
        if r.status_code != 200:
            print(f"⚠️ 楽天API エラー: {r.status_code} {r.text[:200]}", file=sys.stderr)
            return []
        data = r.json()
    except Exception as e:
        print(f"⚠️ 楽天API 取得失敗: {e}", file=sys.stderr)
        return []

    items = []
    for entry in data.get("Items", []):
        it = entry.get("Item", {})
        name = (it.get("itemName") or "").strip()
        url  = add_affiliate(it.get("itemUrl") or "")
        if name:
            items.append({"name": name[:80], "url": url})
    print(f"  API取得: {len(items)} 件")
    return items


def fetch_ranking() -> list[dict]:
    """ランキング取得。API が使えればそれを優先、ダメならスクレイピングへフォールバック。"""
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

    # ⑥ 本文：楽天ブックスなら SPU+0.5% 訴求に差し替え
    if books:
        body = (
            f"🚨 楽天ランキングに急上昇！\n"
            f"📚 楽天ブックスで「{name}」\n"
            "\n"
            "人気アイテムはすぐ売り切れも😰\n"
            "💡3,000円以上でSPU+0.5%🎁\n"
            "\n"
            f"▶ 商品\n{item_url}\n"
            f"▶ エントリー\n{SITE_URL}\n"
            f" {tag_line}"
        )
    else:
        body = (
            f"🚨 楽天ランキングに急上昇！\n"
            f"「{name}」\n"
            "\n"
            "人気アイテムはすぐ売り切れも😰\n"
            "気になる方はお早めに✨\n"
            "\n"
            f"▶ 商品\n{item_url}\n"
            f"▶ エントリー\n{SITE_URL}\n"
            f" {tag_line}"
        )
    return body


# ── メイン ────────────────────────────────────────────────────────────────────

def main():
    now = datetime.datetime.now(JST)
    today_str = now.strftime('%Y-%m-%d')
    weekday = now.weekday()  # 0=月 … 6=日

    print(f"=== ランキングチェック {now.strftime('%Y-%m-%d %H:%M JST')} ===")

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
            new_items = [i for i in ranking_items if i['name'] not in prev_names]
            rare_new = [
                i for i in new_items
                if any(kw in i['name'] for kw in RARE_KEYWORDS)
            ]

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
                print("  新規レアアイテムなし")

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
        body, tag_categories = REGULAR_TWEETS[regular_index % len(REGULAR_TWEETS)]
        tweet = body + "\n\n" + hashtags(tag_categories)
        print(f"\n投稿内容（定期・常連アイテム）:\n{tweet}\n")
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
