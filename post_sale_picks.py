#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""セール文脈まとめ（A案）: 大型セール開催中、今の売れ筋を1日1回まとめ投稿する。

daily-tweet(エントリー喚起) / supersale-alert(開幕告知) / ranking(個別速報) とは
角度を変え、「今このセールで売れている商品」を数点まとめて紹介する販促枠。

── 仕様 ──
- 起動: 大型セール(スーパーSALE or マラソンpointup)開催中のみ。1日1回(dedup)。
- 時間: 14-15時JST想定（昼12・夕18 の daily スロットの“間”で露出を分散）。窓外は何もしない。
- 商品: 楽天Ichiba Ranking(総合)の上位を取得し aff 化。280字に収まる範囲で 2-3 点。
- リンク: 各商品の aff リンク + 「エントリーまとめは今楽」サイトリンク（常に正しい・ブランド導線）。
- graceful: 商品が取れない / 非開催 / 投稿済 / 窓外 / 280字超 は何もしない（誤投稿しない）。

── 再利用（DRY）──
楽天ランキング取得 fetch_top_items（hits≤20クランプ=地雷#10対策込み）、aff()、
Cloudflare対策済みの post_tweet（地雷#15対策込み）を post_category_ranking から import。
"""
import os
import re
import sys
import json
import datetime

# 検証済みの取得 / アフィリエイト / 投稿ロジックを再利用（地雷#10/#15 対策込み）
from post_category_ranking import fetch_top_items, aff, post_tweet
from hashtag_helper import hashtags

JST = datetime.timezone(datetime.timedelta(hours=9))
STATUS_FILE   = "campaign_status.json"
POSTED_FILE   = "sale_picks_posted.json"
SITE_URL_BASE = "https://imaraku.github.io/imaraku/imaraku.html"
GENERAL_GENRE = 0     # 総合ランキング
MAX_PICKS = 3
MIN_PICKS = 2
NUM_MARKS = "①②③④⑤"


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _wlen(text: str) -> int:
    """X 加重長の近似（URL=23, 非ASCII=2, ASCII=1）。"""
    w = 0
    tmp = text
    for u in re.findall(r'https?://\S+', text):
        tmp = tmp.replace(u, '', 1)
        w += 23
    for ch in tmp:
        w += 1 if ord(ch) < 0x1100 else 2
    return w


def _short(name: str, limit: int = 18) -> str:
    """長い楽天商品名を limit 文字に丸める。"""
    name = " ".join((name or "").split())
    return name if len(name) <= limit else name[:limit - 1] + "…"


def sale_context(status: dict):
    """開催中の大型セール名を返す。無ければ None。"""
    if status.get("supersale"):
        return "楽天スーパーSALE"
    if status.get("marathon_pointup"):
        return "お買い物マラソン"
    return None


def build_tweet(sale_name: str, picks: list, now: datetime.datetime):
    """280字に収まる範囲で 3→2 点入れたまとめツイートを作る。収まらなければ None。"""
    site = f"{SITE_URL_BASE}?d={now.strftime('%Y%m%d')}"
    tags = hashtags(['core', 'supersale', 'ranking'], now=now, max_tags=3)
    for n in range(min(MAX_PICKS, len(picks)), MIN_PICKS - 1, -1):
        head = f"🛒{sale_name}で今売れてるのはコレ👇\n\n"
        body = "".join(
            f"{NUM_MARKS[i]} {_short(picks[i]['name'])}\n{aff(picks[i]['url'])}\n"
            for i in range(n)
        )
        tail = f"\nエントリーまとめは今楽👇\n{site}\n{tags}"
        text = head + body + tail
        if _wlen(text) <= 278:
            return text
    return None


def main():
    now = datetime.datetime.now(JST)
    force = os.environ.get("SALE_PICKS_FORCE", "").lower() in ("1", "true", "yes")

    # 時間ガード: 14-15時JST想定。cron遅延の余裕で 13-17時台まで許容。窓外は何もしない。
    if not force and not (13 <= now.hour <= 17):
        print(f"時間窓外({now.hour}時JST) → 何もしない")
        return

    status = load_json(STATUS_FILE, {})
    sale_name = sale_context(status)
    if not sale_name:
        print("大型セール非開催（supersale / marathon_pointup いずれもfalse）→ 何もしない")
        return

    # クレジット節約(2026-06-10): 売れ筋まとめは「最強日」(セール×0と5のつく日)に集中。
    # カテゴリTOP3 / 急上昇ランキングと商品紹介が重複するため、毎セール日→最強日のみに絞る。
    if not force and now.day % 5 != 0:
        print(f"  最強日(0と5のつく日)でない（{now.day}日）→ スキップ（クレジット節約）")
        return

    today = now.strftime("%Y-%m-%d")
    posted = load_json(POSTED_FILE, {})
    if posted.get("date") == today and not force:
        print(f"本日({today})は投稿済 → スキップ")
        return

    raw = fetch_top_items(GENERAL_GENRE, hits=20)
    picks = [p for p in raw if p.get("name") and p.get("url")][:MAX_PICKS]
    if len(picks) < MIN_PICKS:
        print(f"売れ筋が {len(picks)} 件しか取れず → スキップ（誤投稿回避）")
        return

    text = build_tweet(sale_name, picks, now)
    if not text:
        print("280字に収まらず → スキップ")
        return

    print(f"\n[セール文脈まとめ]\n{text}\n")
    if post_tweet(text):
        save_json(POSTED_FILE, {"date": today, "sale": sale_name})
        print("✅ 投稿成功・履歴更新")
    else:
        print("❌ 投稿失敗 → exit 1（GitHub失敗通知用）", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
