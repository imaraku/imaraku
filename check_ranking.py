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
import sys
import json
import datetime
import requests
from bs4 import BeautifulSoup
from requests_oauthlib import OAuth1

# ── 認証情報 ─────────────────────────────────────────────────────────────────
API_KEY             = os.environ["TWITTER_API_KEY"]
API_SECRET          = os.environ["TWITTER_API_SECRET"]
ACCESS_TOKEN        = os.environ["TWITTER_ACCESS_TOKEN"]
ACCESS_TOKEN_SECRET = os.environ["TWITTER_ACCESS_TOKEN_SECRET"]

# ── 定数 ─────────────────────────────────────────────────────────────────────
JST          = datetime.timezone(datetime.timedelta(hours=9))
RANKING_BASE = "https://ranking.rakuten.co.jp/"
RANKING_URL  = RANKING_BASE + "?scid=af_pc_etc&sc2id=af_101_0_0"
SITE_URL     = "https://imaraku.github.io/imaraku/imaraku.html"
CACHE_FILE   = "ranking_cache.json"

# レアアイテム検出キーワード（新規ランクインしたら即ツイート）
RARE_KEYWORDS = [
    "ゲーム", "ソフト", "Switch", "PlayStation", "PS5", "Xbox",
    "シール", "ステッカー", "ドロップシール", "ボンボン",
    "グッズ", "限定", "新発売", "入荷", "フィギュア", "カード",
]

# 常連アイテムのツイートテンプレート（月・水・金でローテーション）
REGULAR_TWEETS = [
    # コンタクトレンズ
    (
        "👁 コンタクトレンズ、楽天で買ってますか？\n"
        "\n"
        "実は市販・眼科より楽天市場の方が\n"
        "安いことがほとんど💡\n"
        "\n"
        "しかもポイントが貯まる・使える！\n"
        "ランキング上位の常連アイテムです🏆\n"
        "\n"
        f"今日のランキングはこちら👇\n{RANKING_URL}\n"
        "\n"
        f"エントリーを忘れずに👇\n{SITE_URL}\n"
        "\n"
        "#楽天 #コンタクトレンズ #ポイ活 #節約術"
    ),
    # お水・炭酸水
    (
        "💧 重い飲料こそ楽天で！\n"
        "\n"
        "お水・炭酸水を箱買いしても\n"
        "玄関まで届けてくれるので体への負担ゼロ✨\n"
        "\n"
        "スーパーで運ぶより安くてポイントも貯まる👍\n"
        "\n"
        f"ランキングをチェック👇\n{RANKING_URL}\n"
        "\n"
        f"エントリーを忘れずに👇\n{SITE_URL}\n"
        "\n"
        "#楽天 #ミネラルウォーター #炭酸水 #ポイ活 #宅配"
    ),
    # ティッシュ・トイレットペーパー
    (
        "🧻 かさばる日用品も楽天にお任せ！\n"
        "\n"
        "ティッシュ・トイレットペーパーは\n"
        "重くてかさばってスーパーで買うのが大変…😅\n"
        "楽天なら玄関まで届けてくれます✨\n"
        "\n"
        "まとめ買いでさらにお得＆ポイントも貯まる💡\n"
        "\n"
        f"ランキングをチェック👇\n{RANKING_URL}\n"
        "\n"
        f"エントリーを忘れずに👇\n{SITE_URL}\n"
        "\n"
        "#楽天 #日用品 #ポイ活 #宅配 #節約術"
    ),
    # お米
    (
        "🍚 重いお米も楽天でお得に！\n"
        "\n"
        "5kg・10kgのお米をスーパーで運ぶのは重労働…\n"
        "楽天なら玄関まで届けてくれます🏠\n"
        "\n"
        "ポイントも貯まってさらにお得💡\n"
        "定期購入でさらに割引になるショップも！\n"
        "\n"
        f"ランキングをチェック👇\n{RANKING_URL}\n"
        "\n"
        f"エントリーを忘れずに👇\n{SITE_URL}\n"
        "\n"
        "#楽天 #お米 #ポイ活 #宅配 #節約術"
    ),
    # 洗剤・柔軟剤
    (
        "🫧 洗剤・柔軟剤も楽天でまとめ買い！\n"
        "\n"
        "重くてかさばる洗剤類こそ宅配が便利✨\n"
        "楽天市場ならポイントが貯まって\n"
        "スーパーよりお得なことも💡\n"
        "\n"
        f"ランキングをチェック👇\n{RANKING_URL}\n"
        "\n"
        f"エントリーを忘れずに👇\n{SITE_URL}\n"
        "\n"
        "#楽天 #日用品 #洗剤 #ポイ活 #節約術"
    ),
    # ランキング全般
    (
        "🏆 楽天ランキング、チェックしてますか？\n"
        "\n"
        "毎日リアルタイムで更新されるランキングは\n"
        "買い物のヒントにもなります🛒\n"
        "\n"
        "エントリーと合わせてポイント最大化で\n"
        "賢くお買い物しよう💡\n"
        "\n"
        f"今日のランキングはこちら👇\n{RANKING_URL}\n"
        "\n"
        f"エントリーまとめ👇\n{SITE_URL}\n"
        "\n"
        "#楽天 #楽天市場 #ポイ活 #節約術"
    ),
]


# ── ユーティリティ ─────────────────────────────────────────────────────────────

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

def fetch_ranking() -> list[dict]:
    """楽天ランキングページから上位アイテムを取得する。"""
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

def tweet_rare_item(items: list[dict]) -> str:
    """レアアイテム新規ランクインのツイートを生成する。"""
    top = items[0]
    name = top['name']
    item_url = top['url'] or RANKING_URL

    return (
        f"🚨 楽天ランキングに「{name}」が急上昇！\n"
        "\n"
        "人気アイテムはすぐ売り切れることも😰\n"
        "気になる方はお早めに✨\n"
        "\n"
        f"▶ 商品を見る\n{item_url}\n"
        "\n"
        "エントリーしてからお買い物でポイントお得👇\n"
        f"{SITE_URL}\n"
        "\n"
        "#楽天 #楽天市場 #ポイ活 #ランキング"
    )


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
        new_items = [i for i in ranking_items if i['name'] not in prev_names]
        rare_new = [
            i for i in new_items
            if any(kw in i['name'] for kw in RARE_KEYWORDS)
        ]

        if rare_new:
            print(f"  🚨 レアアイテム新規ランクイン: {[i['name'] for i in rare_new]}")
            tweet = tweet_rare_item(rare_new)
            print(f"\n投稿内容（レアアイテム）:\n{tweet}\n")
            post_tweet(tweet)
        else:
            print("  新規レアアイテムなし")

    # ② 定期ツイート（月・水・金 かつ 今日まだ投稿していない場合）
    # ※ ランキング取得の成否に関わらず実行する
    if weekday in [0, 2, 4] and last_regular_date != today_str:
        tweet = REGULAR_TWEETS[regular_index % len(REGULAR_TWEETS)]
        print(f"\n投稿内容（定期・常連アイテム）:\n{tweet}\n")
        post_tweet(tweet)
        regular_index += 1
        cache["last_regular_date"] = today_str
        cache["regular_index"] = regular_index
    else:
        print(f"  定期ツイートはスキップ（weekday={weekday}, last={last_regular_date}）")

    # キャッシュ更新（ランキング取得できた場合のみアイテムリストを更新）
    if current_names:
        cache["items"] = current_names
    save_cache(cache)
    print("✅ キャッシュを更新しました")


if __name__ == "__main__":
    main()
