#!/usr/bin/env python3
"""
check_campaigns.py
GitHub Actions から 2 時間ごとに実行。

【出力ファイル】
  imaraku/campaign_status.json   … 各キャンペーンの開催状況（true/false）
  imaraku/new_campaigns.json     … 既存リストにない新キャンペーン候補

HTML ファイルはこれらの JSON をページ読み込み時に動的取得するため、
HTML 自体を書き換える必要がなくなりました。
"""

import json
import os
import re
import sys
from urllib.parse import urlparse

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

STATUS_JSON  = "campaign_status.json"
NEW_JSON     = "new_campaigns.json"

# ─── 既知キャンペーン定義 ─────────────────────────────────────────────────
# key        : campaign_status.json のキー（HTML の CAMPAIGN_STATUS と一致）
# url        : チェック対象ページ
# end_kw     : 終了と判定するキーワード
# active_kw  : 開催中と判定するキーワード
# default    : 取得失敗時のデフォルト
CAMPAIGNS = [
    {
        "key": "marathon",
        "url": "https://event.rakuten.co.jp/campaign/point-up/marathon/",
        "end_kw":    ["終了しました", "キャンペーンは終了", "受付終了"],
        "active_kw": ["エントリーする", "エントリー受付中", "買いまわり", "マラソン開催中", "もうすぐスタート", "事前エントリー"],
        "default": False,
    },
    {
        # ポイントアップ期間（実際に買いまわりでポイントが上がる期間）
        # エントリー期間のみのときは false、ポイントアップ開始後は true
        "key": "marathon_pointup",
        "url": "https://event.rakuten.co.jp/campaign/point-up/marathon/",
        "end_kw":    ["もうすぐスタート", "事前エントリー", "終了しました", "受付終了"],
        "active_kw": ["開催中", "買いまわり中", "ポイントアップ期間"],
        "default": False,
    },
    {
        "key": "eagles",
        "url": "https://event.rakuten.co.jp/campaign/sports/",
        "end_kw":    ["終了しました", "キャンペーンは終了", "受付終了"],
        "active_kw": ["EAGLES", "イーグルス"],
        "default": False,
    },
    {
        "key": "vissel",
        "url": "https://event.rakuten.co.jp/campaign/sports/",
        "end_kw":    ["終了しました", "キャンペーンは終了", "受付終了"],
        "active_kw": ["VISSEL", "ヴィッセル"],
        "default": False,
    },
    {
        "key": "biccamera",
        "url": "https://biccamera.rakuten.co.jp/c/campaign/megabic/",
        "end_kw":    ["終了しました", "キャンペーンは終了", "受付終了"],
        "active_kw": ["エントリーする", "エントリー受付中", "MegaBIC", "ポイントアップ"],
        "default": True,
    },
    {
        "key": "superdeal",
        "url": "https://event.rakuten.co.jp/superdeal/campaign/superdealdays/",
        "end_kw":    ["終了しました", "キャンペーンは終了", "受付終了"],
        "active_kw": ["エントリーする", "エントリー受付中", "スーパーDEAL", "ポイントバック"],
        "default": True,
    },
    {
        "key": "returnpurchaser",
        "url": "https://event.rakuten.co.jp/campaign/returnpurchaser/",
        "end_kw":    ["終了しました", "キャンペーンは終了", "受付終了"],
        "active_kw": ["エントリーする", "クーポン", "久しぶり"],
        "default": True,
    },
    {
        "key": "newpurchaser",
        "url": "https://event.rakuten.co.jp/campaign/newpurchaser/",
        "end_kw":    ["終了しました", "キャンペーンは終了", "受付終了"],
        "active_kw": ["エントリーする", "クーポン", "はじめて"],
        "default": True,
    },
    {
        "key": "adidas",
        "url": "https://www.rakuten.ne.jp/gold/adidas/adidasdays/",
        "end_kw":    ["終了しました", "キャンペーンは終了", "受付終了", "セールは終了"],
        "active_kw": ["SALE", "セール", "50%", "40%", "30%", "20%", "OFF", "off"],
        "default": False,
    },
    {
        "key": "nike",
        "url": "https://item.rakuten.co.jp/nike-official/c/0000000172/",
        "end_kw":    ["終了しました", "キャンペーンは終了", "セールは終了"],
        "active_kw": ["SALE", "セール", "60%", "50%", "40%", "30%", "OFF", "off"],
        "default": False,
    },
    {
        "key": "mobilebonus",
        "url": "https://network.mobile.rakuten.co.jp/lp/link/event/20260404/",
        "end_kw":    ["終了しました", "キャンペーンは終了", "受付終了", "ページが見つかりません", "404"],
        "active_kw": ["エントリー", "ポイント", "+2倍", "2倍", "開催中", "キャンペーン"],
        "default": False,
    },
    {
        # マラソン内サブキャンペーン：リピート購入+1倍
        # マラソンページにリピート購入の記載があるときのみ true
        "key": "repeat_purchase",
        "url": "https://event.rakuten.co.jp/campaign/point-up/marathon/",
        "end_kw":    ["終了しました", "キャンペーンは終了", "受付終了"],
        "active_kw": ["リピート購入", "リピートボーナス", "リピート＋1倍", "リピート+1倍"],
        "default": False,
    },
    {
        # マラソン内ゲリラキャンペーン：(ゲリラ)全店+1倍
        # 性質上の自動検出は困難。ゲリラ開催日のみマラソンページに文言が出ることがある
        "key": "guerrilla",
        "url": "https://event.rakuten.co.jp/campaign/point-up/marathon/",
        "end_kw":    ["終了しました", "キャンペーンは終了", "受付終了"],
        "active_kw": ["ゲリラ", "全店＋1倍", "全店+1倍", "ゲリラキャンペーン"],
        "default": False,
    },
    {
        # スーパーDEAL 4時間限定ポイントバック
        "key": "superdeal_4h",
        "url": "https://event.rakuten.co.jp/superdeal/campaign/pointback10/",
        "end_kw":    ["終了しました", "キャンペーンは終了", "受付終了"],
        "active_kw": ["エントリーする", "エントリー受付中", "ポイントバック", "4時間", "+10%", "10%バック"],
        "default": False,
    },
    {
        # 楽天モバイル×スーパーDEAL +10%
        "key": "mobiledeal",
        "url": "https://event.rakuten.co.jp/superdeal/campaign/mobiledeal/20260404/",
        "end_kw":    ["終了しました", "キャンペーンは終了", "受付終了", "ページが見つかりません"],
        "active_kw": ["エントリーする", "エントリー受付中", "モバイル", "+10%", "10%"],
        "default": False,
    },
]

