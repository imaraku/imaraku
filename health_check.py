#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""health_check.py — 今楽の投稿系が「静かに死んでいないか」を毎晩点検し、異常時だけメールで知らせる。

2026-09-12 に X API クレジット枯渇（推定）で全チャンネルが5日間、無言で停止していたのに
誰も気づけなかった事故の恒久対策。相棒は子育て中で毎日タイムラインを見られないため、
「異常があれば向こうから知らせに来る」仕組みが要る。

判定:
  1. posted_slots.json に今日(JST)の投稿記録が無い → 日次ツイートが今日1本も出ていない = 異常
     （日次は毎日必ず 12時/18時 に投稿する設計なので、23:30 時点で0本なら確実に異常）
  2. GitHub Actions 公開API で「今日 failure になった投稿系 workflow」を集計して同封
     → 複数チャンネルが同時に失敗していれば X API クレジット枯渇(402)の可能性大（地雷#17）
設計:
  - 異常時のみメール。正常時は沈黙（毎日メールが来ると読まれなくなる）
  - 監視自体は絶対に落ちない（例外は握りつぶして exit 0）
  - DRY_RUN=1 なら送信せず本文を標準出力へ
"""
import os
import sys
import json
import ssl
import smtplib
import datetime
from email.header import Header
from email.mime.text import MIMEText

import requests

JST = datetime.timezone(datetime.timedelta(hours=9))
REPO = "imaraku/imaraku"
POSTED_SLOTS_FILE = "posted_slots.json"
ACTIONS_URL = f"https://github.com/{REPO}/actions"

# 投稿系 workflow（X に投稿するもの）。failure 集計の対象。
POSTING_WORKFLOWS = [
    "daily-tweet", "ranking-check", "category-ranking", "sale-picks",
    "mega-chance", "marathon-preannounce", "travel-campaign",
    "monthly-pay", "point-usage", "supersale-alert",
]

GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
MAIL_TO = os.environ.get("MAIL_TO", GMAIL_USER)
DRY_RUN = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "yes")


def daily_posted_today(today: datetime.date) -> list:
    """今日の日次投稿スロット一覧（無ければ空リスト）。"""
    try:
        with open(POSTED_SLOTS_FILE, encoding="utf-8") as f:
            return list(json.load(f).get(today.isoformat(), []))
    except Exception:
        return []


def today_failures(today: datetime.date) -> dict:
    """{workflow: failure回数} を今日(JST)分だけ集計。API不調時は空dict（判定は日次記録だけで行う）。"""
    result = {}
    for wf in POSTING_WORKFLOWS:
        try:
            r = requests.get(
                f"https://api.github.com/repos/{REPO}/actions/workflows/{wf}.yml/runs",
                params={"per_page": 10}, timeout=15,
                headers={"Accept": "application/vnd.github+json"},
            )
            if r.status_code != 200:
                continue
            n = 0
            for run in r.json().get("workflow_runs", []):
                t = datetime.datetime.fromisoformat(run["created_at"].replace("Z", "+00:00")).astimezone(JST)
                if t.date() == today and run.get("conclusion") == "failure":
                    n += 1
            if n:
                result[wf] = n
        except Exception:
            continue
    return result


def stale_channels(today: datetime.date, max_age_days: int = 3) -> list:
    """他チャンネルの投稿記録(dedupファイル)が古い＝「成功扱いだが実は投稿できていない」を検出。
    ranking/category は失敗しても exit 1 しない設計なので、workflow の conclusion では
    見抜けない。X API 枯渇(402)は全チャンネル同時に沈黙するため、これが決め手になる。"""
    stale = []
    def age(date_str):
        try:
            return (today - datetime.date.fromisoformat(date_str[:10])).days
        except Exception:
            return None
    try:
        with open("category_posted.json", encoding="utf-8") as f:
            a = age(json.load(f).get("last_posted_date", ""))
        if a is None or a > max_age_days:
            stale.append(f"カテゴリTOP1（最終 {a}日前）" if a is not None else "カテゴリTOP1（記録なし）")
    except Exception:
        pass
    try:
        with open("posted_ip_history.json", encoding="utf-8") as f:
            dates = [v for v in json.load(f).values() if isinstance(v, str)]
        a = age(max(dates)) if dates else None
        if a is None or a > max_age_days:
            stale.append(f"急上昇ランキング（最終 {a}日前）" if a is not None else "急上昇ランキング（記録なし）")
    except Exception:
        pass
    return stale


def build_mail(today: datetime.date, slots: list, failures: dict, stale: list) -> tuple:
    multi = len(failures) >= 2 or (not slots and stale)
    subject = f"【今楽】X投稿が止まっています（{today.month}/{today.day}）"
    checked_at = datetime.datetime.now(JST).strftime("%m/%d %H:%M")
    lines = [
        f"今楽の自動投稿に異常があります（点検対象日 {today.isoformat()} / 点検実行 {checked_at} JST）。",
        "",
        f"■ 今日の日次ツイート: {len(slots)}本" + ("（posted_slots に記録なし）" if not slots else f" {slots}"),
    ]
    if failures:
        lines.append("■ 今日 failure になった投稿系 workflow:")
        for wf, n in sorted(failures.items()):
            lines.append(f"   - {wf} ×{n}")
    else:
        lines.append("■ 今日の workflow failure: 取得できず／なし（run自体が無い可能性）")
    if stale:
        lines.append("■ 投稿記録が数日止まっているチャンネル（成功扱いでも実は投稿できていない）:")
        for s in stale:
            lines.append(f"   - {s}")
    lines += ["", "■ 判定と対処:"]
    if multi:
        lines += [
            "   複数チャンネルが同時に失敗 → X API クレジット枯渇(402)の可能性が高い（地雷#17）",
            "   → https://console.x.com → Billing で残高を確認して補充してください",
            "   （補充すれば次のスロットから自動で投稿が再開します。コード変更は不要）",
        ]
    else:
        lines += [
            "   日次だけの失敗 → コード側の問題の可能性。相棒(Claude)に「投稿失敗の原因究明」を依頼してください",
            "   （念のため https://console.x.com のクレジット残高も確認を）",
        ]
    lines += ["", f"■ Actions: {ACTIONS_URL}", "", "— 今楽 健康監視（health_check.py）"]
    return subject, "\n".join(lines)


def send_mail(subject: str, body: str) -> None:
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = GMAIL_USER
    msg["To"] = MAIL_TO
    context = ssl.create_default_context()
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
        server.starttls(context=context)
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.send_message(msg)
    print(f"✅ 警告メール送信 → {MAIL_TO}")


def main() -> None:
    now = datetime.datetime.now(JST)
    # 点検対象日 = 「23:30 の点検が cron 遅延で日付を跨いでも前日を見る」ため 6時間戻した日付。
    # 2026-09-19 23:30 の点検が 9/20 0時過ぎに着地し「今日(9/20)は0本」と誤報した事故の対策。
    today = (now - datetime.timedelta(hours=6)).date()
    print(f"=== 今楽 健康監視 {now.strftime('%Y-%m-%d %H:%M JST')}（点検対象日: {today}）===")
    slots = daily_posted_today(today)
    failures = today_failures(today)
    stale = stale_channels(today)
    print(f"  今日の日次投稿: {slots or 'なし'} / failure: {failures or 'なし'} / 停滞: {stale or 'なし'}")

    if slots and not failures:
        print("  → 正常。メールなし")
        return
    if slots and failures:
        # 日次は出ているが他が落ちた日。単発の cron 遅延等でも起きるため、2件以上の失敗のみ通知
        if sum(failures.values()) < 2:
            print("  → 軽微（failure 1件・日次は正常）。メールなし")
            return

    subject, body = build_mail(today, slots, failures, stale)
    if DRY_RUN or not (GMAIL_USER and GMAIL_APP_PASSWORD):
        print("  [DRY RUN / 認証なし] 送信せず本文を表示:\n")
        print(subject); print(body)
        return
    try:
        send_mail(subject, body)
    except Exception as e:
        print(f"  ⚠️ メール送信失敗: {e}", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # 監視は絶対に落とさない
        print(f"⚠️ health_check 例外: {e}", file=sys.stderr)
    sys.exit(0)
