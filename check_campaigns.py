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

import datetime
import json
import os
import re
import sys
from urllib.parse import urlparse

import requests

JST = datetime.timezone(datetime.timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

STATUS_JSON    = "campaign_status.json"
NEW_JSON       = "new_campaigns.json"
SCHEDULE_JSON  = "marathon_schedule.json"
EXPIRED_JSON   = "expired_entries.json"   # ハードコード済みエントリーのうち終了確定したURL一覧
IMARAKU_HTML   = "imaraku.html"
MARATHON_URL   = "https://event.rakuten.co.jp/campaign/point-up/marathon/"

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
        # 勝利ボーナスの検出は「勝利」「勝ちました」「ポイント2倍エントリー」等の
        # 勝利マーカーが必須。チーム名だけでは常時ページ内に存在するため false 判定。
        "key": "eagles",
        "url": "https://event.rakuten.co.jp/campaign/sports/",
        "end_kw":    ["終了しました", "キャンペーンは終了", "受付終了"],
        "active_kw": ["イーグルス勝利", "EAGLES勝利", "イーグルスが勝ちました",
                      "イーグルス勝ちました", "勝利記念", "W勝利",
                      "EAGLES勝", "イーグルス勝"],
        "default": False,
    },
    {
        "key": "vissel",
        "url": "https://event.rakuten.co.jp/campaign/sports/",
        "end_kw":    ["終了しました", "キャンペーンは終了", "受付終了"],
        "active_kw": ["ヴィッセル勝利", "VISSEL勝利", "ヴィッセルが勝ちました",
                      "ヴィッセル勝ちました", "神戸勝利", "W勝利",
                      "VISSEL勝", "ヴィッセル勝", "神戸勝"],
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
        # SALE/セール等のキーワードはページに常時残ることが多いため、
        # 「開催中」「実施中」と明確に書かれている場合のみ true
        "key": "adidas",
        "url": "https://www.rakuten.ne.jp/gold/adidas/adidasdays/",
        "end_kw":    ["終了しました", "キャンペーンは終了", "受付終了",
                      "セールは終了", "先行セールは終了", "次回セール"],
        "active_kw": ["開催中", "実施中", "SALE開催中", "セール開催中",
                      "セール実施中", "本日最終日"],
        "default": False,
    },
    {
        "key": "nike",
        "url": "https://item.rakuten.co.jp/nike-official/c/0000000172/",
        "end_kw":    ["終了しました", "キャンペーンは終了", "セールは終了"],
        "active_kw": ["開催中", "実施中", "SALE開催中", "セール開催中",
                      "セール実施中", "本日最終日"],
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
    "https://event.rakuten.co.jp/coupon/",             # クーポン特集
    "https://coupon.rakuten.co.jp/",                   # クーポンセンター
    "https://event.rakuten.co.jp/superdeal/",          # スーパーDEAL
    "https://event.rakuten.co.jp/campaign/sale/",      # セール特集
]