# ─── 新キャンペーン自動検出：スキャン対象ページ ──────────────────────────
# これらのページから <a href="..."> を収集し、
# KNOWN_URLS にない楽天キャンペーンURLを new_campaigns.json に追記する
SCAN_PAGES = [
    "https://www.rakuten.co.jp/",                      # 楽天市場トップ
    "https://event.rakuten.co.jp/",                    # イベントトップ
    "https://event.rakuten.co.jp/campaign/point-up/",  # ポイントアップ一覧
]

# 既知URLのパターン（これに含まれるURLは「新規」扱いしない）
KNOWN_URL_PATTERNS = [c["url"] for c in CAMPAIGNS] + [
    "toolbar.rakuten.co.jp",
    "biccamera.rakuten.co.jp",
    "superdeal/campaign/superdealdays",
    "superdeal/campaign/overseas",
    "event.rakuten.co.jp/card/pointday",
    "event.rakuten.co.jp/campaign/point-up/wonderful-day",
    "event.rakuten.co.jp/campaign/point-up/ichiba-day",
    "books.rakuten.co.jp",
    "brandavenue.rakuten.co.jp",
    "beauty.rakuten.co.jp",
    "event.rakuten.co.jp/genre/daily",
    "event.rakuten.co.jp/brand/",
    "event.rakuten.co.jp/drink/",
    "event.rakuten.co.jp/fashion/",
    "event.rakuten.co.jp/medicine/",
    "event.rakuten.co.jp/season/",
    "24.rakuten.co.jp",
    "point.rakuten.co.jp",
    "event.rakuten.co.jp/overseas/",
    "event.rakuten.co.jp/beauty/",
    "event.rakuten.co.jp/young/",
    "event.rakuten.co.jp/auto/",
    "event.rakuten.co.jp/superdeal/campaign/megadeal",
    "event.rakuten.co.jp/superdeal/campaign/pointback10",
    "event.rakuten.co.jp/superdeal/campaign/mobiledeal",
    "event.rakuten.co.jp/incentive/",
    "event.rakuten.co.jp/family/",
    "event.rakuten.co.jp/guide/",
]

