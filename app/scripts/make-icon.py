"""Draws the app icon (a magnifying glass over a photo) and writes
build/icon.png (1024 px, macOS/Linux) and build/icon.ico (16–256 px, Windows).
Run: python3 scripts/make-icon.py   (needs Pillow)"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

S = 4096  # drawn large, scaled down for smooth edges
OUT = Path(__file__).resolve().parent.parent / "build"


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # Background: a rounded square with a diagonal green gradient.
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    top, bottom = (58, 128, 80), (22, 61, 38)
    for y in range(S):
        gd.line([(0, y), (S, y)], fill=lerp(top, bottom, y / S) + (255,))
    mask = Image.new("L", (S, S), 0)
    m = S * 0.06
    ImageDraw.Draw(mask).rounded_rectangle([m, m, S - m, S - m], radius=S * 0.2, fill=255)
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)
    cx, cy, r = S * 0.43, S * 0.43, S * 0.25   # the lens
    ring = S * 0.065
    # Handle (under the ring), drawn as a thick rounded line.
    hx0, hy0 = cx + r * 0.72, cy + r * 0.72
    hx1, hy1 = S * 0.80, S * 0.80
    w = S * 0.11
    d.line([(hx0, hy0), (hx1, hy1)], fill=(245, 241, 228, 255), width=round(w))
    d.ellipse([hx1 - w / 2, hy1 - w / 2, hx1 + w / 2, hy1 + w / 2], fill=(245, 241, 228, 255))

    # Inside the lens: a small photo (sky, sun, two hills), clipped to the circle.
    photo = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    pd = ImageDraw.Draw(photo)
    pd.rectangle([0, 0, S, S], fill=(186, 222, 236, 255))
    pd.ellipse([cx + r * 0.15, cy - r * 0.62, cx + r * 0.55, cy - r * 0.22], fill=(255, 205, 86, 255))
    pd.polygon([(cx - r * 1.1, cy + r * 1.1), (cx - r * 0.35, cy - r * 0.15), (cx + r * 0.35, cy + r * 1.1)], fill=(64, 140, 92, 255))
    pd.polygon([(cx - r * 0.2, cy + r * 1.1), (cx + r * 0.42, cy + r * 0.12), (cx + r * 1.1, cy + r * 1.1)], fill=(38, 101, 64, 255))
    lens = Image.new("L", (S, S), 0)
    ImageDraw.Draw(lens).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    img.paste(photo, (0, 0), lens)

    # A soft shine on the glass.
    shine = Image.new("L", (S, S), 0)
    ImageDraw.Draw(shine).ellipse([cx - r * 0.75, cy - r * 0.8, cx - r * 0.05, cy - r * 0.35], fill=90)
    shine = shine.filter(ImageFilter.GaussianBlur(S * 0.01))
    img.paste((255, 255, 255, 255), (0, 0), Image.composite(shine, Image.new("L", (S, S), 0), lens))

    # The ring.
    d.ellipse([cx - r - ring / 2, cy - r - ring / 2, cx + r + ring / 2, cy + r + ring / 2],
              outline=(245, 241, 228, 255), width=round(ring))
    return img


big = draw()
OUT.mkdir(exist_ok=True)
png = big.resize((1024, 1024), Image.LANCZOS)
png.save(OUT / "icon.png")
big.resize((256, 256), Image.LANCZOS).save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
# A preview of the small sizes, side by side, for checking legibility.
sheet = Image.new("RGBA", (16 + 24 + 32 + 48 + 64 + 128 + 256 + 8 * 10, 266), (240, 240, 240, 255))
x = 10
for n in (16, 24, 32, 48, 64, 128, 256):
    sheet.paste(big.resize((n, n), Image.LANCZOS), (x, 256 - n + 5), big.resize((n, n), Image.LANCZOS))
    x += n + 10
sheet.save(OUT / "icon-sizes-preview.png")
print("wrote", *sorted(p.name for p in OUT.iterdir()))