# 既知URLのパターン（これに含まれるURLは「新規」扱いしない）
KNOWN_URL_PATTERNS = [c["url"] for c in CAMPAIGNS] + [
    "toolbar.rakuten.co.jp",
    "biccamera.rakuten.co.jp",
    "superdeal/campaign/superdealdays",
    "superdeal/campaign/overseas",
    "event.rakuten.co.jp/card/pointday",
    "event.rakuten.co.jp/campaign/card/pointday",   # 0と5のつく日と重複
    "event.rakuten.co.jp/campaign/sports",          # eagles/vissel と重複
    "event.rakuten.co.jp/campaign/rank",            # ランク特典系（今楽の対象外）
    "event.rakuten.co.jp/genre/school",             # 入園入学シーズン物（恒常的でない）
    "event.rakuten.co.jp/genre/summer",             # シーズン物
    "event.rakuten.co.jp/genre/winter",             # シーズン物
    "event.rakuten.co.jp/genre/spring",             # シーズン物
    "event.rakuten.co.jp/genre/autumn",             # シーズン物
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
# event.rakuten.co.jp の主要セクション + coupon.rakuten.co.jp を網羅
NEW_CAMPAIGN_URL_RE = re.compile(
    r'https://(?:'
    r'event\.rakuten\.co\.jp/(?:campaign|genre|coupon|superdeal/campaign|sale)/[^"\'>\s]+'
    r'|coupon\.rakuten\.co\.jp/[a-zA-Z0-9_\-]+/[^"\'>\s]+'
    r')'
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


# ─── マラソン スケジュール抽出 ─────────────────────────────────────────────
# ページ内テキストから「yyyy年m月d日(曜)hh:mm」や「m月d日hh:mm〜」を探す。
# ポイントアップ期間（例: 4/4 20:00 〜 4/11 01:59）と
# エントリー期間（例: 4/1 10:00 〜 4/11 01:59）の2種類がよくある。

# 「2026年4月4日（土）20:00」または「4月4日(土)20:00」にマッチ
_DATE_RE = re.compile(
    r'(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日'         # 日付
    r'(?:[（(][^）)]{1,3}[）)])?'                   # （土）等 任意
    r'\s*(\d{1,2})[:：](\d{2})'                     # 時刻
)

# 期間表記: 「開始 〜 終了」 (〜や～、-の揺れに対応)
_RANGE_RE = re.compile(
    r'((?:\d{4}年)?\d{1,2}月\d{1,2}日(?:[（(][^）)]{1,3}[）)])?\s*\d{1,2}[:：]\d{2})'
    r'\s*[〜～\-]\s*'
    r'((?:\d{4}年)?\d{1,2}月\d{1,2}日(?:[（(][^）)]{1,3}[）)])?\s*\d{1,2}[:：]\d{2})'
)


def _parse_jst(text: str, fallback_year: int) -> datetime.datetime | None:
    m = _DATE_RE.search(text)
    if not m:
        return None
    year = int(m.group(1)) if m.group(1) else fallback_year
    month, day, hour, minute = int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
    try:
        return datetime.datetime(year, month, day, hour, minute, tzinfo=JST)
    except ValueError:
        return None


def extract_marathon_schedule(html: str) -> dict | None:
    """マラソンページHTMLから開催期間を抽出。見つからなければNone。"""
    # タグ除去してテキスト化
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text)

    now = datetime.datetime.now(JST)
    fallback_year = now.year

    ranges = _RANGE_RE.findall(text)
    if not ranges:
        return None

    # (start_dt, end_dt) のペアを抽出し、未来〜今日の範囲にある最短の期間を採用
    candidates = []
    for start_txt, end_txt in ranges:
        s = _parse_jst(start_txt, fallback_year)
        e = _parse_jst(end_txt, fallback_year)
        if not s or not e:
            continue
        # 年跨ぎ補正: 終了が開始より前なら終了を翌年に
        if e < s:
            e = e.replace(year=e.year + 1)
        # 過去すぎ（30日以上前に終わっている）は除外
        if e < now - datetime.timedelta(days=30):
            continue
        # 未来すぎ（1年以上先）も除外
        if s > now + datetime.timedelta(days=365):
            continue
        candidates.append((s, e))

    if not candidates:
        return None

    # ポイントアップ期間の候補: 開始が20時台（マラソンは通常20:00開始）
    pointup = next(((s, e) for s, e in candidates if s.hour == 20), None)
    # エントリー期間の候補: 開始が10時前後（通常エントリーは10:00開始）かつ pointup と終了時刻が一致
    entry = None
    if pointup:
        entry = next(
            ((s, e) for s, e in candidates if s.hour < 20 and abs((e - pointup[1]).total_seconds()) < 3600),
            None,
        )
    if not pointup:
        # 20時開始が見つからない場合は最初の候補を pointup として扱う
        pointup = candidates[0]

    result = {
        "pointup_start": pointup[0].isoformat(),
        "pointup_end":   pointup[1].isoformat(),
        "entry_start":   entry[0].isoformat() if entry else None,
    }
    return result


def update_marathon_schedule() -> dict:
    """マラソンページから日程を抽出して marathon_schedule.json を更新。
    既存が source='manual' なら上書きしない。"""
    existing = load_json(SCHEDULE_JSON, {})
    if existing.get("source") == "manual" and existing.get("pointup_end"):
        # 手動設定が有効期限内なら触らない
        try:
            end = datetime.datetime.fromisoformat(existing["pointup_end"])
            if end > datetime.datetime.now(JST):
                print("  [schedule] 手動設定を維持（未終了）")
                return existing
        except Exception:
            pass

    html = fetch(MARATHON_URL)
    if not html:
        print("  [schedule] ページ取得失敗 → 既存値維持")
        return existing

    extracted = extract_marathon_schedule(html)
    if not extracted:
        print("  [schedule] 日程の抽出に失敗 → 既存値維持")
        return existing

    new_schedule = {
        "entry_start":   extracted.get("entry_start"),
        "pointup_start": extracted["pointup_start"],
        "pointup_end":   extracted["pointup_end"],
        "source":        "auto",
        "updated_at":    datetime.datetime.now(JST).isoformat(),
    }
    save_json(SCHEDULE_JSON, new_schedule)
    print(f"  [schedule] ✓ 自動抽出: {new_schedule['pointup_start']} 〜 {new_schedule['pointup_end']}")
    return new_schedule


# ─── 勝ったら倍（sports）判定 ─────────────────────────────────────────────
# sports ページは「W勝利！」バナーが画像化されていて HTML 文字列を解析しても
# 検出できない。代わりに「過去のキャンペーン開催日一覧」テーブルから
# 昨日（= 今日のポイント付与対象となる試合日）の結果を読み取る。

SPORTS_URL_BARE = "https://event.rakuten.co.jp/campaign/sports/"

# 例: 「4月17日（金） 楽天イーグルス＆ヴィッセル」「4月11日（土） 楽天イーグルス」
# ヴィッセルのみの場合は「ヴィッセル」単独、両チーム勝利は＆または&で連結
_SPORTS_ROW_RE = re.compile(
    r'(\d{1,2})月(\d{1,2})日'
    r'(?:[（(][^）)]{1,3}[）)])?'
    r'\s*((?:楽天イーグルス|ヴィッセル神戸|ヴィッセル|イーグルス)'
    r'(?:\s*[＆&]\s*(?:ヴィッセル神戸|ヴィッセル|楽天イーグルス|イーグルス))?)'
)


def detect_sports_wins(now: datetime.datetime) -> tuple[bool | None, bool | None]:
    """sports ページの過去開催日一覧テーブルから、今日のW勝利状況を判定。
    試合で勝った翌日が倍率対象日なので、今日の 0-23:59 は「昨日の試合結果」が効く。
    深夜をまたぐ試合もあるため、昨日と一昨日の両方を確認する。

    戻り値: (eagles_flag, vissel_flag)
       - (True,  *    ) / (*,    True ): 該当試合あり → 倍率有効
       - (False, False): ページ正常取得できたが該当行なし → 倍率無効（確定）
       - (None,  None ): ページ取得失敗／HTML解析失敗    → キーワード判定にフォールバック

    ⚠️ 重要: 「該当行なし」は (False, False) を返す。キーワード判定は楽天ページ
    内の過去実績や説明文（"イーグルス勝利時ポイント2倍" 等）に含まれる文言に
    常に反応して誤陽性を起こすため、テーブル判定で確信がある時はそれを優先する。
    """
    html = fetch(SPORTS_URL_BARE)
    if not html:
        # ネットワーク失敗 → キーワード判定にフォールバック
        return (None, None)

    # HTML タグ除去してテキスト化（スペース区切り）
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text)

    # 過去開催日一覧セクションが存在することを確認（HTML構造が変わっていないか）
    # 見つからなければ解析失敗とみなしてフォールバック
    if '過去のキャンペーン開催日一覧' not in text:
        print("  [sports] 過去開催日一覧セクションが見つからず → キーワード判定にフォールバック")
        return (None, None)

    # 今日が何曜日で何月何日か
    today = now.date()
    candidates = [today - datetime.timedelta(days=1), today - datetime.timedelta(days=2)]

    eagles = False
    vissel = False
    matched = False
    # ページ内の開催日一覧は時系列降順で並ぶ (新 → 旧)。
    # 月番号が上昇したら年度境界（= 前年度の領域に突入）と判断してスキャン停止する。
    # これがないと「前年の4月19日」のような古いデータを誤って今年として拾ってしまう。
    prev_mo = None
    for m in _SPORTS_ROW_RE.finditer(text):
        mo, d, teams = int(m.group(1)), int(m.group(2)), m.group(3)
        if prev_mo is not None and mo > prev_mo:
            # 月が上昇 = 年度跨ぎ → 以降は前年度データなのでスキャン終了
            print(f"  [sports] 年度境界検知（{prev_mo}月 → {mo}月）→ スキャン終了")
            break
        prev_mo = mo
        # 年は暦上の最新一致を採用（過去半年以内）
        for cand in candidates:
            if cand.month == mo and cand.day == d:
                # 対象期間: 試合日翌日 = 今日
                bonus_date = cand + datetime.timedelta(days=1)
                if bonus_date == today:
                    matched = True
                    if "イーグルス" in teams:
                        eagles = True
                    if "ヴィッセル" in teams:
                        vissel = True
                    print(f"  [sports] {mo}/{d} の試合結果: {teams} → 今日({today}) 有効")
                break

    if not matched:
        # ページは正常取得できたが、昨日・一昨日の勝利行が存在しない
        # = 両チームとも負けた or 試合なし → 倍率無効で確定
        print(f"  [sports] 昨日・一昨日の勝利行なし → eagles/vissel 共に false 確定")
        return (False, False)
    return (eagles, vissel)


