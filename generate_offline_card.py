#!/usr/bin/env python3
"""
オフ会用 紹介ハガキ (postcard) 生成スクリプト
imaraku.html サイト + Xアカウントの2つのQRコードを並べたカードを作る。
出力: imaraku_offline_card.png （ハガキサイズ 100x148mm @ 300dpi = 1181x1748px）
"""
from PIL import Image, ImageDraw, ImageFont
import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers.pil import RoundedModuleDrawer
from qrcode.image.styles.colormasks import SolidFillColorMask

# ── サイズ・パス ─────────────────────────────────────────────────
W, H = 1181, 1748   # ハガキサイズ @300dpi
OUT_PATH = "imaraku_offline_card.png"

SITE_URL = "https://imaraku.github.io/imaraku/imaraku.html"
X_URL    = "https://x.com/ima_raku_entry"

# ── カラーパレット（楽天系の赤金 + 落ち着き）──────────────────
BG_TOP    = (250, 245, 235)   # 暖色オフホワイト
BG_BOT    = (255, 240, 220)   # 上→下グラデ
ACCENT    = (191, 0, 0)       # 楽天レッド
GOLD      = (218, 165, 32)    # ゴールド
INK       = (40, 25, 25)      # 濃赤茶（テキスト）
SUB_INK   = (110, 80, 75)     # サブテキスト
WHITE     = (255, 255, 255)
QR_DARK   = (191, 0, 0)       # QRも赤に

# ── フォント ─────────────────────────────────────────────────
JP_BOLD   = "/System/Library/Fonts/ヒラギノ角ゴシック W7.ttc"
JP_HEAVY  = "/System/Library/Fonts/ヒラギノ角ゴシック W9.ttc"
JP_REG    = "/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc"

def font(path, size):
    return ImageFont.truetype(path, size)

# ── 背景: グラデーション ─────────────────────────────────────
def make_gradient_bg(w, h, top, bot):
    img = Image.new("RGB", (w, h), top)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        ratio = y / h
        r = int(top[0] * (1 - ratio) + bot[0] * ratio)
        g = int(top[1] * (1 - ratio) + bot[1] * ratio)
        b = int(top[2] * (1 - ratio) + bot[2] * ratio)
        draw.line([(0, y), (w, y)], fill=(r, g, b))
    return img

img = make_gradient_bg(W, H, BG_TOP, BG_BOT)
draw = ImageDraw.Draw(img)

# ── 装飾: 上下のリボン ─────────────────────────────────────
RIBBON_H = 14
draw.rectangle([0, 0, W, RIBBON_H], fill=ACCENT)
draw.rectangle([0, RIBBON_H, W, RIBBON_H + 6], fill=GOLD)
draw.rectangle([0, H - RIBBON_H - 6, W, H - RIBBON_H], fill=GOLD)
draw.rectangle([0, H - RIBBON_H, W, H], fill=ACCENT)

# ── ヘッダー ─────────────────────────────────────────────────
TITLE_Y = 110
title_font = font(JP_HEAVY, 160)
sub_font   = font(JP_BOLD, 50)
tag_font   = font(JP_BOLD, 38)

# 「今楽」大タイトル
title = "今楽"
tw = draw.textbbox((0, 0), title, font=title_font)[2]
draw.text(((W - tw) / 2, TITLE_Y), title, font=title_font, fill=ACCENT)

# サブタイトル
subtitle = "imaraku"
sw = draw.textbbox((0, 0), subtitle, font=sub_font)[2]
draw.text(((W - sw) / 2, TITLE_Y + 200), subtitle, font=sub_font, fill=GOLD)

# キャッチコピー（共感ターゲティング）
copy_lines = [
    "楽天で買う前に「エントリー忘れた…」",
    "を なくす まとめサイト",
]
copy_font = font(JP_BOLD, 52)
y = TITLE_Y + 290
for line in copy_lines:
    cw = draw.textbbox((0, 0), line, font=copy_font)[2]
    draw.text(((W - cw) / 2, y), line, font=copy_font, fill=INK)
    y += 70

# ── 共感セクション（誇大広告ではなく「悩み解決」訴求）──
empathy_y = y + 50

# 問いかけ
ask_font = font(JP_BOLD, 44)
ask_text = "こんな経験、ありませんか？"
aw = draw.textbbox((0, 0), ask_text, font=ask_font)[2]
draw.text(((W - aw) / 2, empathy_y), ask_text, font=ask_font, fill=INK)
empathy_y += 80

# お悩みリスト（左揃えグループを中央配置）
pain_font = font(JP_BOLD, 38)
pains = [
    "エントリー忘れて損した",
    "キャンペーンが多すぎて分からない",
    "いつ買うのがお得か悩む",
]
# 一番長い行に合わせてグループ全体の幅を計算
max_pain_w = max(draw.textbbox((0, 0), p, font=pain_font)[2] for p in pains)
mark_w = 56  # マーカー（円）分のスペース
group_w = mark_w + max_pain_w
group_x = (W - group_w) // 2

for p in pains:
    # マーカー（ゴールドの塗り潰し円）— フォント非依存で文字化けしない
    cy = empathy_y + 22  # テキスト中央付近
    draw.ellipse(
        [group_x + 8, cy - 7, group_x + 8 + 14, cy + 7],
        fill=GOLD,
    )
    # お悩みテキスト
    draw.text((group_x + mark_w, empathy_y), p, font=pain_font, fill=INK)
    empathy_y += 60

