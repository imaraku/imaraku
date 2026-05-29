# 今楽（imaraku）プロジェクト — Claude Code 引き継ぎドキュメント

## 👋 引き継ぎClaudeへ：最初に知っておくべきこと

**運営者は @ima_raku_entry（mochiki.kengo@gmail.com）。一人称「相棒」で呼んでくる。
カジュアルなトーンで頼むぜ系の口調。技術的な細かい指示よりも「違和感を伝える」スタイル。
`お疲れ！相棒！` `ナイス！` `頼むぜ！` みたいなノリで返してOK。**

### 🤝 チームメンバー（3人体制）
- **相棒** (運営者): 違和感センサー / ドメイン知識 / 優先順位判断 / オフ会等の人脈構築
- **俺** (引き継ぎClaude): コード実装 / 調査 / 自動化の組み立て
- **カナ** (`qa_audit.py`): 自動運用状態の常時監視・異常検出を担当する独立スタッフ
  - 毎朝 8:00 JST に静かに巡回
  - 全項目クリア時は黙ってレポート更新
  - WARN/FAIL を発見した時は commit メッセージで報告
  - 相棒と俺がガンガン進めて取りこぼした事を後ろから拾う役回り

### 必読セクション（順番に）
1. **🚨 踏むな地雷リスト**（このすぐ下）— 過去のセッションで実際に踏んだ事故集
2. **自動化レジストリ**（中盤）— 二重投稿の元凶になるので新規自動化前に必ず読む
3. **ファイル構成** — JSONファイルがそれぞれ何を管理してるか

### 🔥 チームの行動指針（相棒の言葉より 2026-05-23）
> 「何か行動すれば、ミスは当然起きる。そこをどう乗り越えるかが大事。」

俺らのチームは「ミスゼロ」を目指してない。「**ミス → 学び の速度を最大化**」を目指してる。
- 動かす → ミスる → 即気付く（相棒の違和感センサー）→ 即直す（俺のコード）→
  教訓を残す（CLAUDE.md 地雷集）→ カナが裏で取りこぼし救出
- この回転速度が今楽の真の強み。境界を押せるから新しい発見が生まれる。
- 慎重設計で「何も起きない安全な静寂」より、動いて学ぶサイクルを選ぶ。

### 作業時の鉄則
- **コード論理だけでなく実挙動も毎回確認する**（過去にこの怠慢で2回事故った）
- **デフォルト値は保守的に**（不明 = 非表示／非開催）— 攻めすぎると誤表示する
- **大きな仕様変更は段階的に**（X投稿に直結するので、誤判定の影響が大きい）
- **commit する前に、その変更が誤表示・誤投稿しないか想像する**
- 相棒は git の細かい操作はやや苦手なので、push までの手順を**コピペ可能なブロック**で渡す

### 環境
- macOS / Mac mini（相棒の端末）
- ローカル Python は 3.9（型ヒント `X | None` 不可。CIは 3.11 でOK）
- リポジトリは `/Users/mochikikengo/Documents/imaraku/`
- Git は `osxkeychain` 認証。PAT は `imaraku-p` トークン（`workflow` スコープ追加済 2026-04-27）

---

## プロジェクト概要

**今楽（imaraku）** は楽天市場のキャンペーンエントリーをまとめたアグリゲーターサイト。

- **サイトURL**: https://imaraku.github.io/imaraku/imaraku.html
- **GitHubリポジトリ**: https://github.com/imaraku/imaraku
- **Xアカウント**: @ima_raku_entry
- **運営者メール**: mochiki.kengo@gmail.com

---

---

## 🚨 引き継ぎ時 必読：踏むな地雷リスト

過去のセッションで実際に踏んだ事故。同じミスを繰り返さないこと。

### ⚠️ 1. 「終了しました」キーワード単独で expired 判定するな
楽天のページは **過去キャンペーンへの言及**（例: "前回マラソンは終了しました 次回は…"）で
このキーワードを含むため、単独マッチで判定するとアクティブなキャンペーンを大量誤検出する。

✅ **正解**: STRICT_END_PHRASES（「**本**キャンペーンは終了」「**この**キャンペーンは終了」）
                + 「お買い物ありがとうございました」等 GRATITUDE_PHRASES で判定。
                さらに「エントリーする」ボタン等のアクティブ要素が無いことも確認。

