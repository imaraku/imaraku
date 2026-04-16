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
4. ワンダフルデー（18日）               → ワンダフルデーツイート
5. 0と5のつく日（マラソンなし）          → ふるさと納税アピールツイート
6. W勝利（eagles & vissel）            → ポイント3倍ツイート
7. イーグルスのみ勝利                   → ポイント2倍ツイート
8. ヴィッセルのみ勝利                   → ポイント2倍ツイート
9. 土曜 & adidas開催中                  → adidas特集ツイート
10. 日曜 & nike開催中                   → NIKE特集ツイート
11. 通常日                              → 39ショップ・リピート・ゲリラ告知
```

---

## GitHub Actionsのスケジュール

| ワークフロー | cron（UTC） | JST換算 |
|---|---|---|
| check-campaigns | 毎時 奇数(15,17,19,21,23,1,3,5,7,9,11,13) | 2時間ごと |
| daily-tweet | 0 15/3/9/11 * * * | 0時/12時/18時/20時 JST |
| marathon-preannounce | 50 10 * * * | 毎日19:50 JST |
| ranking-check | 0 */3 * * * | 3時間ごと |

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
