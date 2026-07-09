"""Generate assets/icon.ico (run once; the .ico is committed)."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

out = Path("assets")
out.mkdir(exist_ok=True)
img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)
draw.ellipse((16, 16, 240, 240), fill="#c89b3c")
try:
    font = ImageFont.truetype("arialbd.ttf", 110)
except OSError:
    font = ImageFont.load_default()
draw.text((128, 118), "LA", font=font, fill="#0a1428", anchor="mm")
img.save(out / "icon.ico", sizes=[(256, 256), (64, 64), (32, 32), (16, 16)])
print("wrote", out / "icon.ico")