### ⚠️ 2. URL生存チェック対象に showOnDays / campaignKey 付きエントリーを含めるな
- `showOnDays:[1]` 等の特定日URL は対象外日に 404 を返すため、誤って expired 入りする
- `campaignKey` 持ちは campaign_status.json で別系統管理されているので二重管理になる

✅ **正解**: `extract_html_entry_urls()` でブロック単位で `showOnDays|campaignKey` を含む
              エントリーをスキップ。検査対象 77→31件に絞り込み。

### ⚠️ 3. imaraku.html の CAMPAIGN_STATUS ハードコード追加し忘れ → 季節キャンペーン誤表示
ハードコード defaults に無いキー（pokemon_lottery, ochugen 等）は `hasOwnProperty=false` で
旧ロジックでは「表示扱い」されていた。

✅ **正解**: `applyFilter` で `CAMPAIGN_STATUS[key] !== true` で判定。未定義は非表示扱い。

### ⚠️ 4. detect_new_campaigns はカテゴリナビを大量誤検出する
楽天クーポンTOPには `/coupon/sweets`, `/coupon/pc` 等のカテゴリ一覧URLが大量にある。
これらは個別キャンペーンじゃないので追加するとサイトが汚染される。

✅ **正解**: `is_category_nav_url()` で除外、`is_invalid_campaign_name()` で名前バリデーション、
              同名重複排除、1ラン最大10件で暴走防止（6重ガード）。

### ⚠️ 5. GitHub Actions の cron は best-effort で取りこぼす
時間ピッタリの cron は混み合うほど drop される。3本冗長化しても全drop することがある。

✅ **正解**: `daily-tweet.yml` は `0,30 * * * *`（毎時2回 = 48回/日）まで密化し、
              スクリプト側 `posted_slots.json` で「対象スロット & 未投稿」のみ実投稿。

### ⚠️ 6. check-campaigns が10分占有 → 他workflow を弾く
77URL の逐次fetch で run時間が 53s → 600s に肥大化、daily-tweet の cron drop 連鎖を引き起こした。

✅ **正解**: ThreadPoolExecutor max_workers=20 で並列化（~30s）。timeout-minutes も全workflow で設定済。

### ⚠️ 7. fetch失敗 = expired 復活 ではない
URL生存チェックで取得失敗（ネットワーク不調）した時に既存expired を「復活」させると、
本物の終了URLが瞬間的に site に再表示されてしまう。

✅ **正解**: `_check_one_url` は `"expired:理由" / "active" / "unknown"` の3値ステータス。
              unknown のときは既存expired状態を維持。

### ⚠️ 8. ハードコードURLから消えたエントリーは expired 一覧から自動削除する
imaraku.html から URL を消した時、expired_entries.json に永遠に残ってしまう問題があった。

✅ **正解**: マージ時に「`existing_expired` にあるが今回チェック対象 (active+unknown+new_expired) に
              含まれない URL は削除」のロジック追加済み。

### ⚠️ 9. PAT に workflow スコープが無いと .github/workflows/*.yml が push できない
2026-04-25 にこれを踏んで、workflow ファイル変更をコミットから外す回避策で対処した。
現在の PAT (`imaraku-p`) には workflow スコープを追加済み（2026-04-27）。

### ⚠️ 10. 楽天ランキングAPI (openapi.rakuten.co.jp/ichibaranking) の仕様マップ
**境界条件メモ**（推奨: 諦める前に「単体 vs 組み合わせ」を切り分けて再検証）。
2026-05-12 に validation 厳格化、2026-05-20 にカテゴリ別取得が実は通ることを再確認した。
仕様の境界が時々変わる前提で、**1-2 週間に一度は debug log で response body を確認**する運用が安全。

**OK な組み合わせ**:
- `genreId=0` 単体 + `period=realtime` + `hits<=20` (page 省略) → 総合 TOP20
- `genreId=N` 単体 (N=各大ジャンル) + `period=realtime` + `hits<=30` (page 省略) → ジャンル別 TOP30
  - 既知の通る ID: 0(総合) / 100533(食品) / 100804(スイーツ) / 100934(医薬品) /
    100938(健康) / 100939(日用品) / 101213(ペット) / 101240(CD/DVD) /
    101266(本雑誌) / 200162(テレビ家電) / 562637(おもちゃ)
- `sex=0 or 1` 単体 + `age=20/30/40` + `period=実は daily/weekly/monthly のみ?` → 要再検証
  - 旧メモでは 404 だったが、もしかしたら period の組み合わせ次第で通る可能性