# ─── ポケモンカード抽選（楽天ブックス）判定 ─────────────────────────────
# pokemon_lottery.json に複数の受付期間を登録できる。
# 受付期間中(= start <= now <= end) のみ True を返す。
POKEMON_LOTTERY_JSON = "pokemon_lottery.json"
SEASONAL_EVENTS_JSON = "seasonal_events.json"


def detect_seasonal_events(now: datetime.datetime) -> dict[str, bool]:
    """seasonal_events.json に定義された季節イベントの開催状況を判定する。

    判定条件（全てを満たすとき true）:
      1. 現在時刻が active_periods のいずれかの [start, end] に入っている
      2. URL が取得でき、verify_keywords のいずれかを含む
      3. end_keywords のいずれも含まない

    ネットワーク失敗時は期間内ならデフォルト true（安全側 = サイトに出る）。
    戻り値: { key: bool } — 定義された全イベントに対する判定結果。
    """
    data = load_json(SEASONAL_EVENTS_JSON, {})
    events = data.get("events", []) if isinstance(data, dict) else []
    out: dict[str, bool] = {}
    for ev in events:
        key = ev.get("key")
        if not key:
            continue
        # 期間内か
        periods = ev.get("active_periods", [])
        in_window = False
        for p in periods:
            try:
                s = datetime.datetime.fromisoformat(p["start"])
                e = datetime.datetime.fromisoformat(p["end"])
            except (KeyError, ValueError, TypeError):
                continue
            if s <= now <= e:
                in_window = True
                break
        if not in_window:
            out[key] = False
            print(f"  [{key}] 期間外")
            continue

        # URL 取得 → キーワード検証
        url = ev.get("url")
        if not url:
            # URL 未設定なら期間判定のみで true
            out[key] = True
            print(f"  [{key}] ✓ 期間内（URL検証なし）")
            continue

        page = fetch(url)
        if page is None:
            # 取得失敗 → 安全側=false（壊れたURLを表示し続けない）。一時障害なら次cronで復活する
            out[key] = False
            print(f"  [{key}] ⚠️ 取得失敗 → false（次cronで再判定）")
            continue

        end_kws = ev.get("end_keywords", [])
        if any(kw in page for kw in end_kws):
            out[key] = False
            print(f"  [{key}] ✗ 終了キーワード検出")
            continue

        verify_kws = ev.get("verify_keywords", [])
        if verify_kws and not any(kw in page for kw in verify_kws):
            out[key] = False
            print(f"  [{key}] ✗ 検証キーワード不在（ページ内容変化の可能性）")
            continue

        out[key] = True
        print(f"  [{key}] ✓ 期間内 & ページ検証OK")

    return out


