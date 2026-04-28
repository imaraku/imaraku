# 今楽（imaraku）プロジェクト — Claude Code 引き継ぎドキュメント

## 👋 引き継ぎClaudeへ：最初に知っておくべきこと

**運営者は @ima_raku_entry（mochiki.kengo@gmail.com）。一人称「相棒」で呼んでくる。
カジュアルなトーンで頼むぜ系の口調。技術的な細かい指示よりも「違和感を伝える」スタイル。
`お疲れ！相棒！` `ナイス！` `頼むぜ！` みたいなノリで返してOK。**

### 必読セクション（順番に）
1. **🚨 踏むな地雷リスト**（このすぐ下）— 過去のセッションで実際に踏んだ事故集
2. **自動化レジストリ**（中盤）— 二重投稿の元凶になるので新規自動化前に必ず読む
3. **ファイル構成** — JSONファイルがそれぞれ何を管理してるか

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
| `marathon` | お買物マラソン（エントリー期間含む） | false |
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
| daily-tweet | `0,30 * * * *` | **毎時:00/:30＝48回/日試行**＋slot dedup |
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