**NG な組み合わせ**（再検証する価値は周期的に確認）:
- `genreId` と `sex` 同時送信 → 400 (`no permit setting genreId and sex parameter at the same time`)
- `sex=2` (両性？) → 400 (`set sex from 0,1`)
- `sex` 単体（`age` なし）→ 400 (`must set age parameter in 20,30,40`)
- `period=realtime` + `page>=2` → 400 (realtime は pagination 非対応)
- `period=realtime` + `hits>20` → 400 (realtime は hits 上限 20)
- `period=daily/weekly/monthly` 全般 → 400 (`set period from realtime`)
  - これは「実は openapi.rakuten.co.jp/ichibaranking は **realtime 専用**」の現れ
  - daily/weekly/monthly が欲しければ別エンドポイント or 旧 API を探す必要

**現運用** (`check_ranking.py` / `fetch_ranking_via_api`):
```python
axes = [
    ("総合",        {"genreId": 0}),       # 楽天全体
    ("おもちゃ",    {"genreId": 562637}),  # ポケカ・たまごっち・ドロップシール
    ("CD/DVD",      {"genreId": 101240}),  # Snow Man/アイドル/邦楽
    ("本雑誌",      {"genreId": 101266}),  # ONE PIECE magazine 等
    ("テレビ家電",  {"genreId": 200162}),  # Switch 2 ソフト・新作ガジェット
    ("食品",        {"genreId": 100533}),  # 限定スイーツ・コラボ食品
]
# hits=20, page 省略, sex/age 渡さない、period=realtime（デフォルト）
```
6軸並列で ~140 件取得。総合 TOP30 だけだと売り切れ商品ばかり拾うが、
**カテゴリ別 TOP30 はトラフィック分散でまだ在庫がある段階で検出**できる。

**🔁 再発事例（2026-05-28）— hits=30 を再び書いてしまった**:
カテゴリTOP1 リファクタ (`6bbdcca`) で `post_category_ranking.py` の
`fetch_top_items(hits=...)` 既定を **20→30 に変更**してしまい（「TOP1 だけ使うが
フィルタ後の余裕で 30 取得」という善意の判断）、realtime API が全リクエスト 400 →
`items=[]` → 毎回「該当アイテム不足」スキップ。**カテゴリTOP1 が 5/28・5/29 と
連続で投稿ゼロ**になった（`category_posted.json` が 5/27 "食品TOP3" で凍結したのが痕跡）。
`check_ranking.py` の `fetch_top_ranked_item` も `min(hits,30)` で同じ穴があり、
常連ツイートが毎回 search URL フォールバックに落ちていた。
✅ **恒久対策**: hits は **fetch 関数の入口で `min(hits, 20)` に clamp** する安全弁を
両ファイルに追加。caller が誤って 30 を渡しても二度と 400 を踏まない。
✅ **教訓**: 「TOP3→TOP1 で余裕を持って多めに取る」発想は realtime の hits≤20 制約と
衝突する。hits を触る変更は地雷#10 を必ず想起すること。

### ⚠️ 11. YAML/JSON を Edit ツールで操作したら必ず構文検証してから push
2026-05-20 に daily-tweet スロット節約のため Edit でcron 行差し替えをしたが、
古い `# 手動テスト用 / workflow_dispatch:` 2行を残したまま新しい同じ2行も
追加してしまい、`on:` 直下に `workflow_dispatch:` が**2回出現**する状態でpush。

YAML はマッピング内のキー重複を許容しないため `on:` ブロック全体が無効化、
GitHub Actions が「No jobs were run」を返し、5/20 18:19 〜 19:35 の **約75分間に
8 run 全てが失敗**した（cron も workflow_dispatch も発火不能）。

✅ **正解（運用ルール化）**:
```bash
# YAML
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/X.yml'))"
# venv に yaml が無ければ簡易チェック:
python3 -c "
import sys
lines = open('.github/workflows/X.yml').read().split('\\n')
keys = [l.strip().rstrip(':') for l in lines if l.startswith('  ') and l.rstrip().endswith(':')]
from collections import Counter
dup = {k:c for k,c in Counter(keys).items() if c > 1}
assert not dup, f'duplicate keys: {dup}'
"
# JSON
python3 -m json.tool < path/to/file.json > /dev/null
```

✅ **異常検知のヒント**:
- 「Run failed: ...workflow.yml ... No jobs were run」メールが連発したら
  **真っ先に workflow ファイルの構文を疑う** (run の中ではなく workflow 自体が壊れてる)
