#!/usr/bin/env python3
"""
post_room_suggestion.py
楽天ROOM投稿用に「ふるさと納税の人気商品」を1件選出し、
Claude Haiku にアピール文を生成させて Gmail にメールで通知する。

【動作ロジック】
  1. 楽天ふるさと納税ランキングページ(event.rakuten.co.jp/furusato/ranking/)を
     スクレイピングして上位商品を取得
  2. キャッシュと突き合わせて未通知の上位1品を選出
  3. Claude Haiku 4.5 にアピール文(2-3行)を生成させる
  4. メール本文を組み立てて Gmail SMTP 経由で送信
  5. キャッシュ更新（直近30件の商品URLを保持して重複回避）
"""

import os
import re
import io
import sys
import json
import datetime
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.header import Header

import requests
from bs4 import BeautifulSoup

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_OK = True
except ImportError:
    PIL_OK = False

# ── 認証情報 ─────────────────────────────────────────────────────────────────
RAKUTEN_APP_ID     = os.environ.get("RAKUTEN_APP_ID", "").strip()
RAKUTEN_ACCESS_KEY = os.environ.get("RAKUTEN_ACCESS_KEY", "").strip()
RAKUTEN_ORIGIN     = os.environ.get("RAKUTEN_ORIGIN", "https://imaraku.github.io").strip()

ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "").strip()
GMAIL_USER         = os.environ.get("GMAIL_USER", "mochiki.kengo@gmail.com").strip()
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]  # 必須
MAIL_TO            = os.environ.get("MAIL_TO", "mochiki.kengo@gmail.com").strip()

# ── 定数 ─────────────────────────────────────────────────────────────────────
JST                = datetime.timezone(datetime.timedelta(hours=9))
CACHE_FILE         = "room_post_cache.json"
CACHE_HISTORY_MAX  = 1000   # 投稿済みは事実上ずっと覚えておく（重複投稿防止）
                            # 80KB前後で済むのでサイズ問題なし。3年分の余裕あり。
# ROOM経由のクリックを imaraku.html (af_101_0_0) と区別するため別 sc2id を使う。
# 楽天アフィリエイト管理画面で「af_room_0_0」で絞ればROOM由来だけ集計できる。
AFFILIATE_SUFFIX   = "scid=af_pc_etc&sc2id=af_room_0_0"
CLAUDE_MODEL       = "claude-haiku-4-5-20251001"

# ── 画像生成用定数 ────────────────────────────────────────────────────────────
OUTPUT_IMAGE_PATH  = "/tmp/room_post_image.png"
IMAGE_SIZE         = (1080, 1080)       # ROOMは正方形が映える
BRAND_GREEN        = (93, 138, 70)      # 和風グリーン（田舎感）
ACCENT_GOLD        = (216, 180, 124)    # 稲穂ベージュゴールド
BG_CREAM           = (250, 246, 240)    # 背景クリーム
TEXT_DARK          = (60, 40, 20)       # 濃茶テキスト
FONT_CANDIDATES = [
    # GitHub Actions (ubuntu) — fonts-noto-cjk パッケージ
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    # macOS ローカルテスト用
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]

# ── ユーティリティ ─────────────────────────────────────────────────────────────

def add_affiliate(url: str) -> str:
    """楽天URLにアフィリエイトパラメータを付与する。"""
    if not url or "rakuten" not in url:
        return url
    sep = "&" if "?" in url else "?"
    return url + sep + AFFILIATE_SUFFIX


def strip_name_prefix(name: str) -> str:
    """【...】【...】で始まる商品名プレフィックスを軽く整形。"""
    pattern = re.compile(r'^[【［\[][^】］\]]*[】］\]]\s*')
    while True:
        m = pattern.match(name)
        if not m:
            break
        stripped = name[m.end():]
        if not stripped.strip():
            break
        name = stripped
    return name.strip()


def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"sent_urls": [], "last_sent_date": ""}


