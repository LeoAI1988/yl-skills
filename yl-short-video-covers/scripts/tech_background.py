"""Load the approved reusable background. Never synthesize a replacement."""
from pathlib import Path
import hashlib
from PIL import Image, ImageEnhance, ImageDraw

STYLE_VERSION = "mature-circuit-v2"
BACKGROUND_ID = "background-black-yellow-tech-v2"
BACKGROUND_SHA256 = "ee53e201a98d2fa9ad66f118f80c8ae1999f6781728c54bb220bd1dd311cb1c2"
DEFAULT_BACKGROUND = Path(__file__).resolve().parents[1] / "assets" / (BACKGROUND_ID + ".png")


def approved_background_path(path=None):
    selected = Path(path) if path else DEFAULT_BACKGROUND
    if not selected.is_file():
        raise FileNotFoundError("Approved circuit master is missing; restore the bundled asset, do not redraw or substitute it")
    if hashlib.sha256(selected.read_bytes()).hexdigest() != BACKGROUND_SHA256:
        raise ValueError("Background differs from the approved master; a similar circuit image is not the same template")
    return selected


def make_tech_background(width=1080, height=1440, path=None):
    with Image.open(approved_background_path(path)) as image:
        return image.convert("RGB").resize((width, height), Image.Resampling.LANCZOS)


def prepared_background(width=1080, height=1440, path=None):
    image = ImageEnhance.Contrast(make_tech_background(width, height, path)).enhance(1.05).convert("RGBA")
    shade = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(shade)
    for x in range(width):
        alpha = round(145 * max(0.0, 1.0 - x / (width * 0.78)))
        draw.line((x, 0, x, height), fill=(0, 0, 0, alpha))
    return Image.alpha_composite(image, shade)


def texture_pixels(image):
    """Evidence of visible circuitry in the lower-left free background corridor."""
    w,h=image.size
    crop=image.convert("RGB").crop((int(w*.03),int(h*.79),int(w*.28),int(h*.94)))
    return sum(1 for r,g,b in crop.getdata() if 24 <= max(r,g,b) <= 165 and max(r,g,b)-min(r,g,b)<65)