# 新キャンペーンとして検出する URL パターン（楽天エントリー系）
NEW_CAMPAIGN_URL_RE = re.compile(
    r'https://event\.rakuten\.co\.jp/(?:campaign|genre|coupon|superdeal/campaign)/[^"\'>\s]+'
)

# キャンペーン名を URL から推定する
ENTRY_KEYWORD_RE = re.compile(r'エントリー|ポイントアップ|クーポン|特典|キャンペーン')


# ─── ユーティリティ ───────────────────────────────────────────────────────

# 同一URLの二重フェッチを防ぐキャッシュ
_page_cache: dict[str, str | None] = {}


def fetch(url: str, timeout: int = 15) -> str | None:
    if url in _page_cache:
        return _page_cache[url]
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        result = r.text
    except Exception as e:
        print(f"  ⚠️  取得失敗 {url}: {e}", file=sys.stderr)
        result = None
    _page_cache[url] = result
    return result


def check_campaign(camp: dict) -> bool:
    text = fetch(camp["url"])
    if text is None:
        print(f"  [{camp['key']}] → フォールバック: {camp['default']}")
        return camp["default"]
    for kw in camp["end_kw"]:
        if kw in text:
            print(f"  [{camp['key']}] ✗ 終了: 「{kw}」")
            return False
    for kw in camp["active_kw"]:
        if kw in text:
            print(f"  [{camp['key']}] ✓ 開催中: 「{kw}」")
            return True
    print(f"  [{camp['key']}] ? 判定不能 → {camp['default']}")
    return camp["default"]


# ─── 新キャンペーン自動検出 ───────────────────────────────────────────────

def is_known(url: str) -> bool:
    for pattern in KNOWN_URL_PATTERNS:
        if pattern in url:
            return True
    return False


def extract_title_near_link(html: str, url: str) -> str:
    """リンク周辺のテキストからキャンペーン名を推定する（ベストエフォート）。"""
    # URLをエスケープしてその周辺100文字を取得
    escaped = re.escape(url)
    m = re.search(rf'.{{0,200}}{escaped}.{{0,200}}', html, re.DOTALL)
    if not m:
        return url
    snippet = re.sub(r'<[^>]+>', '', m.group())   # タグ除去
    snippet = re.sub(r'\s+', ' ', snippet).strip()
    # 日本語部分を抽出
    jp = re.findall(r'[\u3000-\u9FFF\uFF00-\uFFEF]+', snippet)
    if jp:
        return max(jp, key=len)[:30]
    return urlparse(url).path.strip('/').split('/')[-1]


END_KEYWORDS   = ["終了しました", "キャンペーンは終了", "受付終了", "ページが見つかりません"]
ACTIVE_KEYWORDS = ["エントリーする", "エントリー受付中", "ポイントアップ", "クーポン", "開催中"]


def is_campaign_active(url: str) -> bool:
    """URLにアクセスして、キャンペーンがまだ開催中かを判定する。"""
    page = fetch(url)
    if page is None:
        return True   # 取得失敗時は消さない（安全側）
    if any(kw in page for kw in END_KEYWORDS):
        return False
    if any(kw in page for kw in ACTIVE_KEYWORDS):
        return True
    return True       # 判定不能時も消さない