def save_cache(cache: dict) -> None:
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


# ── ランキング取得（スクレイピング） ───────────────────────────────────────────
#
# 2026-05-25 以降、楽天がページ構造を変更:
#   旧: <a href="https://item.rakuten.co.jp/f..."> 直接リンク
#   新: <div data-key="itemurl">https://item.rakuten.co.jp/f...</div> data-key パターン
#
# 新フォーマットは全フィールドが綺麗に data-key で並ぶので、
# むしろ取得が確実かつシンプルになった（rank, name, url, image, price, shop が全部取れる）。

FURUSATO_RANKING_URL = "https://event.rakuten.co.jp/furusato/ranking/"
# 寄付額文字列 → 整数。"7,500円～" や "18,000円" 等を吸収
PRICE_VALUE_RE = re.compile(r"([0-9][0-9,]{2,})")


def _extract_datakey_values(html: str, key: str) -> list[str]:
    """<div data-key="key">...</div> の中身テキストを順序通り抽出。"""
    pat = re.compile(
        r'<div\s+data-key="' + re.escape(key) + r'"\s*>(.*?)</div>',
        re.DOTALL,
    )
    return [m.group(1).strip() for m in pat.finditer(html)]


def _extract_datakey_image_srcs(html: str, key: str = "imageurl") -> list[str]:
    """<div data-key="imageurl"><img src="..." /></div> の src を抽出。"""
    pat = re.compile(
        r'<div\s+data-key="' + re.escape(key) + r'"\s*>(.*?)</div>',
        re.DOTALL,
    )
    results = []
    for m in pat.finditer(html):
        block = m.group(1)
        img_m = re.search(r'<img[^>]+src="([^"]+)"', block)
        results.append(img_m.group(1).strip() if img_m else "")
    return results


def _parse_price(text: str) -> int:
    """『18,000円』『7,500円～』等から整数を抽出。失敗時は0。"""
    if not text:
        return 0
    m = PRICE_VALUE_RE.search(text)
    if not m:
        return 0
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return 0


def fetch_via_scrape() -> list[dict]:
    """楽天ふるさと納税ランキングページをスクレイピングして上位商品を取得。"""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ja,en;q=0.9",
    }
    try:
        r = requests.get(FURUSATO_RANKING_URL, headers=headers, timeout=25)
        if r.status_code != 200:
            print(f"⚠️ ランキングページ {r.status_code}: {r.text[:200]}", file=sys.stderr)
            return []
    except Exception as e:
        print(f"⚠️ ランキングページ取得失敗: {e}", file=sys.stderr)
        return []

    html = r.text
    ranks       = _extract_datakey_values(html, "rank")
    names       = _extract_datakey_values(html, "itemname")
    urls        = _extract_datakey_values(html, "itemurl")
    images      = _extract_datakey_image_srcs(html, "imageurl")
    prices      = _extract_datakey_values(html, "kakaku")
    shops       = _extract_datakey_values(html, "shopname")

    # 全フィールドの件数が揃わない場合は早期return（楽天側の再変更検出）
    n = min(len(ranks), len(names), len(urls), len(images), len(prices), len(shops))
    if n == 0:
        print(f"⚠️ data-key 形式マッチ0件。ページ構造が再変更された可能性。"
              f"ranks={len(ranks)} names={len(names)} urls={len(urls)} "
              f"images={len(images)} prices={len(prices)} shops={len(shops)}",
              file=sys.stderr)
        return []

    seen_base = set()
    items: list[dict] = []
    for i in range(n):
        url = urls[i]
        if not url or "item.rakuten.co.jp" not in url:
            continue
        base = url.split("?")[0].rstrip("/")
        if base in seen_base:
            continue
        name = names[i]
        if not name or len(name) < 5:
            continue
        seen_base.add(base)
        items.append({
            "name": name,
            "url": base + "/",
            "price": _parse_price(prices[i]),
            "shop": shops[i] or "",
            "image_url": images[i] or "",
            "caption": "",
        })
        if len(items) >= 60:
            break

    print(f"  スクレイピング取得: {len(items)} 件")
    return items


