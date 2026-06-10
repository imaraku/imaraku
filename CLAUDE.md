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

### ⚠️ 15. X API (api.twitter.com) は Cloudflare で間欠的に 403 を返す
2026-05-31 に「カテゴリTOP3ツイート」が2連続失敗。ログ実視で真因判明：
api.twitter.com への投稿が **Cloudflare マネージドチャレンジ（403 "Just a moment…"）**
で弾かれていた。GitHub Actions のデータセンターIP＋素の `python-requests` の
デフォルト User-Agent が「いかにもbot」と判定されるのが原因。重複でもコードbugでも
認証エラーでもない（最初は重複403を疑ったが、ログ本文を見て確定した）。

【なぜ気づきにくいか】
- 間欠的（全リクエストではなく一部だけ challenge）。多くは通るので「たまに失敗」に見える。
- cron回数が多い経路（daily-tweet / ranking）はリトライで拾えて表面化しない。
- カテゴリは 1日2回 cron だけ → 両方 challenge に当たって全滅 → 初めて顕在化した。

✅ **対策（全4投稿スクリプトに適用済 2026-05-31）**:
post_daily_tweet / check_ranking / post_marathon_alert / post_category_ranking の
`_post_once`（または `post_tweet`）に:
  1. **ブラウザ風 User-Agent** を付与（bot スコアを下げ challenge 率を減らす）
  2. **Cloudflare403 / 429 / 5xx は最大3回リトライ**（5s,10s バックオフ＋timeout=20）
  3. 重複403等の決定的エラーはリトライしない（無駄撃ち防止）
判定: `403 かつ body に "Just a moment" / "cloudflare" / "cf_chl" を含む` → Cloudflare とみなす。

✅ **教訓**:
- 「post_tweet が False」の真因は status code だけでなく **body を見ないと分からない**
  （地雷#11「success を信用するな」の"失敗"版＝失敗の中身も見ろ）。
- これは**緩和策**。Cloudflare が強化したら UA だけでは突破できなくなる可能性あり。
  その時は専用ライブラリ(tweepy 等)や別経路を検討。**周期的に投稿成功率を確認**する。
- ログ本文は認証必須。gh 未導入時は **Chrome MCP でジョブログをスクショ→読む**のが速い
  （`javascript_tool` は query string を含むと拡張のセーフティでブロックされることがある）。

### ⚠️ 16. slot窓が狭いと cron 遅延着地で「投稿ゼロ」になる（地雷#5 の続き）
2026-06-01・02 に daily-tweet が投稿ゼロだった。真因: GitHub Actions の cron
(`0,30 7,8,9,10` UTC = 16:00-19:30 JST) が**遅延**し、実際の実行が 20-21時JST に
着地 → `current_slot()` の slot窓(16-20時)の外 → None → no-op で何も投稿しない。
（5/27-5/31 は窓内に1回は走れていたので顕在化しなかった。）

run は全て ✅success（no-op も success 扱い）なので、**失敗メールすら来ない**沈黙の
取りこぼし。`posted_slots.json` が更新されない／タイムラインに日次が出ない、で初めて気づく。

✅ **対策（2026-06-03）**: `SLOT_WINDOWS` の "18" を (16,20)→**(16,22)** に拡張。
GitHub の遅延着地(20-21時JST)も拾えるようにした。posted_slots dedup は不変なので
二重投稿リスクなし。通常日は16-19時、drop多発日は20-21時に救済される。

✅ **教訓**:
- cron の「発火予定時刻」と「実際の着地時刻」は別物。**slot窓は遅延着地を見込んで広めに**取る。
- 「success だが no-op」は失敗メールが来ない → 地雷#11「success を信用するな」と同根。
  カナの巡回 or `posted_slots.json` の鮮度監視で拾うのが将来の再発防止になる。
- 症状が「投稿が出てない」時は、URL/Cloudflare/重複 を疑う前に **そもそも slot窓内に
  発火できているか**（run の実時刻 vs 窓）を最初に確認する。