def detect_pokemon_lottery(now: datetime.datetime) -> bool:
    data = load_json(POKEMON_LOTTERY_JSON, {})
    periods = data.get("receipt_periods", []) if isinstance(data, dict) else []
    for p in periods:
        try:
            s = datetime.datetime.fromisoformat(p["start"])
            e = datetime.datetime.fromisoformat(p["end"])
        except (KeyError, ValueError, TypeError):
            continue
        if s <= now <= e:
            print(f"  [pokemon_lottery] 受付期間中: {p.get('name', '(no name)')}")
            return True
    return False


def marathon_flags_from_schedule(schedule: dict) -> tuple[bool | None, bool | None]:
    """スケジュールから現在時刻基準で (marathon, marathon_pointup) を計算。
    スケジュール無効の場合は (None, None) を返し、呼び出し側はキーワード判定にフォールバックする。"""
    if not schedule:
        return (None, None)
    try:
        p_start = schedule.get("pointup_start")
        p_end   = schedule.get("pointup_end")
        if not p_start or not p_end:
            return (None, None)
        p_start_dt = datetime.datetime.fromisoformat(p_start)
        p_end_dt   = datetime.datetime.fromisoformat(p_end)
    except Exception:
        return (None, None)

    now = datetime.datetime.now(JST)
    e_start = schedule.get("entry_start")
    e_start_dt = None
    if e_start:
        try:
            e_start_dt = datetime.datetime.fromisoformat(e_start)
        except Exception:
            pass

    # エントリー期間開始 〜 ポイントアップ終了 の間は marathon=true
    start_of_marathon = e_start_dt if e_start_dt else p_start_dt
    marathon = start_of_marathon <= now <= p_end_dt
    pointup  = p_start_dt <= now <= p_end_dt
    return (marathon, pointup)


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
    """URLが既知パターンに該当するかチェック（trailing slash 揺れに対応）。"""
    norm_url = url.rstrip('/')
    for pattern in KNOWN_URL_PATTERNS:
        norm_pattern = pattern.rstrip('/')
        if norm_pattern in norm_url:
            return True
    return False