- Edit で複数行の差し替えをした直後は、変更前後の行数を git diff で確認する

### ⚠️ 12. X (Twitter) は同一テンプレ文章を約30日窓で 403 で弾く
2026-05-21 14:53 JST に daily-tweet の `tweet_marathon_entry_only()` が
"403 You are not permitted to perform this action" で失敗した。

【真因】
完全固定文のテンプレートは、前回マラソンのエントリー期間に同じ文章を 4-6 回
投稿済 → X の重複投稿検出（~30日窓）にヒット。

✅ **正解（運用済）**:
`post_daily_tweet.py` に `daily_lead_in()` ヘルパーを定義し、全テンプレ先頭に
「📅 5/21(木) 🌞 お昼チェック」「📅 5/21(木) 🌆 帰り道チェック」の日替わり×
スロット別文脈行を挿入。これで:
- 日付が変わる → 翌日同じテンプレでもユニーク
- 12時/18時で挨拶絵文字が変わる → 同日2回投稿でもユニーク

【適用済テンプレ】21 種類:
marathon_kickoff / big_chance / entry_only / normal / wonderful_day / ichiba_day /
zero_five_day / month_end_eve / month_end_last / triple_combo (3種) /
marathon_x_victory / w_victory_x_special / single_victory_x_special /
w_victory / eagles / vissel / adidas / nike / normal

【適用しないもの】
- 年1回テンプレ (new_year / valentine / white_day / christmas 等) → 365日空くから安全
- countdown 系 (`days_until` で自然にユニーク) → 既に変動的
- 急上昇ランキングツイート (商品名で自然にユニーク)
- カテゴリTOP3 (毎日カテゴリが回るので自然にユニーク)

【今後新しいテンプレを足すとき】
**完全固定文は禁止**。daily_lead_in() を必ず先頭に挿入するか、可変要素を
本文に組み込む。新テンプレ追加時は dedup リスクを必ず確認。

### ⚠️ 13. 楽天レガシーAPI (app.rakuten.co.jp) は新規 applicationId を受け付けない
2026-05-23 に「カテゴリ別 TOP100 まで深掘り」を狙ってレガシー Ranking API
(`app.rakuten.co.jp/services/api/IchibaItem/Ranking/20170628`) を試したが、
全リクエストが `400 specify valid applicationId` で拒否された。

これは Search API (5/12 セッションで同じく拒否) と同パターンで、
楽天が新規発行の applicationId を旧 API endpoint で受け付けない仕様変更を行った模様。
新 API (`openapi.rakuten.co.jp`) しか使えないが、新 API は:
- realtime 専用 (period=daily/weekly/monthly は 400)
- pagination 非対応 (page>=2 は 400)
- 1ジャンル TOP30 が事実上の上限

✅ **対応**: TOP100 拡張は諦め、6 ジャンル realtime ランキング（合計 ~170 件）で運用継続。
新しい applicationId 取得しても旧 API では救われないため、構造的に解決不能。
将来 Rakuten が新 API に pagination を追加すれば自動的に拡張余地が生まれる。

### ⚠️ 14. 「前回NGだった」結論は周期的に再検証する
2026-05-12 → 12 に「sex+genreId は無理」「カテゴリ別ランキングは無理」と
結論づけた結果、1週間「総合 TOP30 のみ」運用で売り切れ通知が頻発していた。
2026-05-20 に相棒の違和感センサーで再チャレンジ → 「genreId 単体なら OK」を発見、
売り切れ前のレア検出が可能に。

✅ **教訓**:
- API 仕様は数日〜数週間単位で変わる。debug log で body を残す習慣を保つ
- 「sex+genreId 同時は NG」のように **境界条件付きで** メモを残す
  （単に「カテゴリ別はNG」と書くと、次の俺が試さなくなる）
- 「諦めパターンも CLAUDE.md に書く」は両刃の剣。**書くなら必ず "条件下で NG"** にする

### ⚠️ 11. 「scheduled job が success」を信用するな — 中身を見ろ
地雷#10 の時、GitHub Actions の run は全て緑 (✅ success) だった。けど **API 取得が 0件**
で実質何もしていない空回り。相棒の違和感センサー（「最近投稿ないな」）が無かったら
1週間気付けなかった可能性が高い。

✅ **教訓**:
- API レスポンスは **必ず `r.text[:250]` レベルで error body をログに残す**（地雷#10 の真因
  は debug log で初めて見えた）