empathy_y += 30

# 締めの一文（謙虚・誠実）
closing_font = font(JP_BOLD, 40)
closing_lines = [
    "そんな小さな悔しさを 減らせたらと",
    "思って 作ったサイトです。",
]
for line in closing_lines:
    cw = draw.textbbox((0, 0), line, font=closing_font)[2]
    draw.text(((W - cw) / 2, empathy_y), line, font=closing_font, fill=SUB_INK)
    empathy_y += 56

# ── QRコード生成 ────────────────────────────────────────────
def make_qr(url, color):
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=12,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    qr_img = qr.make_image(
        image_factory=StyledPilImage,
        module_drawer=RoundedModuleDrawer(),
        color_mask=SolidFillColorMask(front_color=color, back_color=WHITE),
    ).convert("RGB")
    return qr_img

QR_SIZE = 380
site_qr = make_qr(SITE_URL, QR_DARK).resize((QR_SIZE, QR_SIZE), Image.LANCZOS)
x_qr    = make_qr(X_URL, (15, 20, 25)).resize((QR_SIZE, QR_SIZE), Image.LANCZOS)

# QRコード配置（横並び・中央揃え）
QR_Y     = 1080
GAP_X    = 80
qr_total_w = QR_SIZE * 2 + GAP_X
left_x   = (W - qr_total_w) // 2
right_x  = left_x + QR_SIZE + GAP_X

# QR枠（白背景＋影効果）
def paste_qr_with_label(qr_img, x, y, label_top, label_main, frame_color):
    # フレーム（白背景に少し外側のラベル）
    PAD = 22
    LABEL_H = 60
    # 影
    shadow_offset = 8
    shadow = Image.new("RGB", (QR_SIZE + PAD*2, QR_SIZE + PAD*2 + LABEL_H), (0, 0, 0))
    shadow_alpha = Image.new("L", shadow.size, 0)
    sdraw = ImageDraw.Draw(shadow_alpha)
    sdraw.rounded_rectangle([0, 0, shadow.size[0], shadow.size[1]], radius=20, fill=80)
    img.paste(shadow, (x - PAD + shadow_offset, y - PAD + shadow_offset), shadow_alpha)

    # 白い枠
    frame = Image.new("RGB", (QR_SIZE + PAD*2, QR_SIZE + PAD*2 + LABEL_H), WHITE)
    fdraw = ImageDraw.Draw(frame)
    # 上部に色付きラベル
    fdraw.rounded_rectangle([0, 0, frame.size[0], LABEL_H + 10], radius=20, fill=frame_color)
    fdraw.rectangle([0, LABEL_H - 10, frame.size[0], LABEL_H + 10], fill=frame_color)
    # 上部ラベルテキスト
    label_top_font = font(JP_HEAVY, 30)
    label_main_font = font(JP_HEAVY, 36)
    ltw = fdraw.textbbox((0, 0), label_top, font=label_top_font)[2]
    fdraw.text(((frame.size[0] - ltw) / 2, 8), label_top, font=label_top_font, fill=WHITE)
    # ラベル下のメインテキスト（フレーム下部に）
    frame_with_mask = Image.new("RGB", frame.size, WHITE)
    frame_with_mask.paste(frame, (0, 0))
    # マスクで角丸
    mask = Image.new("L", frame.size, 0)
    mdraw = ImageDraw.Draw(mask)
    mdraw.rounded_rectangle([0, 0, frame.size[0], frame.size[1]], radius=20, fill=255)
    img.paste(frame_with_mask, (x - PAD, y - PAD), mask)
    # QR本体
    img.paste(qr_img, (x, y + LABEL_H - 5))
    # フレーム下のメインテキスト
    main_y = y + LABEL_H + QR_SIZE + 16
    main_w = draw.textbbox((0, 0), label_main, font=label_main_font)[2]
    draw.text((x + (QR_SIZE - main_w) / 2, main_y), label_main, font=label_main_font, fill=INK)

paste_qr_with_label(site_qr, left_x, QR_Y, "WEBサイト", "今すぐエントリー", ACCENT)
paste_qr_with_label(x_qr, right_x, QR_Y, "Xアカウント", "@ima_raku_entry", (15, 20, 25))

# ── フッター ─────────────────────────────────────────────────
foot_y = H - 110
foot_lines = [
    "スマホで読み取って今すぐチェック",
    "完全無料・個人開発・押し売りなし",
]
foot_font = font(JP_BOLD, 32)
foot_sub = font(JP_REG, 26)
fw = draw.textbbox((0, 0), foot_lines[0], font=foot_font)[2]
draw.text(((W - fw) / 2, foot_y), foot_lines[0], font=foot_font, fill=ACCENT)
fw2 = draw.textbbox((0, 0), foot_lines[1], font=foot_sub)[2]
draw.text(((W - fw2) / 2, foot_y + 48), foot_lines[1], font=foot_sub, fill=SUB_INK)

# 保存
img.save(OUT_PATH, dpi=(300, 300), quality=95)
print(f"✅ 生成完了: {OUT_PATH} ({W}x{H} @ 300dpi)")
