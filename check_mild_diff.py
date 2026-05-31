#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""マイルドさん(相棒の参照ブログ)の最新まとめ記事と今楽の保有キャンペーンを差分照合し、
今楽に未掲載かつ「開催中」の楽天市場キャンペーンだけを new_campaigns.json に追加する。

── 実行は「特定の日だけ」（日付ゲートはこのスクリプト内 is_trigger_day）──
  ① 毎月1日の前日（＝月末）             … 月替わりで新キャンペーンが入れ替わる
  ② お買い物マラソン開始(pointup_start)の前日 … marathon_schedule.json 参照（マラソン確実）
  ③ マイルドさんが当日に大型セール系まとめを新規投稿  … スーパーセール/ポイントバック祭
     /マラソン/大感謝祭 等を、開催日程を持たずとも「マイルドさんの新着」で検知
GitHub Actions から毎日 23時台に起動し、上記以外の日は何もせず終了する想定。
（マイルドさんは大型セール前日の夜に投稿するので、23時起動なら記事は出ている）
（テスト時は環境変数 MILD_DIFF_FORCE=true で日付ゲートを無視できる）

── 著作権・礼儀 ──
  照合するのは「どの楽天キャンペーンURLが存在するか」という事実のみ。
  名称は各キャンペーンページの og:title（楽天側の正式名）から取得し、
  マイルドさんの記事本文は一切複製しない。リンク先解決(a.r10.to)も最小限。

── フィルタ ──
  check_campaigns.py のガードを再利用（市場外除外/カテゴリナビ/期間検証/名前検証）。