- カナの巡回 (`qa_audit.py`) には「run は緑だが `ranking_cache.json` が N時間更新されてない」
  系の検知ロジックを将来的に足すと再発防止になる
- 「コードは正しく動いてる風」「成功で返ってる」≠「ユーザー価値が出ている」

### 🔗 補足: 動的URL（月毎に日付が変わるキャンペーン）の自動追従
楽天の一部キャンペーンは URL 末尾が `/YYYYMMDD/` 形式で月毎に変わる
（例: `mobiledeal/20260509/`）。次のマラソンで URL が変わると、ハードコード
URL を踏むユーザーが 404 を見る + `check_campaigns.py` が「終了」誤判定する事故が起きる。

✅ **対策**: `discover_dynamic_urls()` が `superdeal/` トップから最新の日付付きURL
を正規表現で抽出し、`dynamic_urls.json` に書き出す。
- `check_campaigns.py` 側: CAMPAIGNS 定義の URL を実行時に上書き → 状況チェックも常に最新URLで実施
- `imaraku.html` 側: ページロード時に `dynamic_urls.json` を fetch し、
  `data-campaign-key` 一致するカードの href / data-entry-url / bulk-check data-url
  を最新URLに差し替え

新しい日付付きキャンペーン（superdeal_4h 系等）を増やすときは `discover_dynamic_urls()`
内に正規表現を追加するだけ。

### 🛠️ 補足: Rakuten ランキングAPI デバッグの定石
- ローカルに RAKUTEN_APP_ID/ACCESS_KEY が無いので、検証は GitHub Actions の
  `workflow_dispatch` で manual run → raw logs 確認 が最速ループ
- raw logs は Azure blob 署名 URL に redirect されるので Chrome MCP の
  `javascript_tool` で `document.body.innerText.match(...)` すると効率良く取れる
- 修正→push→manual run→ログ確認 を 5分1サイクルで回せると、API 仕様変更も即日吸収可能

---

## ファイル構成

```
imaraku/                        ← リポジトリルート
├── imaraku.html                ← メインサイト（GitHub Pages）
├── campaign_status.json        ← キャンペーン開催状況（GitHub Actionsが自動更新）
├── new_campaigns.json          ← 自動検出された新キャンペーン候補
├── expired_entries.json        ← 終了確定したハードコード済みエントリーURL集合
├── seasonal_events.json        ← 季節イベント（母の日／父の日等）の active_periods 定義
├── marathon_schedule.json      ← マラソンの正確な開始/終了時刻（自動抽出 or 手動）
├── posted_slots.json           ← daily-tweet の slot 別投稿実績（重複排除用）
├── kickoff_fired.json          ← マラソン kickoff 発火履歴（再発火防止）
├── preannounce_fired.json      ← 事前告知ツイート発火履歴（日次重複排除）
├── pokemon_lottery.json        ← ポケカ抽選の受付期間（手動メンテ）
├── dynamic_urls.json           ← 月毎に日付が変わる動的URL（mobiledeal 等）。check_campaigns.py が自動更新
├── ranking_cache.json          ← ランキングチェック用キャッシュ（自動生成）
├── ogp.png                     ← X/OGPリンクプレビュー画像 (1200x630)
├── check_campaigns.py          ← キャンペーン状態チェック（メイン）
├── post_daily_tweet.py         ← 日次ツイート（slot dedup ロジック含む）
├── post_marathon_alert.py      ← マラソン事前告知ツイート
├── check_ranking.py            ← 楽天ランキングチェック＆ツイート
└── .github/
    └── workflows/
        ├── check-campaigns.yml     ← 2時間ごと実行（URL生存チェック含む）
        ├── daily-tweet.yml         ← 毎時:00/:30 (48回/日 試行＋slot dedup)
        ├── marathon-preannounce.yml← 19:30/19:40/19:50 JST 冗長fire
        └── ranking-check.yml       ← :00/:30 で2倍冗長化済
```

---

## campaign_status.json のキー一覧