### ⚠️ 17. X API は従量課金 — クレジット枯渇で全投稿が 402 停止する
2026-06-09 に daily-tweet が2連続失敗。ログ実視で
`402 {"title":"CreditsDepleted","detail":"...does not have any credits..."}` を確認。
X API は**投稿のたびにクレジットを消費する従量課金**で、残高ゼロになると全経路が一斉に
402 で止まる（コード/Cloudflare/cronは無関係）。スーパーSALE期の投稿増で枯渇した。

✅ **対応**: 残高・補充は `console.x.com` → Billing（**相棒にしか操作できない**。Claudeは課金操作不可）。
✅ **節約設定（2026-06-10 適用済・質は維持し被り/繰返し/過剰頻度だけ削減）**:
  - ranking-check: cron 6時刻→3時刻（JST 12/18/21）
  - 常連ツイート: 非マラソン時 週6→週1（月曜）。マラソン中は毎日
  - 急上昇ツイート: 1日2件 cap（`ranking_cache.json` の rare_count）
  - sale-picks: 毎セール日→最強日（セール×0と5）のみ
✅ **教訓**: 投稿失敗は status code だけでなく **body を読む**（402=クレジット枯渇 /
  403=Cloudflare or 重複。地雷#11/#15 と同根）。新しい投稿経路を増やす時は
  「クレジット消費が増える」コストを必ず意識する。

### ⚠️ 18. 楽天の共通ヘッダに「エントリーする」が入っている — キーワードでエントリーページ判別は不可
2026-06-11 に「SALE配下のエントリー型サブページを🆕に拾う」設計を dry-run したところ、
**会場ページ（半額/ジャンル/訳あり等）28件が「エントリーする」キーワードを含んで素通り**した。
楽天の共通ヘッダ/フッタに当該文言が常駐しているため。逆に本命の参加型（くじ/たまご）は
**JSレンダーで生HTMLに文言が無く弾かれた**。

✅ **正解**: ページ内キーワードでの判別はやめ、**slug 決め打ち probe**（`detect_sale_minigames`:
  lottery/find-quiz/tamago 等は毎回 slug が同じで token だけ変わる。probe 200=開催中のみ追加、
  SALE終了時に sale_minigame タグで自動掃除）。
✅ **同根の対処**: ゲリラ判定も SALE版ページは文言が違う（「エントリーでポイント2倍」）ため、
  CAMPAIGNS の guerrilla に `period_check: True` を有効化（ページの開催期間表記で判定。
  期間が取れなければ従来キーワードにフォールバック）。
✅ **教訓**: 「ページにこの言葉があるか」で種類を判別する設計は、共通ヘッダ・JSレンダーの
  両方で裏切られる。**実ページで dry-run してから積む**こと（今回これで事故を未然回避）。

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

### ⚡ 補足: ゲリラのスーパーSALE対応＋参加型ミニゲーム検出（2026-06-11・本番実証済）
- **ゲリラ**: `discover_dynamic_urls()` がマラソン token で見つからない時、supersale top から
  token 抽出→ `campaign/supersale/<token>/pointdouble/` を probe。1-c の強制 false も
  supersale 中は guerrilla を除外。判定は `period_check`（地雷#18参照）。
  run#852 で本番 `guerrilla=True` を実証（SALE終了で自動クローズ）。
- **ミニゲーム**: `detect_sale_minigames()` が lottery/find-quiz/tamago 等を slug probe で
  🆕枠へ追加（おすすめにも表示）。SALE終了時に `sale_minigame` タグで自動掃除。

### ✅ 補足: エントリー済みチェックUI＋「次の未エントリーを開く」FAB（2026-06-11 相棒の要望）
実利用は「1個開いてエントリー→戻って次」。これに合わせた2つの仕組み（imaraku.html）:
- **済みチェック**: エントリー/取得ボタンを開くと自動で ✅済（減光＋緑バッジ＋ボタン緑化）。
  バッジタップで戻せる。`localStorage`（key: `imaraku_entry_done_v1`）に**月単位**で保存し
  月替わりで自動リセット（楽天の毎月再エントリー仕様と整合）。モードバナーに「✅済 X/Y」。