# カテゴリナビゲーションURLの除外パターン
# event.rakuten.co.jp/coupon/<カテゴリ短縮名> はクーポン一覧ページで個別キャンペーンではない
CATEGORY_NAV_TAILS = {
    "sweets", "pc", "sports", "accessories", "drink", "autogoods",
    "medicine", "sake", "electronics", "baby", "media", "appliance",
    "health", "daily", "about", "beauty", "inner", "mensfashion",
    "ladiesfashion", "bag", "hobby", "watch", "kitchen", "flower",
    "pet", "shoes", "interior", "food", "newshop", "jewelry",
    "tv", "audio", "camera", "diy", "kids", "men",
}

# キャンペーン名として使えない汚いパターン
INVALID_NAME_PATTERNS = [
    re.compile(r'^[・〜～\s\-]'),     # 句読点で始まる（"・オーディオ・..." など）
    re.compile(r'はこちら$'),         # "○○はこちら" は誘導用バナーで誤検出
    re.compile(r'^クーポンを探す$'),
    re.compile(r'^ただいまの注目'),
    re.compile(r'^（'),               # 括弧で始まる（"（スーパーポイント...」"）
]

# 「過去キャンペーンのお礼ページ」を検出する句（追加でEND判定）
GRATITUDE_PHRASES = [
    "お買い物ありがとうございました",
    "ご利用ありがとうございました",
    "ご来場ありがとうございました",
    "ご参加ありがとうございました",
]


def is_invalid_campaign_name(name: str) -> bool:
    if not name or len(name) < 4:
        return True
    for p in INVALID_NAME_PATTERNS:
        if p.search(name):
            return True
    return False


def is_category_nav_url(url: str) -> bool:
    """event.rakuten.co.jp/coupon/<カテゴリ短縮名> 形式を検出してスキップ"""
    m = re.match(r'^https?://event\.rakuten\.co\.jp/coupon/([^/]+)/?$', url)
    if not m:
        return False
    return m.group(1).lower() in CATEGORY_NAV_TAILS


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


def extract_title_near_link_v2(html: str, url: str) -> str:
    """v2: img alt -> リンクテキスト -> v1 フォールバック の順で名前を抽出"""
    escaped = re.escape(url)
    alt_match = re.search(
        rf'<a[^>]*href=["\'](?:{escaped})["\'][^>]*>\s*<img[^>]*\salt=["\']([^"\']+)["\']',
        html, re.IGNORECASE | re.DOTALL,
    )
    if alt_match:
        alt = alt_match.group(1).strip()
        if alt and len(alt) >= 3:
            return alt[:50]
    text_match = re.search(
        rf'<a[^>]*href=["\'](?:{escaped})["\'][^>]*>(.*?)</a>',
        html, re.IGNORECASE | re.DOTALL,
    )
    if text_match:
        inner = re.sub(r'<[^>]+>', '', text_match.group(1)).strip()
        inner = re.sub(r'\s+', ' ', inner)
        if inner and len(inner) >= 3:
            return inner[:50]
    return extract_title_near_link(html, url)


END_KEYWORDS   = [
    "終了しました", "キャンペーンは終了", "受付終了",
    "エントリー期間は終了", "エントリーは終了", "開催期間は終了",
    "開催していません", "次回の", "次回開催",
    "ページが見つかりません", "お探しのページは",
]
ACTIVE_KEYWORDS = ["エントリーする", "エントリー受付中", "ポイントアップ", "クーポン", "開催中"]


def is_campaign_active(url: str) -> bool:
    """URLにアクセスして、キャンペーンがまだ開催中かを判定する（保守的判定）。
    STRICT終了句／お礼ページ句の検出時のみ false。それ以外はアクティブ扱い。"""
    page = fetch(url)
    if page is None:
        return True   # 取得失敗時は消さない（安全側）
    # STRICT終了句
    STRICT_ENDS = [
        "本キャンペーンは終了", "このキャンペーンは終了",
        "ご応募の受付は終了", "本特集は終了",
    ]
    for p in STRICT_ENDS:
        if p in page:
            return False
    # 過去開催のお礼ページ
    for p in GRATITUDE_PHRASES:
        if p in page:
            return False
    return True


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


