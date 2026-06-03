#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""楽天スーパーSALE の自動アナウンス投稿。

毎日 14-21時JST の窓で起動し、スーパーSALE公式ページから開催日程を自動検出して:
  - 一般開始の前日(= 楽天モバイル先行日) → モバイル先行アナウンス
  - 一般開始日                          → 一般開幕アナウンス
を投稿する（各1回・dedup）。

── 日程検出（2026-06-03 実ページで検証済み）──
  公式ページの「20:00開始 → 翌日以降 01:59 終了・3日以上」の長期レンジのうち、
  直近(±数日)で最も遅い開始を「一般開始」とみなす。先行 = その前日
  （楽天モバイル先行ロジック。相棒承認の "最悪1日早くてOK" 前提）。
  モバイル先行アナウンスは本文に「楽天モバイル」＋「先行」がある時のみ（安全弁）。

── 投稿 ──
  Cloudflare マネージドチャレンジ対策で UA 付与＋一時エラーリトライ（地雷#15）。
  supersale_announced.json で二重投稿を防止。時間窓外/対象日でない/未検出 は何もしない。
"""
import os
import re
import sys
import json
import time
import html as _html
import datetime
from urllib.parse import quote

import requests
from requests_oauthlib import OAuth1

# ── 認証情報（GitHub Secrets）──
API_KEY             = os.environ["TWITTER_API_KEY"]
API_SECRET          = os.environ["TWITTER_API_SECRET"]
ACCESS_TOKEN        = os.environ["TWITTER_ACCESS_TOKEN"]
ACCESS_TOKEN_SECRET = os.environ["TWITTER_ACCESS_TOKEN_SECRET"]

JST = datetime.timezone(datetime.timedelta(hours=9))
RAKUTEN_AFFILIATE_ID = "1c52abea.36641b1e.1c52abeb.f5f67f16"
SUPERSALE_URL  = "https://event.rakuten.co.jp/campaign/supersale/"
ANNOUNCED_FILE = "supersale_announced.json"
WD = ["月", "火", "水", "木", "金", "土", "日"]
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
FETCH_HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.9"}

_DATE = re.compile(
    r'(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日(?:[（(][^）)]{1,3}[）)])?\s*(\d{1,2})[:：](\d{2})')
_RANGE = re.compile(
    r'((?:\d{4}年)?\d{1,2}月\d{1,2}日(?:[（(][^）)]{1,3}[）)])?\s*\d{1,2}[:：]\d{2})'
    r'\s*[〜～~\-–—]\s*'
    r'((?:\d{4}年)?\d{1,2}月\d{1,2}日(?:[（(][^）)]{1,3}[）)])?\s*\d{1,2}[:：]\d{2})')


def _parse_jst(text, fallback_year):
    m = _DATE.search(text)
    if not m:
        return None
    y = int(m.group(1)) if m.group(1) else fallback_year
    try:
        return datetime.datetime(y, int(m.group(2)), int(m.group(3)),
                                 int(m.group(4)), int(m.group(5)), tzinfo=JST)
    except ValueError:
        return None


def aff(url):
    e = quote(url, safe='')
    return f"https://hb.afl.rakuten.co.jp/hgc/{RAKUTEN_AFFILIATE_ID}/?pc={e}&m={e}"


def detect(now, page_html):
    """(一般レンジ(start,end) or None, 先行開始 or None) を返す。"""
    clean = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', _html.unescape(page_html)))
    rngs = set()
    for a, b in _RANGE.findall(clean):
        s = _parse_jst(a, now.year)
        e = _parse_jst(b, now.year)
        if s and e and e > s:
            rngs.add((s, e))
    # 一般枠候補: 20:00開始 / 翌日以降 01:00-02:59 終了 / 3日以上 / 直近(±窓)
    lo = (now - datetime.timedelta(days=1)).date()
    hi = (now + datetime.timedelta(days=3)).date()
    main = [(s, e) for s, e in rngs
            if s.hour == 20 and e.hour in (1, 2) and (e - s).days >= 3
            and lo <= s.date() <= hi]
    if not main:
        return None, None
    general = max(main, key=lambda x: x[0])          # 最も遅い開始 = 一般枠
    senko_start = general[0] - datetime.timedelta(days=1)
    mobile = ("楽天モバイル" in page_html and "先行" in page_html)
    return general, (senko_start if mobile else None)


def _post_once(text):
    """X 投稿。Cloudflare 403 / 429 / 5xx は最大3回リトライ。(成功, ステータス) を返す。"""
    auth = OAuth1(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
    headers = {"Content-Type": "application/json", "User-Agent": UA}
    last = 0
    for attempt in range(1, 4):
        try:
            r = requests.post("https://api.twitter.com/2/tweets",
                              auth=auth, json={"text": text}, headers=headers, timeout=20)
        except requests.RequestException as ex:
            print(f"❌ 投稿例外(試行{attempt}/3): {ex}", file=sys.stderr)
            if attempt < 3:
                time.sleep(5 * attempt)
                continue
            return False, 0
        if r.status_code == 201:
            print(f"✅ 投稿成功: {r.json()['data']['id']}")
            return True, 201
        last = r.status_code
        is_cf = r.status_code == 403 and (
            "Just a moment" in r.text or "cloudflare" in r.text.lower()
            or "cf_chl" in r.text)
        transient = is_cf or r.status_code in (429, 500, 502, 503)
        print(f"❌ 投稿失敗(試行{attempt}/3): {r.status_code} "
              f"{'Cloudflareチャレンジ' if is_cf else r.text[:160]}", file=sys.stderr)
        if attempt < 3 and transient:
            time.sleep(5 * attempt)
            continue
        return False, r.status_code
    return False, last


def _fmt(dt):
    return f"{dt.month}/{dt.day}({WD[dt.weekday()]})"


def tweet_senko(senko_start, general_start, url):
    return (
        "⚡楽天モバイルユーザーは“今夜”先行スタート！\n\n"
        "🛒楽天スーパーSALE\n"
        f"モバイル契約者は本日{_fmt(senko_start)}{senko_start.hour}:00〜先行で参加OK🎉\n"
        f"（一般開始は明日{_fmt(general_start)}{general_start.hour}:00〜）\n\n"
        "エントリー＆詳細はこちら👇\n"
        f"{url}\n"
        "#楽天スーパーセール #楽天モバイル #ポイ活"
    )


def tweet_general(general_start, general_end, url):
    return (
        f"🔥本日{general_start.hour}:00開幕！楽天スーパーSALE\n\n"
        f"🛒{_fmt(general_start)}{general_start.hour}:00〜"
        f"{_fmt(general_end)}{general_end.hour}:{general_end.minute:02d}\n"
        "年に数回の最大級セール✨\n"
        "半額・数量限定アイテムや\n"
        "ショップ買いまわりでポイントUP\n\n"
        "まずはエントリー👇\n"
        f"{url}\n"
        "#楽天スーパーセール #ポイ活 #楽天市場"
    )


def load_announced():
    if os.path.exists(ANNOUNCED_FILE):
        try:
            with open(ANNOUNCED_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_announced(d):
    with open(ANNOUNCED_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _set_output(key, val):
    gho = os.environ.get("GITHUB_OUTPUT")
    if gho:
        with open(gho, "a") as f:
            f.write(f"{key}={val}\n")


def main():
    now = datetime.datetime.now(JST)
    force = os.environ.get("SUPERSALE_FORCE", "").lower() in ("1", "true", "yes")
    # 時間ガード: 14-21時JST 想定。cron遅延の余裕で 13-23時台まで許容。窓外は何もしない。
    if not force and not (13 <= now.hour <= 23):
        print(f"時間窓外({now.hour}時JST) → 何もしない")
        _set_output("changed", "false")
        return

    try:
        r = requests.get(SUPERSALE_URL, headers=FETCH_HEADERS, timeout=20)
        page = r.text if r.status_code == 200 else None
    except Exception as e:
        print(f"ページ取得失敗: {e}", file=sys.stderr)
        page = None
    if not page:
        _set_output("changed", "false")
        return

    general, senko = detect(now, page)
    print(f"検出: 一般開始={general[0] if general else None} 先行開始={senko}")
    if not general:
        print("スーパーSALEの開催日程を検出できず → 何もしない")
        _set_output("changed", "false")
        return

    announced = load_announced()
    posted = False
    url = aff(SUPERSALE_URL)

    if senko and now.date() == senko.date():
        # ① 先行日（= 一般開始の前日）→ モバイル先行ツイート
        key = senko.date().isoformat()
        if announced.get("senko") == key:
            print("先行アナウンスは投稿済み → スキップ")
        else:
            text = tweet_senko(senko, general[0], url)
            print(f"\n[モバイル先行]\n{text}\n")
            if _post_once(text)[0]:
                announced["senko"] = key
                save_announced(announced)
                posted = True
    elif now.date() == general[0].date():
        # ② 一般開始日 → 一般開幕ツイート
        key = general[0].date().isoformat()
        if announced.get("general") == key:
            print("一般アナウンスは投稿済み → スキップ")
        else:
            text = tweet_general(general[0], general[1], url)
            print(f"\n[一般開幕]\n{text}\n")
            if _post_once(text)[0]:
                announced["general"] = key
                save_announced(announced)
                posted = True
    else:
        print("本日は先行日でも一般開始日でもない → 何もしない")

    _set_output("changed", "true" if posted else "false")


if __name__ == "__main__":
    main()
