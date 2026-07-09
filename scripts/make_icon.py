"""Generate the app logo assets from assets/logo-source.jpg.

Circular-crops the source art (removing the black corners), producing:
  - assets/logo.png  (512x512, transparent outside the circle) — used at runtime
  - assets/icon.ico  (multi-size)                              — used by PyInstaller

Run once when the source art changes; both outputs are committed.
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SUPERSAMPLE = 4  # antialias the circle edge


def circular_crop(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    w, h = img.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    img = img.crop((left, top, left + side, top + side))

    big = side * SUPERSAMPLE
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, big - 1, big - 1), fill=255)
    img.putalpha(mask.resize((side, side), Image.LANCZOS))
    return img


def main() -> None:
    source = Image.open(ASSETS / "logo-source.jpg")
    logo = circular_crop(source).resize((512, 512), Image.LANCZOS)
    logo.save(ASSETS / "logo.png")
    logo.save(ASSETS / "icon.ico",
              sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print("wrote", ASSETS / "logo.png", "and", ASSETS / "icon.ico")


if __name__ == "__main__":
    main()