| キー | 説明 | デフォルト |
|---|---|---|
| `marathon` | お買い物マラソン（エントリー期間含む） | false |
| `marathon_pointup` | マラソン ポイントアップ期間中のみ true | false |
| `eagles` | 楽天イーグルス勝利ボーナス | false |
| `vissel` | ヴィッセル神戸勝利ボーナス | false |
| `biccamera` | 楽天BIC MegaBIC | true |
| `superdeal` | スーパーDEAL Days | true |
| `returnpurchaser` | 久しぶりの買い物クーポン | true |
| `newpurchaser` | 初めての買い物クーポン | true |
| `adidas` | adidasセール（常設ではない） | false |
| `nike` | NIKEセール（常設ではない） | false |
| `mobilebonus` | 楽天モバイル限定+2倍（常設ではない） | false |
| `repeat_purchase` | リピート購入 +1倍（マラソン期間中のみ開催） | false |
| `guerrilla` | ゲリラ 全店+1倍（不定期） | false |
| `superdeal_4h` | スーパーDEAL 4時間限定（マラソン期間中のみ開催） | false |
| `mobiledeal` | 楽天モバイル×スーパーDEAL（マラソン期間中のみ開催） | false |
| `pokemon_lottery` | 楽天ブックスのポケカ抽選（受付期間中のみ true） | false |
| `shop39` | 39ショップ キャンペーン（マラソン期と同期間で開催されることが多いが、開催されない月もあるため個別判定） | false |
| `mother_day` | 母の日特集（`seasonal_events.json` で期間制御） | false |
| `father_day` | 父の日特集（同上） | false |
| `ochugen` | お中元特集（同上） | false |
| `oseibo` | お歳暮特集（同上） | false |
| `osechi` | おせち特集（同上） | false |
| `xmas` | クリスマス特集（同上） | false |
| `valentine` | バレンタイン特集（同上） | false |
| `whiteday` | ホワイトデー特集（同上） | false |

⚠️ **注意**: 上記キーのうち `pokemon_lottery` から下は `imaraku.html` の
ハードコード `CAMPAIGN_STATUS` defaults には**含まれていない**。
applyFilter は `CAMPAIGN_STATUS[key] !== true` で「未定義 = 非開催扱い」にしているので
ハードコードに追記しなくても誤表示されない設計（地雷#3 参照）。

---

## imaraku.html の主要な仕組み

### アフィリエイトURL生成
```javascript
function aff(url) { ... }  // 楽天アフィリエイトIDを付与
```

### カードのプロパティ
```javascript
{
  name: "表示名",
  point: "+1%",
  url: "エントリーURL",
  essential: true,        // true = おすすめに表示 / false = 全部表示のみ
  campaignKey: "marathon",// campaign_status.jsonのキー。falseなら両モードで非表示
  demoteMarathon: true,   // true = マラソン期間中はおすすめから除外
  showOnDays: [5,10,15],  // 特定日のみ表示（0と5のつく日など）
  noAffiliate: true,      // true = aff()を通さない（外部ドメイン用）
}
```

### applyFilter ロジック
- `campaignKey` が指定されていて `CAMPAIGN_STATUS[campaignKey] === false` → 両モードで非表示
- `essential: false` → 全部表示のみ（おすすめには出ない）
- `demoteMarathon: true` かつ `marathon: true` → おすすめから除外

### お知らせバナーの表示ルール
1. マラソン ポイントアップ期間中 → 🟢 緑「マラソン開催中！今すぐ買いまわろう」
2. マラソン エントリー期間のみ → 🟡 黄「エントリー受付中！ポイントアップはまだ。先にエントリーだけしておこう」
3. W勝利（eagles & vissel） → 🔴 赤「W勝利！ポイント3倍！」
4. どちらか勝利 → 🔵 青「○○勝利！ポイント2倍！」
5. 特別日（0と5/18日） → 🟡 ゴールド表示

---

## ツイート優先度ロジック（post_daily_tweet.py）