def extract_html_entry_urls(html_path: str) -> set:
    """imaraku.html を読み、ハードコード済みエントリーの url を全部抜く。
    ── 除外ルール ──
      ・a.r10.to（短縮URLは中身がリダイレクトで判定不能）
      ・showOnDays が指定されたエントリー（特定日のみアクティブな URL は
        対象外日に 404 や 一時リダイレクトを返すことがあり、URL生存判定不可）
      ・campaignKey が指定されたエントリー（campaign_status.json で別系統管理）
    """
    if not os.path.exists(html_path):
        return set()
    with open(html_path, encoding="utf-8") as f:
        content = f.read()

    # エントリーオブジェクト全体（{ ... }）を捉えてからその中身を判定する。
    # imaraku.html はエントリーが 1 行 OR 複数行で書かれているため、
    # 中括弧ベースで安全に抽出する。
    urls = set()
    # `{` で始まり `},` で閉じる JS オブジェクト風ブロックを貪欲でなく拾う
    block_re = re.compile(r"\{[^{}]*?\burl:\s*[\"'](https?://[^\"']+)[\"'][^{}]*?\}", re.DOTALL)
    for m in block_re.finditer(content):
        block = m.group(0)
        u = m.group(1)
        if u.startswith("#") or u in ("https://", "http://"):
            continue
        if "a.r10.to" in u:
            continue
        # showOnDays または campaignKey が同じブロック内にあればスキップ
        if "showOnDays" in block:
            continue
        if "campaignKey" in block:
            continue
        urls.add(u)
    return urls


def _check_one_url(url: str) -> tuple:
    """1URLの生存チェック。(url, status) を返す。
      status: "expired:理由" → 終了確定
              "active"        → 取得成功（明確な終了句なし＝アクティブ扱い）
              "unknown"       → 取得失敗（ネットワーク等）/ 判定保留

    ── 保守的判定（誤検出ゼロ優先）──
    終了マーク条件（次のいずれか）:
      A. HTTP 404 で「ページが見つかりません」系の文言あり
      B. STRICT_END_PHRASES（「本キャンペーンは終了」等の文脈確定句）あり
         AND エントリーボタン等のアクティブ要素なし
    通常の「終了しました」「次回開催」等は過去キャンペーン言及で誤マッチするため
    単独では終了マークしない。
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=8, allow_redirects=True)
        status_code = r.status_code
        text = r.text
    except Exception:
        return (url, "unknown")  # 取得失敗 → 判定保留（既存expired状態は維持）

    # A. HTTP 404 + ページなし系
    if status_code == 404 or status_code >= 500:
        if any(kw in text for kw in ["ページが見つかりません", "お探しのページは", "404"]):
            return (url, f"expired:HTTP {status_code}")
        # 5xxの場合は判定保留（楽天側の一時的な不調）
        return (url, "unknown")

    # B. 文脈確定句（「本キャンペーンは終了」など、明らかにこのページ自身の終了）
    STRICT_END_PHRASES = [
        "本キャンペーンは終了",
        "本キャンペーンは終了しました",
        "このキャンペーンは終了しました",
        "このキャンペーンは終了いたしました",
        "本キャンペーンの受付は終了",
        "このキャンペーンの受付は終了",
        "ご応募の受付は終了",
        "本特集は終了",
        "ページの公開は終了",
    ]
    has_strict_end = any(p in text for p in STRICT_END_PHRASES)
    if has_strict_end:
        active_signals = [
            'class="entryBtn"', 'class="entry-btn"',
            'エントリーする</a>', 'エントリーする</button>',
            'エントリーはこちら',
        ]
        if not any(s in text for s in active_signals):
            return (url, "expired:STRICT終了句検出")

    # C. 過去開催お礼ページ（"お買い物ありがとうございました" 等）
    GRATITUDE = [
        "お買い物ありがとうございました",
        "ご利用ありがとうございました",
    ]
    if any(p in text for p in GRATITUDE):
        return (url, "expired:お礼ページ検出")

    return (url, "active")


def check_hardcoded_entry_urls(html_path: str) -> tuple:
    """imaraku.html 内の全エントリーURLを並列で生存チェックする。
    戻り値: (expired_dict, active_set, unknown_set)
      expired_dict: {url: {ended_at, matched_keyword}} 終了確定
      active_set:   取得成功で明確な終了句なし＝アクティブ確定
      unknown_set:  取得失敗（既存expired状態を維持すべきURL）
    並列度20で高速化（77URL × 8s/URL逐次 = 600s → 並列なら ~30s）。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    urls = sorted(extract_html_entry_urls(html_path))
    print(f"  対象URL: {len(urls)} 件（並列20）")
    expired = {}
    active = set()
    unknown = set()
    today = datetime.datetime.now(JST).date().isoformat()
    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = {ex.submit(_check_one_url, u): u for u in urls}
        for fut in as_completed(futures):
            url, status = fut.result()
            if status.startswith("expired:"):
                kw = status.split(":", 1)[1]
                print(f"  🗑️  終了確定: {kw} → {url}")
                expired[url] = {"ended_at": today, "matched_keyword": kw}
            elif status == "active":
                active.add(url)
            else:  # unknown
                unknown.add(url)
    print(f"  → 終了 {len(expired)} / アクティブ {len(active)} / 取得失敗 {len(unknown)}")
    return expired, active, unknown