- **FAB**: 画面下固定「▶ 次の未エントリーを開く（残りN件）」。タップ→次の未エントリーを
  開いて済み化→戻る→タップ…で全消化。該当者のみ(ママ/学/ペット割)は自動巡回から除外。
- ⚠️ **自動エントリー（押すだけで完了）は実装禁止**: 楽天セッションは外部から使えず、
  自動化は楽天規約違反（ユーザーBANリスク）＋アフィリエイト停止リスク。この FAB＋済みUIが
  規約内でできる最適解、という整理（2026-06-11 相棒と合意）。

### 🎛️ 補足: おすすめモード簡素化（2026-06-11 相棒の要望）
おすすめ68件の正体は🆕自動検出44件（特集ページ）だった。方針:
- 🆕枠は **全部表示のみ**（`renderNewCampaigns` の data-essential を動的化。
  参加型ミニゲームだけ true でおすすめにも出す）。🆕が全部 hidden なら見出しごと隠す。
- マラソン系のジャンル特化/条件型/会員限定/少額クーポン11枚を essential:false に降格。
- 実測: おすすめ 68→24件 / 全部表示84件。**おすすめ=「今日すべき基本」だけ**を維持する。
  新カード追加時は「ライトユーザーが今日やるべきか」で essential を決めること。

### 🛒 補足: 楽天トップpageの市場キャンペーン自動抽出（2026-05-30 相棒の要望）
楽天トップ(`www.rakuten.co.jp`)のメインビジュアル（バナーカルーセル）は **JSレンダーSPA＋
画像に文字焼き込み**で、生HTMLからは抽出不能（biccamera と同じ／地雷参照）。代わりに
**生HTMLに含まれる `event.rakuten.co.jp` の実キャンペーンリンク**を `detect_new_campaigns()`
で広く拾う方式に拡張した（トップpageは元々 `SCAN_PAGES` に在った）。

- **拡張点**: `NEW_CAMPAIGN_URL_RE` のセクションに gift/father/mother/brand/bargain/pet/
  fashion/beauty＋キャラ特集(disney/sanrio/pokemon/marvel/starwars/moomin) を追加。
  `KNOWN_URL_PATTERNS` から brand/fashion/beauty を開放（「広め」方針）。
- **ワガママ除外**: `is_non_market_url()`＋`NON_MARKET_PATTERNS` を新設。車/不動産/カード/
  トラベル/レンタカー/銀行/証券/保険/モバイル/ゴルフを除外。※大半は別ドメインで regex に
  当たらず自動除外。
- **期間検証**: 検出時に `period_status(page)=="expired"` を弾く（サイレント終了対策）。
- **出力先**: 既存の `new_campaigns.json` → サイトの「🆕自動検出キャンペーン」枠に自動掲載。
  X投稿経路ではない（二重投稿リスクなし）。MAX_PER_RUN=10＋`purge_ended_campaigns` で自己修復。
- **チューニング**: ノイズ（キャラの深い個別ページ等）が出たら NON_MARKET か KNOWN に1行足すだけ。

### 🤝 補足: マイルドさん差分チェック（取りこぼし拾い・2026-05-30 相棒の要望）
相棒が参照する同業ブログ「マイルドさん」(`mild7000.hatenablog.com`)の最新まとめ記事と
今楽の保有キャンペーンを差分照合し、今楽に未掲載かつ開催中の市場キャンペーンを🆕枠
(`new_campaigns.json`)へ自動追加する仕組み（`check_mild_diff.py`）。

- **起動日**（`is_trigger_day`・毎日23時JST起動→対象日だけ実行）:
  ① 毎月1日の前日（月末）　② お買い物マラソン開始(`pointup_start`)の前日（`marathon_schedule.json`）
  ③ マイルドさんが当日に大型セール系まとめ（マラソン/スーパーセール/ポイントバック祭/大感謝祭/ワンダフルデー等）を新規投稿
  → ③のおかげで**開催日程を今楽が持たないイベントも、マイルドさんの新着投稿で検知**できる。