def fetch_furusato_items() -> list[dict]:
    """楽天ふるさと納税ランキングをスクレイピングで取得。"""
    return fetch_via_scrape()


# ── 商品選出 ───────────────────────────────────────────────────────────────────

SEASONAL_FILE = "seasonal_pre_peak.json"


def load_seasonal_keywords(month: int) -> list[str]:
    """現在の月の『旬のちょっと前』キーワード配列を返す。失敗時は空リスト。"""
    if not os.path.exists(SEASONAL_FILE):
        return []
    try:
        with open(SEASONAL_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("months", {}).get(str(month), [])
    except Exception as e:
        print(f"  ⚠️ 季節カレンダー読み込み失敗: {e}", file=sys.stderr)
        return []


def load_necessity_keywords() -> list[str]:
    """日曜『日用品の日』用キーワード配列を返す。失敗時は空リスト。"""
    if not os.path.exists(SEASONAL_FILE):
        return []
    try:
        with open(SEASONAL_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("sunday_necessities", [])
    except Exception as e:
        print(f"  ⚠️ 日用品キーワード読み込み失敗: {e}", file=sys.stderr)
        return []


def pick_by_keywords(items: list[dict], sent_urls: list[str], keywords: list[str]) -> tuple:
    """キーワードに一致する未送信の上位アイテムを返す。無ければ (None, None)。"""
    sent_set = set(sent_urls)
    for it in items:
        base_url = it["url"].split("?")[0]
        if base_url in sent_set:
            continue
        name = it.get("name", "")
        for kw in keywords or []:
            if kw in name:
                return it, kw
    return None, None


def pick_item(items: list[dict], sent_urls: list[str], seasonal_keywords: list[str] = None) -> tuple:
    """未送信アイテムを選出。返値は (item, matched_keyword_or_None)。

    挙動:
      1. 季節キーワードが指定されてれば、キーワード一致の上位アイテムを優先（位相リード戦略）
      2. 一致が無い、もしくはキーワード未指定 → ランキング順の最上位未送信
      3. 全て送信済み → (None, None)
    """
    # Phase 1: 季節キーワード一致 を優先
    if seasonal_keywords:
        it, kw = pick_by_keywords(items, sent_urls, seasonal_keywords)
        if it is not None:
            return it, kw

    # Phase 2: ランキング順フォールバック
    sent_set = set(sent_urls)
    for it in items:
        base_url = it["url"].split("?")[0]
        if base_url not in sent_set:
            return it, None

    # Phase 3: 全て送信済み
    return None, None


# ── アピール文生成 ─────────────────────────────────────────────────────────────

def generate_appeal(item: dict, seasonal_keyword: str = None, necessity_keyword: str = None) -> str:
    """Claude Haiku にアピール文を生成させる。失敗時はフォールバック文を返す。
    seasonal_keyword: 「旬の先取り」軸を訴求に追加。
    necessity_keyword: 「日用品=実質生活費削減」軸を訴求に追加（日曜の日用品の日）。
    """
    if necessity_keyword:
        fallback = f"ふるさと納税で{necessity_keyword}！どうせ使う日用品だから実質生活費の節約になるよ。"
    elif seasonal_keyword:
        fallback = f"これからが旬の{seasonal_keyword}！ふるさと納税で今から予約しておこう。"
    else:
        fallback = "人気ランキングから厳選！ふるさと納税でお得に手に入れるチャンスだよ。"
    if not ANTHROPIC_API_KEY:
        print("  ⚠️ ANTHROPIC_API_KEY 未設定 → フォールバック", file=sys.stderr)
        return fallback

    try:
        from anthropic import Anthropic
    except ImportError:
        print("  ⚠️ anthropic パッケージ未インストール → フォールバック", file=sys.stderr)
        return fallback

    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    seasonal_hint = ""
    if necessity_keyword:
        seasonal_hint = f"""

# 特記事項（重要）
- この商品は「日用品」枠です（キーワード: {necessity_keyword}）
- ふるさと納税で日用品をもらう = 必ず使うものなので実質的な生活費削減、という節約訴求を軸に
- 「どうせ使うもの」「置き場所いらずの配送月選択」「家計の味方」等、実用的で堅実なトーンで
- 食品のような「美味しそう」訴求は不要。賢い選択・堅実さを褒めるトーンが刺さる層です"""
    elif seasonal_keyword:
        seasonal_hint = f"""

# 特記事項（重要）
- この商品は「旬の少し前」のタイミングで紹介する戦略商品です（キーワード: {seasonal_keyword}）
- 「これから旬」「予約しておくとお得」「シーズン前にゲット」等、先取り感を強調してください
- 旬を待つワクワク感、家族で楽しむシーン等、温かみのある先取り訴求を"""

    prompt = f"""以下は楽天ふるさと納税の人気商品です。楽天ROOM投稿用のアピール文を日本語で生成してください。

# 商品情報
- 商品名: {item['name']}
- ショップ: {item['shop']}
- 寄付額: {item['price']:,}円
- 商品説明(冒頭): {item['caption'][:200]}
{seasonal_hint}

# 要件
- 2〜3行、合計100文字以内
- 購買意欲をそそる、温かみのある口調
- 「お得」「節税」「美味しそう」など自然な訴求
- 先頭に絵文字1つ付けてOK（不要なら無し）
- 過剰な煽り(！！！、【超激安】等)は禁止
- 本文のみ返答。前置きや後書きは不要
"""

    try:
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        return text or fallback
    except Exception as e:
        print(f"  ⚠️ Claude API失敗: {e} → フォールバック", file=sys.stderr)
        return fallback


# ── オリジナル画像生成 ─────────────────────────────────────────────────────────

def _find_font(size: int):
    """日本語対応フォントを探して返す。見つからなければPILデフォルト。"""
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _draw_center_text(draw, text: str, center_xy: tuple, font, color: tuple) -> None:
    """中央揃えでテキスト描画。"""
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
    except AttributeError:
        w, h = draw.textsize(text, font=font)
    cx, cy = center_xy
    draw.text((cx - w // 2, cy - h // 2), text, font=font, fill=color)


_UA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _fetch_ogp_image(product_url: str) -> str:
    """商品ページから og:image の画像URLを取得。失敗時は空文字。

    ランキングページのimgタグはlazy-loadプレースホルダーしか持たないため、
    採用された1件の商品ページだけに追加リクエストしてOGP画像を拾う。
    """
    if not product_url:
        return ""
    try:
        r = requests.get(product_url, headers=_UA_HEADERS, timeout=20)
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        og = soup.find("meta", {"property": "og:image"})
        if og and og.get("content"):
            return og["content"].strip()
    except Exception as e:
        print(f"  ⚠️ OGP取得失敗: {e}", file=sys.stderr)
    return ""


def _download_product_image(url: str):
    """楽天の商品画像をダウンロードしてPIL Imageで返す。失敗時はNone。"""
    if not url:
        return None
    try:
        r = requests.get(url, headers=_UA_HEADERS, timeout=20)
        if r.status_code != 200:
            return None
        img = Image.open(io.BytesIO(r.content))
        return img.convert("RGB")
    except Exception as e:
        print(f"  ⚠️ 商品画像DL失敗: {e}", file=sys.stderr)
        return None


def generate_post_image(item: dict) -> "str | None":
    """ROOM投稿用のオリジナル画像を合成し、ファイルパスを返す。失敗時はNone。

    レイアウト（1080x1080 正方形）:
      - 上下に BRAND_GREEN の帯（140px）+ ACCENT_GOLD のアクセントライン
      - 中央に商品画像（720x560 フィット、金の枠線とドロップシャドウ）
      - 画像下に寄付額を大きく表示
      - フッター帯に @ima_raku_entry クレジット
    商品画像DL失敗時は商品名を大きく表示してフォールバック。
    """
    if not PIL_OK:
        print("  ⚠️ Pillow未インストール → 画像生成スキップ", file=sys.stderr)
        return None

    try:
        W, H = IMAGE_SIZE
        canvas = Image.new("RGB", (W, H), BG_CREAM)
        draw = ImageDraw.Draw(canvas)

        # 上下の緑帯 + アクセントライン
        draw.rectangle([0, 0, W, 140], fill=BRAND_GREEN)
        draw.rectangle([0, 140, W, 146], fill=ACCENT_GOLD)
        draw.rectangle([0, H - 146, W, H - 140], fill=ACCENT_GOLD)
        draw.rectangle([0, H - 140, W, H], fill=BRAND_GREEN)

        # ── ヘッダーテキスト ──
        _draw_center_text(draw, "今日のふるさと納税", (W // 2, 55), _find_font(58), (255, 255, 255))
        _draw_center_text(draw, "楽天ランキング上位", (W // 2, 108), _find_font(34), ACCENT_GOLD)

        # ── 商品画像 ──
        # ランキングページのimgはlazy-load placeholderなので、採用した1件だけ
        # 商品ページのOGP画像を拾う（1リクエスト追加）
        image_url = item.get("image_url", "")
        if not image_url or "t.gif" in image_url or "blank" in image_url.lower():
            image_url = _fetch_ogp_image(item.get("url", ""))
            item["image_url"] = image_url  # 後工程用に記録
        product_img = _download_product_image(image_url)
        if product_img is not None:
            target_box = (720, 560)
            product_img.thumbnail(target_box, Image.LANCZOS)
            pw, ph = product_img.size
            paste_x = (W - pw) // 2
            paste_y = 210 + (target_box[1] - ph) // 2
            # ドロップシャドウ
            shadow = 8
            draw.rectangle(
                [paste_x + shadow, paste_y + shadow,
                 paste_x + pw + shadow, paste_y + ph + shadow],
                fill=(210, 200, 190),
            )
            canvas.paste(product_img, (paste_x, paste_y))
            # 金の枠線
            draw.rectangle(
                [paste_x - 3, paste_y - 3, paste_x + pw + 2, paste_y + ph + 2],
                outline=ACCENT_GOLD, width=3,
            )
        else:
            # 画像取れなかった場合は商品名を大きく表示
            clean = strip_name_prefix(item["name"])[:40]
            _draw_center_text(draw, clean, (W // 2, 500), _find_font(40), TEXT_DARK)

        # ── 価格 ──
        if item.get("price"):
            price_text = f"寄付額 {item['price']:,} 円 〜"
            _draw_center_text(draw, price_text, (W // 2, 830), _find_font(56), TEXT_DARK)

        # ── フッター ──
        _draw_center_text(draw, "楽天ROOM  @ima_raku_entry", (W // 2, H - 95), _find_font(34), (255, 255, 255))
        _draw_center_text(draw, "トカゲ | 毎日コツコツ更新中", (W // 2, H - 48), _find_font(28), ACCENT_GOLD)

        canvas.save(OUTPUT_IMAGE_PATH, "PNG", optimize=True)
        print(f"  ✅ オリジナル画像生成: {OUTPUT_IMAGE_PATH}")
        return OUTPUT_IMAGE_PATH
    except Exception as e:
        print(f"  ⚠️ 画像生成失敗: {e}", file=sys.stderr)
        return None


# ── メール組み立て & 送信 ──────────────────────────────────────────────────────

def get_campaign_boost() -> tuple:
    """今日の投稿に載せるブースト文（コピペ用）とハッシュタグを返す。

    ※ 2026年からお買い物マラソンの買いまわりはふるさと納税が対象外に
      なったため、マラソン連動ブーストは廃止（誤情報防止）。
      現在は「5と0のつく日」のみ。
    """
    today = datetime.datetime.now(JST)
    if today.day % 5 == 0:
        note = "今日は5と0のつく日✨ 楽天カードならポイントアップのチャンス"
        tags = " #5と0のつく日"
        label = "5と0のつく日"
        return note, tags, label
    return "", "", ""


def build_email(item: dict, appeal: str, aff_url: str, seasonal_keyword: str = None,
                necessity_keyword: str = None) -> tuple[str, str]:
    clean_name = strip_name_prefix(item["name"])
    short_name = clean_name[:50]

    if necessity_keyword:
        subject = f"【今日のROOM投稿/日用品の日🧻】{short_name}"
        season_tag = f" #{necessity_keyword} #日用品 #節約術"
        season_note = f"🧻 日曜は日用品の日！『{necessity_keyword}』は節約層のど定番。実用訴求でいくぜ\n\n"
    elif seasonal_keyword:
        subject = f"【今日のROOM投稿/旬先取り🌱】{short_name}"
        season_tag = f" #{seasonal_keyword}"
        season_note = f"🌱 今日は『{seasonal_keyword}』の旬先取りピックだぜ！需要が立ち上がる前に投稿しとくと第一想起取れる\n\n"
    else:
        subject = f"【今日のROOM投稿】{short_name}"
        season_tag = ""
        season_note = ""

    boost_note, boost_tags, boost_label = get_campaign_boost()
    if boost_label:
        subject = subject.replace("】", f"/{boost_label}】", 1)
    boost_info = f"🔥 {boost_label} — 買う動機が強い日。投稿効果が高いぜ\n\n" if boost_label else ""
    boost_block = f"\n{boost_note}\n" if boost_note else ""

    body_name = clean_name[:80]
    tags = f"#楽天ROOM #ふるさと納税 #楽天ふるさと納税 #節税 #お得{season_tag}{boost_tags}"

    body = f"""━━━ 今日の楽天ROOM投稿候補 ━━━

{boost_info}{season_note}📮 {body_name}
💰 寄付額 {item['price']:,}円
🏪 {item['shop']}
🔗 {aff_url}

──────────────────
【投稿文コピペ用 ↓ここから↓】

{appeal}
{boost_block}
🔗 {aff_url}

{tags}
【↑ここまで↑】
──────────────────

🎯 月¥10,000を目指してコツコツ投稿
📅 生成: {datetime.datetime.now(JST).strftime('%Y-%m-%d %H:%M')} JST

━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    return subject, body


def send_email(subject: str, body: str, image_path: "str | None" = None) -> None:
    """画像パスが与えられたらmultipartで添付。なければプレーンテキスト。"""
    if image_path and os.path.exists(image_path):
        msg = MIMEMultipart()
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = GMAIL_USER
        msg["To"] = MAIL_TO
        msg.attach(MIMEText(body, "plain", "utf-8"))
        with open(image_path, "rb") as f:
            img_part = MIMEImage(f.read(), _subtype="png")
        img_part.add_header("Content-Disposition", "attachment", filename="room_post.png")
        msg.attach(img_part)
    else:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = GMAIL_USER
        msg["To"] = MAIL_TO

    context = ssl.create_default_context()
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
        server.starttls(context=context)
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.send_message(msg)
    print(f"✅ メール送信成功 → {MAIL_TO}" + (" (画像添付あり)" if image_path else ""))


# ── メイン ─────────────────────────────────────────────────────────────────────

def build_all_sent_email(items: list) -> tuple:
    """ランキング上位が全件投稿済みだった日の通知メール。"""
    top3 = [strip_name_prefix(it["name"])[:50] for it in items[:3]]
    subject = "【ROOM投稿】今日は全件投稿済みだぜ、お休みしよう"
    body = f"""━━━ 今日の楽天ROOM投稿 ━━━

📭 今日のランキング上位は全件投稿済み（重複防止のためスキップ）

──────────────────
今日のランキングTOP3（参考）:
1. {top3[0] if len(top3) > 0 else '-'}
2. {top3[1] if len(top3) > 1 else '-'}
3. {top3[2] if len(top3) > 2 else '-'}
──────────────────

🛌 今日はROOM投稿お休みでOK
🔄 ランキングが更新されれば新しい商品が出てくるはず
📅 生成: {datetime.datetime.now(JST).strftime('%Y-%m-%d %H:%M')} JST

━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    return subject, body


def main() -> int:
    print("🚀 post_room_suggestion.py 開始")

    items = fetch_furusato_items()
    if not items:
        print("❌ ふるさと納税アイテムを1件も取得できなかった", file=sys.stderr)
        return 1

    cache = load_cache()
    now = datetime.datetime.now(JST)

    # 日曜は「日用品の日」: 日用品キーワード一致を最優先（節約層のど定番戦略）
    item, matched_kw, necessity_kw = None, None, None
    if now.weekday() == 6:
        necessities = load_necessity_keywords()
        if necessities:
            item, necessity_kw = pick_by_keywords(items, cache.get("sent_urls", []), necessities)
            if necessity_kw:
                print(f"  🧻 日曜・日用品の日ピック！ キーワード『{necessity_kw}』一致")
            else:
                print("  🧻 日曜だが日用品の未送信一致なし → 通常ロジックへ")

    # 通常ロジック: 季節先取り → ランキング順
    if item is None:
        seasonal_keywords = load_seasonal_keywords(now.month)
        if seasonal_keywords:
            print(f"  🌱 {now.month}月の旬先取りキーワード: {seasonal_keywords}")
        item, matched_kw = pick_item(items, cache.get("sent_urls", []), seasonal_keywords)

    if item is None:
        # 全件投稿済み → 「お休み通知」だけ送ってキャッシュは触らない
        print("  全件投稿済み → お休み通知メールを送信")
        subject, body = build_all_sent_email(items)
        if os.environ.get("DRY_RUN") == "1":
            print("── DRY RUN (メール送信スキップ) ──")
            print(f"件名: {subject}")
            print(body)
            return 0
        send_email(subject, body)
        print("🏁 完了（お休み日）")
        return 0

    if matched_kw:
        print(f"  🌱 旬先取りピック！ キーワード『{matched_kw}』 一致")
    print(f"  選出: {item['name'][:60]}")
    print(f"  寄付額: {item['price']:,}円")

    aff_url = add_affiliate(item["url"])
    appeal = generate_appeal(item, seasonal_keyword=matched_kw, necessity_keyword=necessity_kw)
    print(f"  アピール文: {appeal}")

    # オリジナル画像生成は一旦停止（ROOM上の「オリジナル写真」の趣旨と合わないため）
    # 復活させたい時は下記コメントアウトを外す
    # image_path = generate_post_image(item)
    image_path = None

    subject, body = build_email(item, appeal, aff_url, seasonal_keyword=matched_kw,
                                necessity_keyword=necessity_kw)

    if os.environ.get("DRY_RUN") == "1":
        print("── DRY RUN (メール送信スキップ) ──")
        print(f"件名: {subject}")
        print(body)
        if image_path:
            print(f"添付画像: {image_path}")
        return 0

    send_email(subject, body, image_path=image_path)

    # キャッシュ更新
    base_url = item["url"].split("?")[0]
    sent = cache.get("sent_urls", [])
    sent.insert(0, base_url)
    cache["sent_urls"] = sent[:CACHE_HISTORY_MAX]
    cache["last_sent_date"] = datetime.datetime.now(JST).strftime("%Y-%m-%d")
    save_cache(cache)

    print("🏁 完了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
