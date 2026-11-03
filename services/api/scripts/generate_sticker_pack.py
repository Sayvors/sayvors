"""Regenerate the fixed AI sticker pack.

The assistant never draws art at runtime. It chooses one of three bundled
stickers with a hidden marker, and the pipeline uploads the matching WebP.
This script is the reproducible source for those files:

    python services/api/scripts/generate_sticker_pack.py

Requirements are WhatsApp's static sticker limits: 512x512 WebP, transparent
background, under 100 KB.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SIZE = 512
SUPERSAMPLE = 2
TARGET_BYTES = 100 * 1024
FONT_CANDIDATES = (
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)

OUT = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "modules"
    / "channels"
    / "meta"
    / "assets"
    / "stickers"
)

PACK = {
    "ok": {"label": "OK", "bg": (0, 168, 132), "ink": (255, 255, 255)},
    "thanks": {"label": "THANKS", "bg": (176, 51, 138), "ink": (255, 255, 255)},
    "done": {"label": "DONE", "bg": (61, 29, 110), "ink": (255, 255, 255)},
}


def _font_path() -> str:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    raise SystemExit("No bold font found; add one to FONT_CANDIDATES.")


def _bubble(size: int) -> Image.Image:
    """A rounded speech bubble with a tail, drawn at supersampled size."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = int(size * 0.10)
    radius = int(size * 0.20)
    box = (margin, margin, size - margin, int(size * 0.78))
    draw.rounded_rectangle(box, radius=radius, fill=(255, 255, 255, 255))
    # The tail is a small triangular notch at the bottom-left, kept inside the
    # safe area so WhatsApp's crop never clips it.
    tail = [
        (int(size * 0.24), int(size * 0.75)),
        (int(size * 0.20), int(size * 0.90)),
        (int(size * 0.40), int(size * 0.78)),
    ]
    draw.polygon(tail, fill=(255, 255, 255, 255))
    return image


def _fit_font(path: str, label: str, max_width: int) -> ImageFont.FreeTypeFont:
    size = 160
    while size > 40:
        font = ImageFont.truetype(path, size)
        left, _, right, _ = font.getbbox(label)
        if right - left <= max_width:
            return font
        size -= 4
    return ImageFont.truetype(path, 40)


def render(key: str) -> Path:
    spec = PACK[key]
    canvas_size = SIZE * SUPERSAMPLE
    canvas = _bubble(canvas_size)

    # Coloured inner face, inset from the white rim. This gives the sticker a
    # printed, physical edge without a gradient.
    face = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(face)
    margin = int(canvas_size * 0.12)
    radius = int(canvas_size * 0.18)
    draw.rounded_rectangle(
        (margin, margin, canvas_size - margin, int(canvas_size * 0.76)),
        radius=radius,
        fill=(*spec["bg"], 255),
    )
    draw.polygon(
        [
            (int(canvas_size * 0.25), int(canvas_size * 0.73)),
            (int(canvas_size * 0.21), int(canvas_size * 0.87)),
            (int(canvas_size * 0.39), int(canvas_size * 0.75)),
        ],
        fill=(*spec["bg"], 255),
    )
    canvas = Image.alpha_composite(canvas, face)

    draw = ImageDraw.Draw(canvas)
    font = _fit_font(_font_path(), spec["label"], int(canvas_size * 0.62))
    left, top, right, bottom = draw.textbbox((0, 0), spec["label"], font=font)
    x = (canvas_size - (right - left)) / 2 - left
    y = int(canvas_size * 0.43) - (bottom - top) / 2 - top
    draw.text((x, y), spec["label"], font=font, fill=(*spec["ink"], 255))

    # Two small sparkles: enough personality to read as a sticker, flat enough
    # to compress to a few kilobytes.
    sparkle = int(canvas_size * 0.035)
    for cx, cy in (
        (int(canvas_size * 0.22), int(canvas_size * 0.22)),
        (int(canvas_size * 0.78), int(canvas_size * 0.30)),
    ):
        draw.polygon(
            [
                (cx, cy - sparkle),
                (cx + sparkle // 3, cy - sparkle // 3),
                (cx + sparkle, cy),
                (cx + sparkle // 3, cy + sparkle // 3),
                (cx, cy + sparkle),
                (cx - sparkle // 3, cy + sparkle // 3),
                (cx - sparkle, cy),
                (cx - sparkle // 3, cy - sparkle // 3),
            ],
            fill=(255, 255, 255, 220),
        )

    # A soft shadow under the bubble, blurred before the downscale so the edge
    # stays smooth. It sits on transparent pixels, never a background fill.
    shadow = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.rounded_rectangle(
        (
            margin + int(canvas_size * 0.012),
            margin + int(canvas_size * 0.02),
            canvas_size - margin + int(canvas_size * 0.012),
            int(canvas_size * 0.76) + int(canvas_size * 0.02),
        ),
        radius=radius,
        fill=(0, 0, 0, 55),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(canvas_size * 0.012))
    composed = Image.alpha_composite(shadow, canvas)

    final = composed.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{key}.webp"
    final.save(path, "WEBP", quality=92, method=6)
    measured = path.stat().st_size
    if measured >= TARGET_BYTES:
        raise SystemExit(
            f"{path.name} is {measured} bytes; WhatsApp's static limit is "
            f"{TARGET_BYTES}."
        )
    return path


def main() -> None:
    for key in PACK:
        path = render(key)
        print(f"{path.name}: {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