```
1. マラソン（ポイントアップ中）× 特別日 → ビッグチャンスツイート
2. マラソン（ポイントアップ中）         → eギフト/Appleギフト活用ツイート
3. マラソン（エントリー期間のみ）        → 事前エントリー促進ツイート（まだ買わなくてOK）
4. 月末前日（マラソン無し）              → 期間限定ポイント失効注意ツイート
5. 月末最終日（マラソン無し）            → 期間限定ポイント失効目前ツイート
6. ワンダフルデー（18日）               → ワンダフルデーツイート
7. 0と5のつく日（マラソンなし）          → ふるさと納税アピールツイート
8. W勝利（eagles & vissel）            → ポイント3倍ツイート
9. イーグルスのみ勝利                   → ポイント2倍ツイート
10. ヴィッセルのみ勝利                   → ポイント2倍ツイート
11. 土曜 & adidas開催中                  → adidas特集ツイート
12. 日曜 & nike開催中                   → NIKE特集ツイート
13. 通常日                              → 39ショップ・リピート・ゲリラ告知

### slot 設計（2026-05-23 改修後・暫定）
- **18時スロット** (JST 16:00-19:59): 通勤・夕方ゴールデンタイム — **現在これだけ稼働**
- ❌ 0時 / 12時 / 20時スロットは廃止（暫定）
  - 0時 / 20時は 2026-05-20 にX APIクレジット節約で廃止
  - 12時は 2026-05-23 に X URL reputation 悪化を止めるため一時休止
    → 1日1投稿に絞って 403 連鎖を物理ゼロに → reputation 自然回復を待つ
  - reputation 回復後（imaraku URL 付き投稿が 1st try で通るようになったら）、
    12時スロットを再開する予定（SLOT_WINDOWS と daily-tweet.yml cron 両方を戻す）
```

### 月末2日の期間限定ポイントツイートについて
- **発射日**: 月の最終日から数えて2日間（31日月=30日/31日、30日月=29日/30日、2月=27日/28日 or 28日/29日）
- **優先度**: マラソン系より下、それ以外の特別日より上（マラソン中はマラソンツイート優先）
- **狙い**: 初心者がやらかしがちな「期間限定ポイント失効」を救う信頼獲得フック
- **重要**: 期間限定ポイントは **楽天キャッシュへチャージ不可**（通常ポイントはOK）。誤情報を出さない

---

## GitHub Actionsのスケジュール（2026-04-28 改修後）

| ワークフロー | cron（UTC） | JST換算 / 戦略 |
|---|---|---|
| check-campaigns | `0 15,17,19,21,23,1,3,5,7,9,11,13 * * *` | 2時間ごと |
| daily-tweet | `5 7,8,9,10 * * *` | **JST 16-19時のみ 4 fire/日**＋slot dedup (1スロット: 18時のみ。URL reputation 回復まで暫定) |
| marathon-preannounce | `30 10 * * *` / `40 10 * * *` / `50 10 * * *` | 19:30/19:40/19:50 JST 冗長fire |
| ranking-check | `0,30 0,3,6,9,11,13,15,18 * * *` | 8時刻×2 (16fire/日) |

**重要**: daily-tweet は cron 取りこぼし対策で毎時2回試行する設計。
スクリプト側で `current_slot()` がスロット判定（0/12/18/20時）し、
`posted_slots.json` が「対象スロット&未投稿」のみ実投稿に絞る。

全ワークフローに：
- `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true`（Node.js 24 対応）
- `concurrency: { group: <name>, cancel-in-progress: false }`（重なり時はキューイング）
- `timeout-minutes`（hang防止）

設定済み。

---

## GitHub Secrets（設定済み）

- `TWITTER_API_KEY`
- `TWITTER_API_SECRET`
- `TWITTER_ACCESS_TOKEN`
- `TWITTER_ACCESS_TOKEN_SECRET`

---

## アフィリエイト設定

全ての楽天URLに `?scid=af_pc_etc&sc2id=af_101_0_0` を付与。
楽天モバイルなど外部ドメインは `noAffiliate: true` で直リンク。

---

## 🚨 自動化レジストリ（⚠️ 新しい自動化を足す前に必ず読むこと）

**このプロジェクトで @ima_raku_entry に投稿できる全経路を、ここに一元管理する。**
新しい cron / LaunchAgent / 別サーバー上のbot / n8n / Buffer 等を追加する時は、
**必ずこの表に追記する**。二重投稿の温床になる。

### 稼働中の自動投稿経路（2026-04-18 現在）

| 経路 | 実体 | スケジュール | 停止方法 |
|---|---|---|---|
| GitHub Actions: daily-tweet | `.github/workflows/daily-tweet.yml` → `post_daily_tweet.py` | 0/12/18/20時 JST | ワークフローを disable |
| GitHub Actions: marathon-preannounce | `.github/workflows/marathon-preannounce.yml` → `post_marathon_alert.py` | 19:50 JST | 同上 |
| GitHub Actions: ranking-check | `.github/workflows/ranking-check.yml` → `check_ranking.py` | 3時間ごと | 同上 |
| GitHub Actions: post-pokemon-lottery | `.github/workflows/post-pokemon-lottery.yml` → `post_pokemon_lottery.py` | 手動 | 実行しない |