- **照合**: フィード→最新2記事→`a.r10.to`解決→`event.rakuten.co.jp` URL集合→今楽の保有/既知URLと
  差分→`check_campaigns.py` のガード再利用（市場外除外/カテゴリナビ/期間検証/名前検証）→開催中のみ追加。
  **事実URLの照合のみ・ブログ本文は不使用**。名称は楽天ページの og:title から取得。
- **稼働状態**: ✅ **稼働中（2026-05-31〜）**。`mild-diff.yml` の schedule 有効
  （毎日23時JST＋:10 バックアップ）。手動テストは `workflow_dispatch` の `force=true` で随時可能。
- **🤝 マイルドさんとの関係（重要・線引き厳守）**: 2026-05-31 に運営者がマイルドさんへ連絡し、
  **「全体的に参考してOK」の許可を取得済み**。ただし許可があっても線引きは絶対厳守＝
  **照合するのは事実（キャンペーンURLの存在）のみ・記事本文やまとめ内容は一切転載しない**。
  将来構想：今楽が見つけた「マイルドさんに無いエントリー」を逆に共有する"伸ばし合い"も視野
  （※優先度は「まず今楽アカウントをコツコツ育てる」が上。逆向き差分はまだ作らない）。
- **性質**: X投稿経路ではなくサイト更新のみ（二重投稿リスクなし）。`MAX_ADD=10`＋
  `purge_ended_campaigns` で自己修復。テストは `workflow_dispatch` の `force=true` で随時可能。

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
├── extra_events.json           ← mega-chance用の大型イベント手動登録（任意・スーパーSALEは自動検知）
├── ranking_cache.json          ← ランキングチェック用キャッシュ（自動生成）
├── (各種)_posted.json          ← 投稿dedup履歴: mega_chance_posted / supersale_announced /
│                                  sale_picks_posted / category_posted / travel_posted /
│                                  monthly_pay_posted / point_usage_posted 等（全て自動更新）
├── ogp.png                     ← X/OGPリンクプレビュー画像 (1200x630)
├── check_campaigns.py          ← キャンペーン状態チェック（メイン・supersale判定含む）
├── hashtag_helper.py           ← ハッシュタグ中央管理（全投稿スクリプトで共有）
├── post_daily_tweet.py         ← 日次ツイート（slot dedup・SALE文脈・最強日ブースト）
├── post_mega_chance.py         ← 最強日アナウンス（マラソン/スーパーSALE×最初の0と5）
├── post_marathon_alert.py      ← マラソン事前告知ツイート
├── post_supersale_alert.py     ← スーパーSALE 先行/開幕告知
├── post_sale_picks.py          ← セール売れ筋まとめ（A案）
├── check_ranking.py            ← ランキング急上昇/常連ツイート
├── post_category_ranking.py    ← カテゴリTOP3ツイート
├── post_travel_campaign.py     ← 0と5の日 楽天トラベル特集
├── post_monthly_pay.py         ← 毎月2日 楽天ペイ月初ルーティン
├── post_point_usage.py         ← 毎月16日 ポイント活用ヒント
├── post_pokemon_lottery.py     ← ポケカ抽選ツイート（手動）
├── post_room_suggestion.py     ← 📧 ROOM用ふるさと納税提案（Gmail送信・X投稿ではない）
├── check_mild_diff.py          ← マイルドさん差分→取りこぼし拾い（稼働中）
├── qa_audit.py                 ← カナの自動監視（毎朝8時JST）
└── .github/
    └── workflows/  （cron詳細は「GitHub Actionsのスケジュール」表を参照）
        ├── check-campaigns.yml / daily-tweet.yml / mega-chance.yml
        ├── marathon-preannounce.yml / supersale-alert.yml / sale-picks.yml
        ├── ranking-check.yml / category-ranking.yml / travel-campaign.yml
        ├── monthly-pay.yml / point-usage.yml / room-daily.yml
        └── post-pokemon-lottery.yml / mild-diff.yml / qa-audit.yml
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
| `supersale` | 楽天スーパーSALE開催中（公式ページの開催レンジを `detect_supersale_active` が自動判定） | false |
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
3b. スーパーSALE × 特別日(0と5/1日/18日) → 最強クラスのビッグチャンスツイート（big_chance）
3c. スーパーSALE開催中                    → SALE文脈ツイート（大型買い回りとしてマラソン直後の高優先）
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

