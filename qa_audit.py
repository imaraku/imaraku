#!/usr/bin/env python3
"""
qa_audit.py — 「カナ」: 点検係スタッフ
今楽プロジェクトの自動運用状態を毎朝チェックし、異常があれば報告する。

カナの仕事は、相棒と俺（相棒2号）が見落としたエラー・取りこぼしを
別の目で拾い上げること。ガンガン進める2人を後ろから支える役回り。

【点検項目】
  ① new_campaigns.json: ノイズパターン混入チェック
  ② expired_entries.json: 鮮度チェック（45日以上更新なし＝怪しい）
  ③ marathon_schedule.json: campaign_status との整合性
  ④ pay_campaigns.json: URL生存確認
  ⑤ posted_slots.json: 直近7日の投稿カバレッジ
  ⑥ seasonal_events.json: 来年分の active_periods カバー
"""

import os
import re
import sys
import json
import datetime
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

JST = datetime.timezone(datetime.timedelta(hours=9))
REPORT_FILE = "qa_report.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept-Language": "ja,en;q=0.9",
}


def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


# ── 個別チェック関数 ─────────────────────────────────────────────────

def check_new_campaigns_quality() -> dict:
    """new_campaigns.json に明らかなノイズが混入していないか"""
    data = load_json("new_campaigns.json", [])
    issues = []
    NOISE_TAILS = ["はこちら", "もっと見る", "詳細はこちら"]
    NOISE_HEADS = ["・", "（", "(", "【"]
    for c in data:
        name = c.get("name", "")
        url = c.get("url", "")
        # 短すぎ・長すぎ
        if len(name) < 5:
            issues.append(f"name短すぎ: '{name}' → {url}")
        # ノイズ末尾
        if any(name.endswith(t) for t in NOISE_TAILS):
            issues.append(f"誘導文末尾: '{name}' → {url}")
        # ノイズ先頭
        if any(name.startswith(h) for h in NOISE_HEADS):
            issues.append(f"句読点始まり: '{name}' → {url}")
        # URLにキャンペーン要素がない
        if "/campaign/" not in url and "/coupon/" not in url:
            issues.append(f"非キャンペーンURL: {url}")
    return {
        "name": "new_campaigns ノイズチェック",
        "status": "WARN" if issues else "PASS",
        "count": len(data),
        "issues": issues,
    }


def check_expired_freshness() -> dict:
    """expired_entries.json が長期間更新されてないと、検出ロジック失敗の可能性"""
    data = load_json("expired_entries.json", {})
    if not data:
        return {
            "name": "expired_entries 鮮度",
            "status": "INFO",
            "count": 0,
            "issues": ["expired_entries.json が空（自然な状態の可能性あり）"],
        }
    today = datetime.datetime.now(JST).date()
    cutoff = today - datetime.timedelta(days=45)
    stale = []
    for url, info in data.items():
        ended_at = info.get("ended_at", "")
        try:
            d = datetime.date.fromisoformat(ended_at)
            if d < cutoff:
                stale.append(f"{ended_at} 古い: {url}")
        except Exception:
            stale.append(f"日付不正 ({ended_at}): {url}")
    return {
        "name": "expired_entries 鮮度",
        "status": "WARN" if stale else "PASS",
        "count": len(data),
        "issues": stale,
    }


def check_marathon_schedule() -> dict:
    """campaign_status.marathon=true なら schedule が現在進行中であるはず"""
    status = load_json("campaign_status.json", {})
    schedule = load_json("marathon_schedule.json", {})
    issues = []
    now = datetime.datetime.now(JST)
    if status.get("marathon"):
        p_end = schedule.get("pointup_end")
        if not p_end:
            issues.append("marathon=true だが schedule.pointup_end 未設定")
        else:
            try:
                end_dt = datetime.datetime.fromisoformat(p_end)
                if end_dt < now:
                    issues.append(f"marathon=true だが既に期間外: pointup_end={p_end}")
            except Exception:
                issues.append(f"pointup_end の日付パース失敗: {p_end}")
    return {
        "name": "marathon 整合性",
        "status": "FAIL" if issues else "PASS",
        "issues": issues,
    }