### 過去に存在したが **廃止済** の自動化（掘り起こし禁止）

| 経路 | 実体 | 廃止日 | 廃止理由 |
|---|---|---|---|
| `com.imaraku.autopost` LaunchAgent | `~/.imaraku/x_auto_post.py` | 2026-04-18 | GitHub Actions と二重投稿、古いSPU/TOP3テンプレで誤発信 |

### 🛡️ 新しい自動化を仕込む時の必須手順

1. **上の「稼働中」表に追記**（経路・実体パス・スケジュール・停止方法）
2. **旧方式は必ず根絶** — 移行のつもりで新旧並走させない。古い LaunchAgent・cron・スクリプトは **即ungrant＋削除**
3. **停止方法を具体的に書く** — 「launchctl bootout gui/UID/Label」等、コマンドレベルで残す
4. **投稿先アカウントとAPIキーの出所を明記** — 生書き .env ファイルをローカルに残さない（GitHub Secrets 一本化）

### 🔍 怪しい投稿が出た時の調査3ステップ

1. X のツイートの投稿時刻をチェック
2. GitHub Actions の実行履歴（`/actions/workflows/*/runs`）に対応する時刻があるか確認
3. **なければローカル疑惑** → `launchctl list | grep imaraku` / `crontab -l` / `ps aux | grep python`

---

## 重要な注意事項・過去の対応履歴

### マラソン期間の2段階について
- **エントリー期間** と **ポイントアップ期間** は別物
- エントリー期間中に購入してもポイントアップしない
- `marathon_pointup` キーで区別して管理
- check_campaigns.py でページ内キーワードにより自動判定

### campaignKeyの注意点
- `marathon` キー = マラソン期間中のみ表示（エントリー期間含む）
- adidas・nikeは常設ではないため campaignKey で制御

### スクリプトのファイル位置
- `check_campaigns.py` と `post_marathon_alert.py` はリポジトリルート直下
（旧: scripts/配下だったが修正済み）

### 🎴 ポケカ抽選（楽天ブックス・数ヶ月に1回開催）

**狙い**: マラソン時のレッドオーシャンを避け、普段と違う層（ポケモン勢）にリーチして認知拡大。

**運用手順（開催日が告知されたら）**:
1. `pokemon_lottery.json` の `receipt_periods` に新しい期間を追加
   ```json
   { "name": "2026年XX月 YY弾", "start": "YYYY-MM-DDTHH:MM:SS+09:00", "end": "YYYY-MM-DDTHH:MM:SS+09:00" }
   ```
2. 商品が変わっていれば `post_pokemon_lottery.py` の `PRODUCTS` リストを更新
3. 必要なら `imaraku.html` の個別17種カードを差し替え（booksEntries セクション内）
4. コミット&push すれば `check_campaigns.py` が受付期間中だけ `pokemon_lottery=true` にしてくれる
5. X投稿は GitHub Actions の「ポケモンカード抽選ツイート投稿（手動）」を workflow_dispatch で発射
   - **初回**: `mode=initial`（受付開始直後の夕方ゴールデンタイム推奨）
   - **リマインド**: `mode=reminder`（締切前日夕方〜当日朝）
   - 同じ内容の二重投稿はX側に403される → reminder モードが文言と商品順を変えて回避

**重要**: ポケカ抽選で当選 → 3,000円以上注文で 楽天ブックスSPU+0.5% が自動ONになる独自価値情報。
これが他のポケカ速報アカウントと差別化できる武器。ツイートに必ず盛り込む。

### ランキングスクレイピング
- `check_ranking.py` が3時間ごとに `ranking.rakuten.co.jp` を取得
- `ranking_cache.json` に前回結果をキャッシュ
- レアアイテム（ゲーム・シール・限定等）の新規ランクインを即ツイート
- 月・水・金に定期ツイート（コンタクトレンズ・お水など常連アイテム紹介）

### 画像生成
- `generate_images.py`（リポジトリ外、ローカルのみ）でogp.png / imaraku_banner.pngを生成
- フォント: `DroidSansFallbackFull.ttf`（日本語）+ `DejaVuSans-Bold.ttf`（英数字）
- 混在テキストは `draw_mixed()` 関数で処理
- PILはRGB画像でアルファ値を無視するため `#FFFFFF20` 等は使わない

---

## Claude Codeでの作業開始方法

```bash
git clone https://github.com/imaraku/imaraku.git
cd imaraku
claude
```