### slot 設計（2026-06-05 改修後）
- **通常日**: 昼12時(JST10-16) + 夕18時(JST16-22) の **2投稿**。窓は cron 遅延着地を見込んで広め(地雷#5/#16)
- **最強の日**(=大型セール×0と5の日): 上記に **夜20時**(JST20-23) を加えた **3投稿**。
  夕(18)窓を16-20に狭め夜(20)20-23と重複させない。`NORMAL_SLOTS` / `PEAK_SLOTS` を `is_peak_day()` で切替
- 履歴: 5/23にX reputation悪化で18時一本に圧縮 → 6/1経過＋Cloudflare対策(地雷#15)完了で
  2026-06-05に12時復活＋ピーク日20時を新設
- 各スロットは `daily_lead_in` で文面ユニーク化(地雷#12)、`posted_slots.json` で各1回(二重投稿なし)

### 🔥「最強の日」の定義と peak-day ブースト（2026-06-05 相棒の定義）
相棒の感覚で「最強クラスの買い時」は次の重なり:
- **お買い物マラソン**: 月1回目のマラソン × 0と5のつく日
- **スーパーSALE**: セール中の最初の0と5のつく日（マラソンの最強日と「同等以上」）

実装 `is_peak_day(now, status)` = **(marathon_pointup or supersale) かつ day%5==0** で広く判定
（「月1回目」「最初の」までは厳密判定せず、セール×0と5 を最強日とする）。最強の日は:
- daily-tweet が **3スロット**(昼/夕/夜) で SALE/マラソンの big_chance を投稿
- `post_sale_picks.py`(A案) が売れ筋まとめを別角度で1本
→ 露出を最大化する。※ピーク日は同じ big_chance 文面が時間帯ヘッダ違いで複数出るため、
  繰り返し感が気になれば夕/夜版の文面を分ける余地あり（将来の改善ポイント）。
```

### 月末2日の期間限定ポイントツイートについて
- **発射日**: 月の最終日から数えて2日間（31日月=30日/31日、30日月=29日/30日、2月=27日/28日 or 28日/29日）
- **優先度**: マラソン系より下、それ以外の特別日より上（マラソン中はマラソンツイート優先）
- **狙い**: 初心者がやらかしがちな「期間限定ポイント失効」を救う信頼獲得フック
- **重要**: 期間限定ポイントは **楽天キャッシュへチャージ不可**（通常ポイントはOK）。誤情報を出さない

---

## GitHub Actionsのスケジュール（2026-06-06 棚卸し済・全数）

※ 投稿内容・停止方法は「自動化レジストリ」を参照。ここは cron 一覧（地雷#5 競合点検用）。

| ワークフロー | cron（UTC） | JST換算 / 戦略 |
|---|---|---|
| check-campaigns | `0 15,17,19,21,23,1,3,5,7,9,11,13 * * *` | 2時間ごと（status更新） |
| daily-tweet | `0,30 2,3,4,5,7,8,9,10,11,12,13 * * *` | 昼(11-14:30)/夕(16-19:30)/夜(20-22:30)＋slot dedup |
| mega-chance | `0,30 22 * * *` | 07:00/07:30（最強日のみ投稿） |
| marathon-preannounce | `30,40,50 10 * * *` | 19:30/40/50（マラソン前日のみ） |
| supersale-alert | `0 5,6,7,8,9,10,11 * * *` | 14-20時毎時（SALE開始前後のみ） |
| sale-picks | `0,30 5,6 * * *` | 14-15時（**最強日=セール×0と5のみ**・クレジット節約） |
| ranking-check | `0,30 3,9,12 * * *` | 3時刻×2（JST12/18/21・クレジット節約 2026-06-10） |
| category-ranking | `0,30 0 * * *` | 09:00/09:30 |
| travel-campaign | `0,30 8 5,10,15,20,25,30 * *` | 0と5の日 17:00（月2まで） |
| monthly-pay | `0,30 12 2 * *` | 毎月2日 21:00 |
| point-usage | `0,30 9 16 * *` | 毎月16日 18:00 |
| room-daily | `0 16 * * *` | 翌01:00（📧メール・X非投稿） |
| mild-diff | `0 14 * * *` / `10 14 * * *` | 23:00/23:10（サイト更新のみ） |
| qa-audit | `0 23 * * *` | 08:00（カナの監視） |

**重要**: daily-tweet は cron 取りこぼし(地雷#5)対策で毎時2回試行する設計。
スクリプト側で `current_slot()` がスロット判定（昼12/夕18、最強日は夜20）し、
`is_peak_day()` でピーク日を判定、`posted_slots.json` が「対象スロット&未投稿」のみ実投稿に絞る。
⚠️ X系の多くが :00 発火で競合 → daily-tweet が押し負けやすい（6/5に0着地の一因）。
将来 cron を :07/:37 等にズラすと競合ドロップが減る（地雷#5・後回し中）。

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

### 稼働中の自動投稿経路（2026-06-06 棚卸し済・全数）

**X 投稿経路（@ima_raku_entry）= 11本＋手動1。新規追加時は必ずこの表に追記すること。**

| 経路 | 実体 | スケジュール(JST) | 内容 | 停止方法 |
|---|---|---|---|---|
| daily-tweet | `daily-tweet.yml` → `post_daily_tweet.py` | 昼12/夕18（最強日は夜20も） | エントリー喚起・SALE文脈 | disable |
| mega-chance | `mega-chance.yml` → `post_mega_chance.py` | 最強日 07:00 | 「月一の最強日」アナウンス（マラソン/スーパーSALE×最初の0と5） | disable |
| marathon-preannounce | `marathon-preannounce.yml` → `post_marathon_alert.py` | マラソン前日 19:30-50 | 事前告知 | disable |
| ranking-check | `ranking-check.yml` → `check_ranking.py` | 3時間ごと | 急上昇/常連ランキング | disable |
| category-ranking | `category-ranking.yml` → `post_category_ranking.py` | 9時台 | カテゴリTOP3 | disable |
| sale-picks | `sale-picks.yml` → `post_sale_picks.py` | セール中 14-15（1日1回） | 売れ筋まとめ | disable |
| supersale-alert | `supersale-alert.yml` → `post_supersale_alert.py` | SALE開始前後 14-20 | 先行/開幕告知 | disable |
| travel-campaign | `travel-campaign.yml` → `post_travel_campaign.py` | 0と5の日 17:00（月2まで） | 楽天トラベル特集 | disable |
| monthly-pay | `monthly-pay.yml` → `post_monthly_pay.py` | 毎月2日 21:00 | 楽天ペイ月初ルーティン | disable |
| point-usage | `point-usage.yml` → `post_point_usage.py` | 毎月16日 18:00 | ポイント活用ヒント | disable |
| post-pokemon-lottery | `post-pokemon-lottery.yml` → `post_pokemon_lottery.py` | 手動 | ポケカ抽選 | 実行しない |

**X 投稿ではない自動化（二重投稿の心配なし）:**
- `room-daily.yml` → `post_room_suggestion.py`: 📧 **Gmailで自分宛**（楽天ROOM用ふるさと納税提案・毎日01:00）。X投稿ではない。
- `check-campaigns.yml` / `mild-diff.yml`: サイト更新のみ（campaign_status / new_campaigns）。
- `qa-audit.yml` → `qa_audit.py`: カナの監視（commit報告のみ）。

⚠️ **最強日の重複に注意**: 最強日（大型セール×最初の0と5）は mega-chance(07時announce)＋
daily-tweet(12/18/20 の big_chance)＋sale-picks(14時) が重なり計6本前後になる。文面は別物だが
テーマが重なるので、最強日にさらに投稿を増やす時は「投稿過多」を点検すること（相棒の違和感センサー優先）。

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
