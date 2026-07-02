#!/usr/bin/env python3
"""Generate application icons for Traducteur PDF"""
import os
from PIL import Image, ImageDraw, ImageFont

SIZES = [16, 22, 24, 32, 48, 64, 128, 256]
COLORS = {
    "bg": (0x31, 0x32, 0x44),       # #313244 (card bg)
    "accent": (0x89, 0xB4, 0xFA),    # #89b4fa
    "white": (0xCD, 0xD6, 0xF4),     # #cdd6f4
    "green": (0xA6, 0xE3, 0xA1),     # #a6e3a1
}

def draw_icon(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded rect background
    margin = max(1, size // 16)
    r = max(2, size // 6)
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=r, fill=COLORS["bg"]
    )

    # Accent stripe top
    stripe_h = max(2, size // 14)
    draw.rounded_rectangle(
        [margin, margin, size - margin, margin + stripe_h],
        radius=1, fill=COLORS["accent"]
    )

    # "PDF" text
    try:
        font_size = size // 4
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except:
        font = ImageFont.load_default()

    # Letter "P" stylized as document
    cx, cy = size // 2, size // 2
    doc_w = size * 3 // 8
    doc_h = size * 5 // 12
    doc_x = cx - doc_w // 2
    doc_y = cy - doc_h // 2 + size // 20

    # Document shape
    doc_r = max(1, size // 20)
    draw.rounded_rectangle(
        [doc_x, doc_y, doc_x + doc_w, doc_y + doc_h],
        radius=doc_r, fill=COLORS["white"]
    )

    # Text lines on document
    line_y = doc_y + doc_h // 4
    line_h = max(1, size // 30)
    for i in range(4):
        lw = doc_w * (3 - i * 0.3) // 4
        lx = doc_x + (doc_w - lw) // 2
        if i == 0:
            draw.rounded_rectangle([lx, line_y, lx + lw, line_y + line_h], radius=1, fill=COLORS["accent"])
        else:
            draw.rounded_rectangle([lx, line_y, lx + lw, line_y + line_h], radius=1, fill=COLORS["bg"])
        line_y += doc_h // 5 + 1

    # Small globe/translate icon in corner
    g_size = size // 5
    g_x = size - margin - g_size - 1
    g_y = margin + 2
    draw.ellipse([g_x, g_y, g_x + g_size, g_y + g_size], fill=COLORS["green"])

    return img

def main():
    outdir = os.path.join(os.path.dirname(__file__), "icons")
    for s in SIZES:
        img = draw_icon(s)
        path = os.path.join(outdir, f"traducteur-pdf-{s}.png")
        os.makedirs(outdir, exist_ok=True)
        img.save(path, "PNG")
        print(f"  {path} ({s}x{s})")
    # Copy 256 as default
    default = os.path.join(outdir, "traducteur-pdf-256.png")
    dest = os.path.join(outdir, "traducteur-pdf.png")
    import shutil
    shutil.copy(default, dest)
    print(f"  {dest} (default)")

if __name__ == "__main__":
    main()
