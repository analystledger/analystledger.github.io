"""Branded square/portrait image cards for social posts (Instagram, TikTok, Facebook, etc.)."""
import os

from PIL import Image, ImageDraw, ImageFont

NAVY, BLUE, WHITE, MUTED, GREEN, RED = "#0b1730", "#0b5fff", "#ffffff", "#9fb0cc", "#3ddc84", "#ff6b6b"
FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", "/usr/share/fonts/TTF"]


def font(size, bold=False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for d in FONT_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def wrap(draw, text, fnt, width):
    lines, line = [], ""
    for word in text.split():
        test = (line + " " + word).strip()
        if draw.textlength(test, font=fnt) <= width:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def logo(draw, x, y, s):
    draw.rounded_rectangle([x, y, x + s, y + s], radius=s // 4.5, fill=BLUE)
    bw = s // 8
    for i, (h, op) in enumerate([(0.22, "#9dbbff"), (0.38, "#cddcff"), (0.53, WHITE)]):
        bx = x + s * (0.22 + i * 0.22)
        draw.rounded_rectangle([bx, y + s * (0.78 - h), bx + bw, y + s * 0.78], radius=3, fill=op)


def card(path, kicker, title, lines, footer, size=(1080, 1350), accent=None):
    """kicker: small label; title: big text; lines: list of (text, colour or None)."""
    W, H = size
    img = Image.new("RGB", size, NAVY)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 14], fill=accent or BLUE)
    logo(d, 70, 70, 76)
    d.text((166, 84), "Analyst Ledger", font=font(42, True), fill=WHITE)
    y = 220
    d.text((70, y), kicker.upper(), font=font(32, True), fill=accent or "#7cb0ff")
    y += 60
    tf = font(64 if len(title) < 40 else 52, True)
    for ln in wrap(d, title, tf, W - 140)[:4]:
        d.text((70, y), ln, font=tf, fill=WHITE)
        y += tf.size + 14
    y += 30
    bf = font(36)
    for text, col in lines:
        for ln in wrap(d, text, bf, W - 140):
            if y > H - 200:
                break
            d.text((70, y), ln, font=bf, fill=col or "#dbe4f3")
            y += 50
        y += 14
    d.line([70, H - 150, W - 70, H - 150], fill="#22345a", width=2)
    d.text((70, H - 125), footer, font=font(30, True), fill="#7cb0ff")
    d.text((70, H - 80), "Not investment advice. Data may be delayed.", font=font(26), fill=MUTED)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, "PNG", optimize=True)
    return path
