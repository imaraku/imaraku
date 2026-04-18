# 今楽（imaraku）プロジェクト — Claude Code 引き継ぎドキュメント

## プロジェクト概要

**今楽（imaraku）** は楽天市場のキャンペーンエントリーをまとめたアグリゲーターサイト。

- **サイトURL**: https://imaraku.github.io/imaraku/imaraku.html
- **GitHubリポジトリ**: https://github.com/imaraku/imaraku
- **Xアカウント**: @ima_raku_entry
- **運営者メール**: mochiki.kengo@gmail.com

---

## ファイル構成

```
imaraku/                        ← リポジトリルート
├── imaraku.html                ← メインサイト（GitHub Pages）
├── campaign_status.json        ← キャンペーン開催状況（GitHub Actionsが自動更新）
├── new_campaigns.json          ← 自動検出された新キャンペーン候補
├── ranking_cache.json          ← ランキングチェック用キャッシュ（自動生成）
├── ogp.png                     ← X/OGPリンクプレビュー画像 (1200x630)
├── check_campaigns.py          ← キャンペーン状態チェックスクリプト（旧: scripts/配下）
├── post_daily_tweet.py         ← 日次ツイートスクリプト
├── post_marathon_alert.py      ← マラソン事前告知スクリプト
├── check_ranking.py            ← 楽天ランキングチェック＆ツイートスクリプト
└── .github/
    └── workflows/
        ├── check-campaigns.yml     ← 2時間ごと実行
        ├── daily-tweet.yml         ← 0時/12時/18時/20時 JST
        ├── marathon-preannounce.yml← 毎日19:50 JST
        └── ranking-check.yml       ← 3時間ごと実行
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

## GitHub Actionsのスケジュール

| ワークフロー | cron（UTC） | JST換算 |
|---|---|---|
| check-campaigns | `0 15,17,19,21,23,1,3,5,7,9,11,13 * * *` | 2時間ごと |
| daily-tweet | `0 15 * * *` / `0 3 * * *` / `0 9 * * *` / `0 11 * * *`（4本） | 0時/12時/18時/20時 JST |
| marathon-preannounce | `50 10 * * *` | 毎日19:50 JST |
| ranking-check | `0 */3 * * *` | 3時間ごと |

全ワークフローに `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true` 設定済み。

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