def detect_new_campaigns(existing_new: list) -> list:
    """スキャンページから新しいキャンペーンURLを検出して返す。
    ── 多重ガード（誤検出ゼロ優先）──
      ① is_known: 既知URL（marathon, eagles 等）はスキップ
      ② is_category_nav_url: 楽天クーポンのカテゴリ一覧ページはスキップ
      ③ STRICT_ENDS / GRATITUDE_PHRASES: 終了確定ページはスキップ
      ④ ACTIVE_KEYWORDS が無いページはスキップ
      ⑤ name 重複・不正パターンはスキップ
      ⑥ 1ラン最大10件まで（暴走防止）
    """
    existing_urls = {c["url"] for c in existing_new}
    existing_names = {c.get("name", "") for c in existing_new}
    found = []
    seen_names_this_run = set()
    MAX_PER_RUN = 10  # 1回の実行で追加するキャンペーンの上限

    for scan_url in SCAN_PAGES:
        if len(found) >= MAX_PER_RUN:
            break
        print(f"  スキャン: {scan_url}")
        html = fetch(scan_url)
        if not html:
            continue
        urls = NEW_CAMPAIGN_URL_RE.findall(html)
        for url in set(urls):
            if len(found) >= MAX_PER_RUN:
                break
            # クリーン化（クエリ除去）
            url = url.split('?')[0].rstrip('/')
            # ① 既知パターン
            if is_known(url):
                continue
            # ② カテゴリナビページ
            if is_category_nav_url(url):
                continue
            # 既存リストにあるならスキップ
            if url in existing_urls:
                continue

            # エントリーページかチェック
            page = fetch(url)
            if not page:
                continue
            # ④ ACTIVE要素なし → スキップ
            if not any(kw in page for kw in ACTIVE_KEYWORDS):
                continue
            # ③ 終了確定ページ → スキップ
            STRICT_ENDS = [
                "本キャンペーンは終了", "このキャンペーンは終了",
                "ご応募の受付は終了", "本特集は終了",
            ]
            if any(p in page for p in STRICT_ENDS):
                continue
            if any(p in page for p in GRATITUDE_PHRASES):
                print(f"  🚫 過去開催のお礼ページ → スキップ: {url}")
                continue

            # ⑤ 名前抽出＆バリデーション
            name = extract_title_near_link_v2(html, url)
            if is_invalid_campaign_name(name):
                continue
            # 同じ名前の重複は排除（同一バナーで複数URLパターン）
            if name in existing_names or name in seen_names_this_run:
                continue
            seen_names_this_run.add(name)

            print(f"  🆕 新キャンペーン候補: {name} → {url}")
            found.append({"name": name, "url": url, "point": "要確認", "detected_at": __import__('datetime').date.today().isoformat()})
            existing_urls.add(url)

    if len(found) >= MAX_PER_RUN:
        print(f"  ⚠️ 上限{MAX_PER_RUN}件に到達したのでスキャン中断")
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

    # 1-b. マラソン スケジュール取得 → 時刻ベースで marathon / marathon_pointup を上書き
    print("\n── 1-b. マラソン スケジュール判定 ──")
    schedule = update_marathon_schedule()
    m_flag, p_flag = marathon_flags_from_schedule(schedule)
    if m_flag is not None:
        if results.get("marathon") != m_flag:
            print(f"  [marathon] キーワード判定={results.get('marathon')} → スケジュール判定={m_flag} で上書き")
        results["marathon"] = m_flag
    if p_flag is not None:
        if results.get("marathon_pointup") != p_flag:
            print(f"  [marathon_pointup] キーワード判定={results.get('marathon_pointup')} → スケジュール判定={p_flag} で上書き")
        results["marathon_pointup"] = p_flag

    # 1-b2. 勝ったら倍（sports）は過去開催日テーブルで判定（バナー画像対策）
    print("\n── 1-b2. 勝ったら倍 判定（過去開催日テーブル） ──")
    now_jst = datetime.datetime.now(JST)
    e_flag, v_flag = detect_sports_wins(now_jst)
    if e_flag is not None:
        if results.get("eagles") != e_flag:
            print(f"  [eagles] キーワード判定={results.get('eagles')} → テーブル判定={e_flag} で上書き")
        results["eagles"] = e_flag
    if v_flag is not None:
        if results.get("vissel") != v_flag:
            print(f"  [vissel] キーワード判定={results.get('vissel')} → テーブル判定={v_flag} で上書き")
        results["vissel"] = v_flag

    # 1-b3. ポケカ抽選（楽天ブックス）は pokemon_lottery.json の受付期間で判定
    print("\n── 1-b3. ポケカ抽選 判定（受付期間スケジュール） ──")
    results["pokemon_lottery"] = detect_pokemon_lottery(now_jst)
    if not results["pokemon_lottery"]:
        print("  [pokemon_lottery] 受付期間外")

    # 1-b4. シーズナル特集（母の日／父の日等）判定
    print("\n── 1-b4. シーズナル特集 判定（seasonal_events.json） ──")
    seasonal = detect_seasonal_events(now_jst)
    for k, v in seasonal.items():
        results[k] = v

    # 1-c. マラソン非開催時はマラソン内サブキャンペーンを強制 false
    if not results.get("marathon", False):
        for k in ["repeat_purchase", "guerrilla", "superdeal_4h", "mobiledeal"]:
            if results.get(k):
                print(f"  [{k}] マラソン非開催のため false に補正")
                results[k] = False

    print("\n── 結果まとめ ──")
    for key, val in results.items():
        print(f"  {key:<20} {'✓ 開催中' if val else '✗ 終了/非開催'}")

    changed_status = save_json(STATUS_JSON, results)
    print(f"\n{'✅ campaign_status.json を更新' if changed_status else '変更なし（campaign_status.json）'}")

    # 1-d. ハードコード済みエントリーのURL生存チェック
    print("\n── 1-d. imaraku.html ハードコードURLの生存チェック ──")
    existing_expired = load_json(EXPIRED_JSON, {})
    new_expired, active_set, unknown_set = check_hardcoded_entry_urls(IMARAKU_HTML)

    # マージルール:
    #  ① 今回 expired 検出 → expired 入り（最新の matched_keyword で上書き）
    #  ② 今回 active 確定（取得成功＆終了句なし） → expired から除去（復活）
    #  ③ 今回 unknown（取得失敗） → 既存 expired 状態を維持（一時的失敗で誤復活させない）
    #  ④ 既存 expired にあるが今回チェック対象外（HTMLから消えた） → 削除（自然な掃除）
    merged_expired = dict(new_expired)
    revived = []
    preserved = []
    cleaned = []
    for u, v in existing_expired.items():
        if u in new_expired:
            continue  # ① 既に上書き済
        if u in active_set:
            revived.append(u)  # ② 復活
        elif u in unknown_set:
            # ③ unknown → 既存状態維持
            merged_expired[u] = v
            preserved.append(u)
        else:
            # ④ HTML から消えた URL → expired 一覧から削除
            cleaned.append(u)

    if revived:
        for u in revived:
            print(f"  ♻️  復活検出（終了URL一覧から除去）: {u}")
    if preserved:
        print(f"  💾 取得失敗で既存expired状態を維持: {len(preserved)} 件")
    if cleaned:
        print(f"  🧹 HTMLから消えたURLをexpired一覧から削除: {len(cleaned)} 件")
    changed_expired = save_json(EXPIRED_JSON, merged_expired)
    print(f"  終了確定 計: {len(merged_expired)} 件 / 復活: {len(revived)} 件")

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
    changed = changed_status or changed_new or changed_expired
    env_file = os.environ.get("GITHUB_OUTPUT", "")
    if env_file:
        with open(env_file, "a") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")

    print("\n=== チェック完了 ===")


if __name__ == "__main__":
    main()