"""
import os
import re
import datetime
from concurrent.futures import ThreadPoolExecutor

import requests

import check_campaigns as cc  # 既存のフィルタ群・定数を再利用（CIは Python 3.11）

FEED_URL = "https://mild7000.hatenablog.com/feed"
ARTICLES_TO_SCAN = 2     # 最新何件の記事を見るか
MAX_ADD = 10             # 1回の実行で追加する上限（detect_new_campaigns と同じ暴走防止）
STRICT_ENDS = ["本キャンペーンは終了", "このキャンペーンは終了",
               "ご応募の受付は終了", "本特集は終了"]
# ③で「大型セール系まとめ」と判定するタイトル語（マラソン以外も広く捕捉）
# 2026-05-31: マイルドさん連絡OK時に「ワンダフルデー」も追加（毎月18日の
#   ワンダフルデーまとめも拾う。マイルドさんが前日に投稿する）。
SALE_KEYWORDS = ["マラソン", "スーパーセール", "スーパーSALE", "スーパー SALE",
                 "ポイントバック", "買い回り", "買いまわり", "大感謝祭", "勝ったら倍",
                 "ワンダフルデー"]


def _norm(u: str) -> str:
    return u.split("?")[0].split("#")[0].rstrip("/").replace("http://", "https://")


def latest_feed_entry(feed_text: str):
    """フィード先頭エントリの (タイトル, 公開日date) を返す。取れなければ (None, None)。"""
    m = re.search(r'<entry>(.*?)</entry>', feed_text or "", re.DOTALL)
    if not m:
        return None, None
    block = m.group(1)
    t = re.search(r'<title>(.*?)</title>', block, re.DOTALL)
    p = re.search(r'<published>(.*?)</published>', block)
    title = re.sub(r'\s+', ' ', t.group(1)).strip() if t else ""
    pub = None
    if p:
        try:
            pub = datetime.datetime.fromisoformat(p.group(1).strip()).date()
        except ValueError:
            pub = None
    return title, pub


def is_trigger_day(now, schedule, latest_title, latest_pub):
    """今日が起動対象日かを判定し (bool, 理由文字列) を返す。"""
    tomorrow = (now + datetime.timedelta(days=1)).date()
    reasons = []
    # ① 明日が1日 = 今日は月末
    if tomorrow.day == 1:
        reasons.append("月初(1日)の前日")
    # ② お買い物マラソン開始(pointup_start)の前日（schedule ベース・確実）
    ps = (schedule or {}).get("pointup_start")
    if ps:
        try:
            if datetime.datetime.fromisoformat(ps).date() == tomorrow:
                reasons.append("お買い物マラソン開始の前日")
        except ValueError:
            pass
    # ③ マイルドさんが「今日」大型セール系まとめを新規投稿（マラソン以外も捕捉）
    if latest_pub == now.date() and latest_title:
        hit = next((k for k in SALE_KEYWORDS if k in latest_title), None)
        if hit:
            reasons.append(f"マイルドさん新着セールまとめ検出（{hit}）")
    return (bool(reasons), " / ".join(reasons))


def _resolve(u: str):
    """a.r10.to アフィリエイト短縮を最終URLに解決。直リンクはそのまま正規化。"""
    if "a.r10.to" not in u:
        return _norm(u)
    try:
        r = requests.get(u, headers=cc.HEADERS, timeout=12, allow_redirects=True)
        return _norm(r.url)
    except Exception:
        return None


def mild_campaign_urls(feed_text: str) -> list:
    """マイルドさん最新記事から event.rakuten.co.jp のキャンペーンURL集合を返す。"""
    arts = re.findall(r'href="(https://mild7000\.hatenablog\.com/entry/[^"]+)"', feed_text or "")
    raw = set()
    for art in arts[:ARTICLES_TO_SCAN]:
        html = cc.fetch(art) or ""
        for u in re.findall(r'href="(https?://[^"]+)"', html):
            if "event.rakuten.co.jp" in u or "a.r10.to" in u:
                raw.add(u)
    if not raw:
        return []
    with ThreadPoolExecutor(max_workers=12) as ex:
        resolved = list(ex.map(_resolve, raw))
    return sorted({u for u in resolved if u and "event.rakuten.co.jp" in u})


def imaraku_known_urls() -> set:
    """今楽が既に保有/掲載済みのURL集合（imaraku.html + new_campaigns.json）。"""
    known = set()
    try:
        with open("imaraku.html", encoding="utf-8") as f:
            site = f.read()
        for u in re.findall(r'https://event\.rakuten\.co\.jp/[^"\'\s)]+', site):
            known.add(_norm(u))
        ar = set(re.findall(r'https://a\.r10\.to/[^"\'\s)]+', site))
        if ar:
            with ThreadPoolExecutor(max_workers=8) as ex:
                for x in ex.map(_resolve, ar):
                    if x and "rakuten" in x:
                        known.add(x)
    except FileNotFoundError:
        pass
    for c in cc.load_json(cc.NEW_JSON, []):
        if c.get("url"):
            known.add(_norm(c["url"]))
    return known


def campaign_name(page: str) -> str:
    """キャンペーンページの og:title（楽天の正式名）から表示名を作る。本文は使わない。"""
    m = (re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', page)
         or re.search(r'<title>([^<]+)</title>', page))
    if not m:
        return ""
    name = re.sub(r'^【楽天市場】', '', m.group(1).strip()).strip()
    return name[:50]


def _set_output(key: str, val: str) -> None:
    gho = os.environ.get("GITHUB_OUTPUT")
    if gho:
        with open(gho, "a") as f:
            f.write(f"{key}={val}\n")


def main() -> None:
    now = datetime.datetime.now(cc.JST)
    schedule = cc.load_json(cc.SCHEDULE_JSON, {})
    force = os.environ.get("MILD_DIFF_FORCE", "").lower() in ("1", "true", "yes")

    feed = cc.fetch(FEED_URL)
    latest_title, latest_pub = latest_feed_entry(feed)

    trigger, reason = is_trigger_day(now, schedule, latest_title, latest_pub)
    if not trigger and not force:
        print(f"本日 {now.date()} は起動対象日ではない（月末/マラソン前日/マイルド新着セールのみ）。終了。")
        _set_output("changed", "false")
        return
    print(f"起動理由: {reason or 'FORCE(テスト)'}  時刻: {now.isoformat()}")
    if latest_title:
        print(f"マイルドさん最新記事: 「{latest_title[:40]}」 ({latest_pub})")

    mild = mild_campaign_urls(feed)
    print(f"マイルドさん最新{ARTICLES_TO_SCAN}記事のキャンペーンURL: {len(mild)} 本")
    known = imaraku_known_urls()
    existing_new = cc.load_json(cc.NEW_JSON, [])
    existing_urls = {_norm(c.get("url", "")) for c in existing_new}
    existing_names = {c.get("name", "") for c in existing_new}

    added = []
    for u in mild:
        if len(added) >= MAX_ADD:
            print(f"  ⚠️ 上限{MAX_ADD}件に到達 → 中断")
            break
        if u in known or u in existing_urls:
            continue
        # check_campaigns のガードを再利用（既知/市場外/カテゴリナビ）
        if cc.is_known(u) or cc.is_non_market_url(u) or cc.is_category_nav_url(u):
            continue
        page = cc.fetch(u)
        if not page:
            continue
        if not any(k in page for k in cc.ACTIVE_KEYWORDS):
            continue
        if any(p in page for p in STRICT_ENDS):
            continue
        if any(p in page for p in cc.GRATITUDE_PHRASES):
            continue
        if cc.period_status(page) == "expired":   # 日付ベースのサイレント終了対策
            continue
        name = campaign_name(page)
        if cc.is_invalid_campaign_name(name) or name in existing_names:
            continue
        existing_names.add(name)
        added.append({"name": name, "url": u, "point": "要確認",
                      "detected_at": now.date().isoformat()})
        print(f"  🆕 取りこぼし追加: {name} → {u}")

    if added:
        existing_new.extend(added)
        cc.save_json(cc.NEW_JSON, existing_new)
        print(f"✅ new_campaigns.json に {len(added)} 件追加（合計 {len(existing_new)} 件）")
        _set_output("changed", "true")
    else:
        print("追加なし（取りこぼしゼロ、または全て既存/除外/終了）")
        _set_output("changed", "false")


if __name__ == "__main__":
    main()