def purge_ended_campaigns(existing_new: list) -> tuple[list, int]:
    """new_campaigns.json の既存エントリーのうち、終了済みを除去して返す。"""
    active = []
    removed = 0
    for c in existing_new:
        url = c.get("url", "")
        if not url:
            active.append(c)
            continue
        if is_campaign_active(url):
            active.append(c)
        else:
            print(f"  🗑️  終了済みを削除: {c.get('name', url)}")
            removed += 1
    return active, removed


def detect_new_campaigns(existing_new: list) -> list:
    """スキャンページから新しいキャンペーンURLを検出して返す。"""
    existing_urls = {c["url"] for c in existing_new}
    found = []

    for scan_url in SCAN_PAGES:
        print(f"  スキャン: {scan_url}")
        html = fetch(scan_url)
        if not html:
            continue
        urls = NEW_CAMPAIGN_URL_RE.findall(html)
        for url in set(urls):
            # クリーン化（クエリ除去）
            url = url.split('?')[0].rstrip('/')
            if is_known(url):
                continue
            if url in existing_urls:
                continue
            # エントリーページかチェック
            page = fetch(url)
            if page and any(kw in page for kw in ACTIVE_KEYWORDS):
                # 終了済みは除外
                if any(kw in page for kw in END_KEYWORDS):
                    continue
                name = extract_title_near_link(html, url)
                print(f"  🆕 新キャンペーン候補: {name} → {url}")
                found.append({"name": name, "url": url, "point": "要確認", "detected_at": __import__('datetime').date.today().isoformat()})
                existing_urls.add(url)

    return found


# ─── JSON 読み書き ─────────────────────────────────────────────────────────

def load_json(path: str, default):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default


def save_json(path: str, data) -> bool:
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    old = load_json(path, None)
    new_text = json.dumps(data, ensure_ascii=False, indent=2)
    if json.dumps(old, ensure_ascii=False, indent=2) == new_text:
        return False  # 変更なし
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_text)
    return True  # 変更あり


# ─── メイン ───────────────────────────────────────────────────────────────

def main():
    print("=== キャンペーン状態チェック開始 ===\n")

    # 1. 既知キャンペーンの開催状況チェック
    print("── 1. 開催状況チェック ──")
    results = {}
    for camp in CAMPAIGNS:
        results[camp["key"]] = check_campaign(camp)

    print("\n── 結果まとめ ──")
    for key, val in results.items():
        print(f"  {key:<20} {'✓ 開催中' if val else '✗ 終了/非開催'}")

    changed_status = save_json(STATUS_JSON, results)
    print(f"\n{'✅ campaign_status.json を更新' if changed_status else '変更なし（campaign_status.json）'}")

    # 2. 既存の自動検出キャンペーンの終了チェック → 終了済みを削除
    print("\n── 2. 自動検出キャンペーンの終了チェック ──")
    existing_new = load_json(NEW_JSON, [])
    if existing_new:
        existing_new, removed_count = purge_ended_campaigns(existing_new)
        print(f"  終了済み削除: {removed_count} 件 / 残り: {len(existing_new)} 件")
    else:
        removed_count = 0
        print("  自動検出キャンペーンなし")

    # 3. 新キャンペーンの自動検出
    print("\n── 3. 新キャンペーン自動検出 ──")
    new_found = detect_new_campaigns(existing_new)

    all_new = existing_new + new_found
    changed_new = save_json(NEW_JSON, all_new)

    if new_found:
        print(f"✅ new_campaigns.json に {len(new_found)} 件追加")
    elif removed_count > 0:
        print(f"✅ new_campaigns.json から終了済み {removed_count} 件を削除")
    else:
        print("変更なし（new_campaigns.json）")

    # 3. GitHub Actions の outputs に変更有無を出力
    changed = changed_status or changed_new
    env_file = os.environ.get("GITHUB_OUTPUT", "")
    if env_file:
        with open(env_file, "a") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")

    print("\n=== チェック完了 ===")


if __name__ == "__main__":
    main()
