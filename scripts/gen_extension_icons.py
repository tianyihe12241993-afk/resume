"""Generate distinguishing icon PNGs for the two extensions.

Sourcing  (user)      → indigo→violet gradient, letter "S"
Co-worker (apply-side)→ emerald→teal gradient, letter "C"

Outputs at 16/32/48/128 px, written into each extension's icons/ folder.
"""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent.parent


def _radial_gradient(size: int, color_inner: tuple[int, int, int], color_outer: tuple[int, int, int]) -> Image.Image:
    """Simple diagonal gradient — top-left = inner, bottom-right = outer."""
    img = Image.new("RGBA", (size, size), color_outer + (255,))
    px = img.load()
    for y in range(size):
        for x in range(size):
            # Diagonal interpolation 0..1
            t = (x + y) / (2 * (size - 1))
            r = int(color_inner[0] * (1 - t) + color_outer[0] * t)
            g = int(color_inner[1] * (1 - t) + color_outer[1] * t)
            b = int(color_inner[2] * (1 - t) + color_outer[2] * t)
            px[x, y] = (r, g, b, 255)
    return img


def _round_corners(img: Image.Image, radius_pct: float = 0.22) -> Image.Image:
    """Apply rounded-rect alpha mask. radius_pct is the corner radius as a
    fraction of image width."""
    size = img.size[0]
    r = int(size * radius_pct)
    mask = Image.new("L", img.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), (size - 1, size - 1)], radius=r, fill=255)
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _draw_letter(img: Image.Image, letter: str) -> None:
    size = img.size[0]
    draw = ImageDraw.Draw(img)
    # Try a few font candidates; fall back to default.
    font = None
    for name in (
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        try:
            font = ImageFont.truetype(name, int(size * 0.62), index=0)
            break
        except (OSError, ValueError):
            continue
    if font is None:
        font = ImageFont.load_default()

    # Bounding box trick for vertical-centering.
    bbox = draw.textbbox((0, 0), letter, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = (size - w) // 2 - bbox[0]
    y = (size - h) // 2 - bbox[1] - int(size * 0.04)  # nudge up a touch
    draw.text((x, y), letter, fill=(255, 255, 255, 255), font=font)


def make_icon(letter: str, gradient: tuple[tuple[int, int, int], tuple[int, int, int]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 48, 128):
        img = _radial_gradient(size, gradient[0], gradient[1])
        img = _round_corners(img)
        _draw_letter(img, letter)
        img.save(out_dir / f"icon{size}.png")
        print(f"  wrote {out_dir.name}/icon{size}.png")


if __name__ == "__main__":
    # Sourcing extension — indigo/violet gradient
    make_icon(
        letter="S",
        gradient=((129, 140, 248), (124, 58, 237)),  # indigo-400 → violet-600
        out_dir=ROOT / "extension" / "icons",
    )
    # Co-worker extension — emerald/teal gradient (distinctly different)
    make_icon(
        letter="C",
        gradient=((52, 211, 153), (13, 148, 136)),  # emerald-400 → teal-600
        out_dir=ROOT / "extension-coworker" / "icons",
    )
    print("Done.")
