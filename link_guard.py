#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""link_guard.py — X投稿に載せるリンク先の生存チェック共有モジュール。

2026-06-10 にトラベル投稿が「この企画は終了しました」ページを案内してしまった事故の恒久対策。
投稿直前に「リンク先が今も生きたキャンペーンページか」を検証し、死んだリンクを世に出さない。

設計（保守的＝「検証できたリンクだけ投稿する」）:
  - hb.afl.rakuten.co.jp ラップ済みURLは中身(pc=)を取り出して検査する
  - 200以外 / 取得失敗 / 終了文言あり → NG（投稿側はそのリンクを落とすか投稿自体をスキップ）
  - check_campaigns の状態判定（不明は現状維持）とは思想が違うことに注意:
    こちらは「外に出す推薦リンク」なので、確認できないものは出さない方が信頼を守れる。
"""
import re
from urllib.parse import urlparse, parse_qs, unquote

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.9"}

# 終了確定のサイン（キャンペーン個別ページ前提。ハブページには使わないこと＝地雷#1）
END_SIGNS = [
    "この企画は終了",
    "本キャンペーンは終了",
    "このキャンペーンは終了",
    "キャンペーンは終了しました",
    "受付は終了",
    "ご利用ありがとうございました",
    "お買い物ありがとうございました",
    "ページが見つかりません",
    "お探しのページ",
]


def unwrap_aff(url: str) -> str:
    """アフィリエイトハブ(hb.afl)経由URLなら中身の生URLを返す。それ以外はそのまま。"""
    if "hb.afl.rakuten.co.jp" not in (url or ""):
        return url
    try:
        qs = parse_qs(urlparse(url).query)
        inner = (qs.get("pc") or [""])[0]
        return unquote(inner) if inner else url
    except Exception:
        return url


def is_link_alive(url: str, timeout: int = 12):
    """リンク先が生きたキャンペーンページか。(ok: bool, reason: str) を返す。
    NG条件: 取得失敗 / HTTP 200以外 / 終了文言を含む。"""
    target = unwrap_aff(url)
    if not target:
        return False, "empty"
    try:
        r = requests.get(target, headers=HEADERS, timeout=timeout, allow_redirects=True)
    except Exception as e:
        return False, f"fetch_error:{type(e).__name__}"
    if r.status_code != 200:
        return False, f"http_{r.status_code}"
    # 文字コード自動判定: 楽天系はcharset未宣言ページがあり、requestsがISO-8859-1と
    # 誤推定すると本文が文字化けして「終了」がマッチしない（2026-06-11 実テストで検出）。
    if r.encoding is None or (r.encoding or "").lower() in ("iso-8859-1", "us-ascii"):
        r.encoding = r.apparent_encoding or "utf-8"
    text = re.sub(r"\s+", " ", r.text)
    for kw in END_SIGNS:
        if kw in text:
            return False, f"end_sign:{kw}"
    return True, "ok"


def filter_alive(items: list, url_key: str = "url") -> list:
    """dictリストから url_key のリンクが生きているものだけ返す（落としたものはprint）。"""
    alive = []
    for it in items:
        ok, reason = is_link_alive(it.get(url_key, ""))
        if ok:
            alive.append(it)
        else:
            print(f"  🚫 link_guard: リンク先NG({reason}) → 除外: "
                  f"{it.get('label') or it.get('name') or it.get(url_key, '')}")
    return alive