def check_pay_campaigns_alive() -> dict:
    """pay_campaigns.json のURL生存確認"""
    data = load_json("pay_campaigns.json", {})
    urls = data.get("campaigns", [])
    if not urls:
        return {"name": "pay_campaigns URL生存", "status": "INFO", "count": 0, "issues": []}

    dead = []
    def _check(url):
        try:
            r = requests.head(url, headers=HEADERS, timeout=8, allow_redirects=True)
            if r.status_code >= 400:
                # HEAD非対応の場合 GET でも試す
                r = requests.get(url, headers=HEADERS, timeout=8, allow_redirects=True)
            return (url, r.status_code)
        except Exception as e:
            return (url, str(e))

    with ThreadPoolExecutor(max_workers=8) as ex:
        for fut in as_completed([ex.submit(_check, u) for u in urls]):
            url, code = fut.result()
            if isinstance(code, int) and code >= 400:
                dead.append(f"HTTP {code}: {url}")
            elif isinstance(code, str):
                dead.append(f"取得失敗 ({code}): {url}")

    return {
        "name": "pay_campaigns URL生存",
        "status": "WARN" if dead else "PASS",
        "count": len(urls),
        "issues": dead,
    }


def check_posted_slots_coverage() -> dict:
    """直近7日の投稿カバレッジ確認（穴があると投稿頻度が落ちている）"""
    data = load_json("posted_slots.json", {})
    today = datetime.datetime.now(JST).date()
    issues = []
    expected_slots = ["0", "12", "18", "20"]
    for i in range(7):
        d = today - datetime.timedelta(days=i)
        d_str = d.isoformat()
        slots = data.get(d_str, [])
        missing = [s for s in expected_slots if s not in slots]
        # 当日は途中なので評価しない
        if i == 0:
            continue
        if not slots:
            issues.append(f"{d_str}: 投稿0件")
        elif len(missing) >= 2:
            issues.append(f"{d_str}: 欠スロット {missing}")
    return {
        "name": "posted_slots カバレッジ",
        "status": "WARN" if issues else "PASS",
        "issues": issues,
    }


def check_seasonal_events() -> dict:
    """seasonal_events.json の active_periods が期限切れになってないか（来年分も必要）"""
    data = load_json("seasonal_events.json", {})
    events = data.get("events", [])
    next_year = (datetime.datetime.now(JST).year) + 1
    issues = []
    for ev in events:
        periods = ev.get("active_periods", [])
        years_covered = set()
        for p in periods:
            try:
                y = datetime.datetime.fromisoformat(p["start"]).year
                years_covered.add(y)
            except Exception:
                pass
        if next_year not in years_covered:
            issues.append(f"{ev.get('key')}: {next_year}年分の active_periods 未設定")
    return {
        "name": "seasonal_events 期間カバレッジ",
        "status": "WARN" if issues else "PASS",
        "count": len(events),
        "issues": issues,
    }


# ── レポート出力 ─────────────────────────────────────────────────

def main():
    now = datetime.datetime.now(JST)
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"📋 カナ → 点検レポート  {now.strftime('%Y-%m-%d %H:%M JST')}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    checks = [
        check_new_campaigns_quality,
        check_expired_freshness,
        check_marathon_schedule,
        check_pay_campaigns_alive,
        check_posted_slots_coverage,
        check_seasonal_events,
    ]

    results = []
    fail_count = 0
    warn_count = 0
    for fn in checks:
        try:
            r = fn()
            results.append(r)
            if r["status"] == "FAIL":
                fail_count += 1
            elif r["status"] == "WARN":
                warn_count += 1
        except Exception as e:
            results.append({"name": fn.__name__, "status": "ERROR", "issues": [str(e)]})
            fail_count += 1

    # コンソール出力（友好的トーン）
    icon_map = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌", "INFO": "ℹ️", "ERROR": "💥"}
    for r in results:
        icon = icon_map.get(r["status"], "?")
        print(f"\n{icon} {r['name']}: {r['status']}")
        if r.get("count") is not None:
            print(f"   件数: {r['count']}")
        for issue in r.get("issues", []):
            print(f"   • {issue}")

    # 総括（カナのコメント）
    print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    if fail_count == 0 and warn_count == 0:
        print("🟢 カナ：全項目クリアです。今楽は健康ですよ ✨")
    elif fail_count > 0:
        print(f"🔴 カナ：緊急 {fail_count} 件 / 注意 {warn_count} 件 → 相棒さん確認お願いします")
    else:
        print(f"🟡 カナ：注意 {warn_count} 件 → しばらく様子見でいいかも")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # JSON 保存（履歴・通知連携用）
    report = {
        "audited_at": now.isoformat(),
        "auditor": "カナ",
        "summary": {"fail": fail_count, "warn": warn_count, "total_checks": len(results)},
        "results": results,
    }
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n📄 詳細レポート: {REPORT_FILE}")


if __name__ == "__main__":
    main()
