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
CACHE_HISTORY_MAX  = 30
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

FURUSATO_RANKING_URL = "https://event.rakuten.co.jp/furusato/ranking/"
# 楽天ふるさと納税の商品URLパターン: item.rakuten.co.jp/f[5-6桁数字]-[自治体名]/...
# 「f + 数字」プレフィックスは自治体ショップの証。ブランドショップと区別できる確実な目印。
FURUSATO_URL_RE = re.compile(r"https?://item\.rakuten\.co\.jp/f\d+-[^/]+/")
PRICE_RE = re.compile(r"([0-9][0-9,]{2,})\s*円")


def _extract_name_from_link(a) -> str:
    """<a> タグから商品名を抽出。imgのaltを優先、なければテキスト。"""
    img = a.find("img")
    if img and img.get("alt"):
        alt = img["alt"].strip()
        if len(alt) >= 5:
            return alt
    text = a.get_text(" ", strip=True)
    return text[:120] if text else ""


def _extract_image_url(a) -> str:
    """<a> 内の <img> から画像URLを抽出。lazy-load属性も考慮。"""
    img = a.find("img")
    if not img:
        return ""
    for attr in ("src", "data-src", "data-original", "data-lazy-src"):
        url = img.get(attr)
        if url and url.strip():
            url = url.strip()
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = "https://event.rakuten.co.jp" + url
            # プレースホルダーや1px透過GIF等は除外
            if url.endswith(".gif") and "blank" in url.lower():
                continue
            if url.startswith("data:"):
                continue
            return url
    return ""


def _extract_price_near(a) -> int:
    """<a> の周辺テキストから寄付額を推定。親要素を2段階辿って円の数字を拾う。"""
    for node in (a, a.parent, getattr(a.parent, "parent", None)):
        if node is None:
            continue
        text = node.get_text(" ", strip=True)
        m = PRICE_RE.search(text)
        if m:
            try:
                return int(m.group(1).replace(",", ""))
            except ValueError:
                continue
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

    soup = BeautifulSoup(r.text, "html.parser")
    seen_base = set()
    items: list[dict] = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not FURUSATO_URL_RE.match(href):
            continue
        base = href.split("?")[0].rstrip("/")
        if base in seen_base:
            continue
        name = _extract_name_from_link(a)
        if not name or len(name) < 5:
            continue
        price = _extract_price_near(a)
        # 自治体名をURLのf000000-xxxxx部分から抽出してshopフィールドに入れる
        shop = ""
        m = re.match(r"https?://item\.rakuten\.co\.jp/(f\d+-[^/]+)/", href)
        if m:
            shop = m.group(1)

        image_url = _extract_image_url(a)

        seen_base.add(base)
        items.append({
            "name": name.strip(),
            "url": base + "/",
            "price": price,
            "shop": shop,
            "image_url": image_url,
            "caption": "",
        })
        if len(items) >= 30:
            break

    print(f"  スクレイピング取得: {len(items)} 件")
    return items


def fetch_furusato_items() -> list[dict]:
    """楽天ふるさと納税ランキングをスクレイピングで取得。"""
    return fetch_via_scrape()


# ── 商品選出 ───────────────────────────────────────────────────────────────────

def pick_item(items: list[dict], sent_urls: list[str]) -> dict | None:
    """未送信の最上位アイテムを返す。"""
    sent_set = set(sent_urls)
    for it in items:
        base_url = it["url"].split("?")[0]
        if base_url not in sent_set:
            return it
    return None


# ── アピール文生成 ─────────────────────────────────────────────────────────────

def generate_appeal(item: dict) -> str:
    """Claude Haiku にアピール文を生成させる。失敗時はフォールバック文を返す。"""
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

    prompt = f"""以下は楽天ふるさと納税の人気商品です。楽天ROOM投稿用のアピール文を日本語で生成してください。

# 商品情報
- 商品名: {item['name']}
- ショップ: {item['shop']}
- 寄付額: {item['price']:,}円
- 商品説明(冒頭): {item['caption'][:200]}

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

def build_email(item: dict, appeal: str, aff_url: str) -> tuple[str, str]:
    clean_name = strip_name_prefix(item["name"])
    short_name = clean_name[:50]
    subject = f"【今日のROOM投稿】{short_name}"

    body_name = clean_name[:80]
    tags = "#楽天ROOM #ふるさと納税 #楽天ふるさと納税 #節税 #お得"

    body = f"""━━━ 今日の楽天ROOM投稿候補 ━━━

📮 {body_name}
💰 寄付額 {item['price']:,}円
🏪 {item['shop']}
🔗 {aff_url}

📎 オリジナル画像を添付したぜ（room_post.png）
   → ROOM投稿時に画像として選択するとC→Bランクアップ条件クリア

──────────────────
【投稿文コピペ用 ↓ここから↓】

{appeal}

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

def main() -> int:
    print("🚀 post_room_suggestion.py 開始")

    items = fetch_furusato_items()
    if not items:
        print("❌ ふるさと納税アイテムを1件も取得できなかった", file=sys.stderr)
        return 1

    cache = load_cache()
    item = pick_item(items, cache.get("sent_urls", []))
    if item is None:
        print("  全て送信済み → キャッシュをリセットしてTOPを採用")
        cache["sent_urls"] = []
        item = items[0]

    print(f"  選出: {item['name'][:60]}")
    print(f"  寄付額: {item['price']:,}円")

    aff_url = add_affiliate(item["url"])
    appeal = generate_appeal(item)
    print(f"  アピール文: {appeal}")

    # オリジナル画像生成（C→Bランクアップ条件対応）
    image_path = generate_post_image(item)

    subject, body = build_email(item, appeal, aff_url)

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
