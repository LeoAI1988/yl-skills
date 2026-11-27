#!/usr/bin/env python3
"""Render a real-scene cover with a slanted headline and an optional evidence card."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from font_utils import find_chinese_font


CANVAS = (1080, 1440)
WHITE = (250, 249, 245, 255)
GOLD = (255, 205, 52, 255)
INK = (17, 19, 22, 255)
TITLE_MARGIN = 16
CARD_PADDING = (28, 24)
TAG_PADDING = (20, 10)


def parse_box(value: str) -> tuple[int, int, int, int]:
    try:
        left, top, right, bottom = (int(part) for part in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected x0,y0,x1,y1 in pixels") from exc
    if left >= right or top >= bottom or min(left, top) < 0:
        raise argparse.ArgumentTypeError("expected a nonempty box with nonnegative coordinates")
    return left, top, right, bottom


def parse_ratios(value: str) -> list[float]:
    try:
        ratios = [float(part) for part in value.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected comma-separated line-size ratios") from exc
    if any(not math.isfinite(ratio) or ratio <= 0 for ratio in ratios):
        raise argparse.ArgumentTypeError("line-size ratios must be positive and finite")
    largest = max(ratios)
    return [ratio / largest for ratio in ratios]


def text_lines(value: str) -> list[str]:
    lines = [line.strip() for line in value.split("|")]
    if any(not line or "\n" in line for line in lines):
        raise ValueError("pass complete individual lines separated by |")
    return lines


def source_crop(source: Image.Image, selection: tuple[int, int, int, int]) -> Image.Image:
    if selection[2] > source.width or selection[3] > source.height:
        raise ValueError("crop box exceeds the oriented photo")
    return ImageOps.fit(source.crop(selection), CANVAS, method=Image.Resampling.LANCZOS)


def line_image(text, font, bounds, fill, outline, slant, tilt, accents, accent_color, weight=0):
    left, top, right, bottom = bounds
    origin = (2 - left, 2 - top)
    image = Image.new("RGBA", (right - left + 4, bottom - top + 4))
    draw = ImageDraw.Draw(image)
    draw.text(origin, text, font=font, fill=fill, stroke_width=outline+weight, stroke_fill=INK)
    if weight:
        draw.text(origin, text, font=font, fill=fill, stroke_width=weight, stroke_fill=fill)
    for accent in accents:
        position = origin[0] + font.getlength(text[:accent.start()])
        draw.text((position, origin[1]), accent.group(), font=font, fill=accent_color)
    if slant:
        shear = math.tan(math.radians(slant))
        extension = math.ceil(shear * image.height)
        image = image.transform(
            (image.width + extension, image.height), Image.Transform.AFFINE,
            (1, shear, -extension, 0, 1, 0), resample=Image.Resampling.BICUBIC,
        )
    if tilt:
        image = image.rotate(tilt, expand=True, resample=Image.Resampling.BICUBIC)
    visible = image.getchannel("A").getbbox()
    if visible is None:
        raise ValueError(f"no visible glyphs for {text!r}")
    return image.crop(visible)


def fit_lines(lines, font_path, ratios, size, gap, fills, *, max_font, slant=0,
              tilt=0, outline=0, accent_terms=(), accent_color=GOLD, weight=0):
    if len(ratios) != len(lines):
        raise ValueError("one line-size ratio is required per line")
    width, height = size
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    pattern = "|".join(re.escape(term) for term in sorted(set(accent_terms), key=len, reverse=True) if term)
    marked = [list(re.finditer(pattern, line)) if pattern else [] for line in lines]
    low, high = 1, max_font
    best = None
    while low <= high:
        base_size = (low + high) // 2
        fonts = [ImageFont.truetype(str(font_path), max(1, round(base_size * ratio))) for ratio in ratios]
        bounds = [
            probe.textbbox((0, 0), line, font=font, stroke_width=outline+weight)
            for line, font in zip(lines, fonts)
        ]
        # Discard oversized candidates before allocating wide intermediate masks.
        if any(right - left > width * 1.35 or bottom - top > height * 1.35 for left, top, right, bottom in bounds):
            high = base_size - 1
            continue
        images = [
            line_image(line, font, bound, fill, outline, slant, tilt, accents, accent_color, weight)
            for line, font, bound, fill, accents in zip(lines, fonts, bounds, fills, marked)
        ]
        visible_width = max(image.width for image in images)
        visible_height = sum(image.height for image in images) + gap * (len(lines) - 1)
        if visible_width <= width and visible_height <= height:
            best = list(zip(images, [font.size for font in fonts]))
            low = base_size + 1
        else:
            high = base_size - 1
    if best is None:
        raise ValueError("title or card does not fit; enlarge its box or rebreak the text")
    return best


def place_lines(art, lines, box, gap, align):
    text_layer = Image.new("RGBA", CANVAS)
    y = box[1]
    records = []
    for (image, font_size), line in zip(art, lines):
        x = box[0]
        if align == "right":
            x = box[2] - image.width
        elif align == "center":
            x = (box[0] + box[2] - image.width) // 2
        text_layer.alpha_composite(image, (x, y))
        records.append({"text": line, "fontSize": font_size, "bounds": [x, y, x + image.width, y + image.height]})
        y += image.height + gap
    return text_layer, records


def scene_with_contrast(scene, headline, records, shade, face_boxes):
    shade_mask = Image.new("L", CANVAS)
    pen = ImageDraw.Draw(shade_mask)
    for entry in records:
        left, top, right, bottom = entry["bounds"]
        pen.rounded_rectangle(
            (left - 45, top - 34, right + 42, bottom + 35), radius=34, fill=round(255 * shade)
        )
    shade_mask = shade_mask.filter(ImageFilter.GaussianBlur(38))
    shadow_mask = Image.new("L", CANVAS)
    shadow_mask.paste(headline.getchannel("A"), (5, 11))
    shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(8)).point(lambda value: round(value * 0.67))
    # Fade the lighting effects away from faces without altering source color.
    if face_boxes:
        protected = Image.new("L", CANVAS)
        pen = ImageDraw.Draw(protected)
        for box in face_boxes:
            pen.rounded_rectangle((box[0] - 18, box[1] - 18, box[2] + 18, box[3] + 18), radius=20, fill=255)
        protected = protected.filter(ImageFilter.GaussianBlur(12))
        no_effect = Image.new("L", CANVAS)
        shade_mask = Image.composite(no_effect, shade_mask, protected)
        shadow_mask = Image.composite(no_effect, shadow_mask, protected)
    black = Image.new("RGB", CANVAS)
    scene = Image.composite(black, scene, shade_mask)
    return Image.composite(black, scene, shadow_mask).convert("RGBA")


def card_tag(text, font_path, width, height, panel_color, text_color):
    pad_x, pad_y = TAG_PADDING
    art = fit_lines([text], font_path, [1.0], (width - 2 * pad_x, height - 2 * pad_y),
                    0, [text_color], max_font=70)
    sprite, _ = art[0]
    tag = Image.new("RGBA", (sprite.width + 2 * pad_x, sprite.height + 2 * pad_y))
    ImageDraw.Draw(tag).rounded_rectangle((0, 0, tag.width - 1, tag.height - 1), radius=12, fill=panel_color)
    tag.alpha_composite(sprite, (pad_x, pad_y))
    return tag


def evidence_card(args, font_path, title_bottom):
    lines = text_lines(args.card)
    left, top, right, bottom = args.card_box
    if top < title_bottom:
        raise ValueError("place the evidence card below the headline")
    pad_x, pad_y = CARD_PADDING
    width, height = right - left, bottom - top
    if args.card_tilt:
        sine = abs(math.sin(math.radians(args.card_tilt)))
        width, height = width - math.ceil(height * sine) - 2, height - math.ceil(width * sine) - 2

    label = (
        card_tag(args.card_label, font_path, width, min(118, height // 3), (21, 43, 75, 245), WHITE)
        if args.card_label else None
    )
    strip = (
        card_tag(args.card_strip, font_path, width - 2 * pad_x, min(100, height // 3), GOLD, INK)
        if args.card_strip else None
    )
    body_top = top + max(0, label.height - 12) if label else top
    strip_height = strip.height + 14 if strip else 0
    text_bottom = top + height - pad_y - strip_height
    inside = (left + pad_x, body_top + pad_y, left + width - pad_x, text_bottom)
    size = (inside[2] - inside[0], inside[3] - inside[1])
    light = args.card_style == "light"
    panel = (248, 246, 239, 242) if light else (17, 20, 24, 226)
    fill, accent = (INK, (28, 71, 139, 255)) if light else (WHITE, GOLD)
    art = fit_lines(
        lines, font_path, args.card_line_sizes or [1.0] * len(lines), size, 13,
        [fill] * len(lines), max_font=110, accent_terms=args.card_accent or (), accent_color=accent,
    )
    letters, records = place_lines(art, lines, inside, 13, "left")
    text_right = max(entry["bounds"][2] for entry in records)
    if strip:
        text_right = max(text_right, left + pad_x + strip.width)
    panel_right = max(text_right + pad_x, left + (label.width if label else 0))
    panel_bottom = records[-1]["bounds"][3] + pad_y + strip_height
    panel_layer = Image.new("RGBA", CANVAS)
    ImageDraw.Draw(panel_layer).rounded_rectangle((left, body_top, panel_right - 1, panel_bottom - 1),
                                                 radius=22, fill=panel)
    panel_layer.alpha_composite(letters)
    if label:
        panel_layer.alpha_composite(label, (left, top))
    if strip:
        panel_layer.alpha_composite(strip, (left + pad_x, records[-1]["bounds"][3] + 14))
    bounds = [left, top, panel_right, panel_bottom]
    if args.card_tilt:
        artwork = panel_layer.crop(bounds).rotate(args.card_tilt, expand=True, resample=Image.Resampling.BICUBIC)
        artwork = artwork.crop(artwork.getchannel("A").getbbox())
        if left + artwork.width > right or top + artwork.height > bottom:
            raise ValueError("tilted card exceeds its allotted box")
        panel_layer = Image.new("RGBA", CANVAS)
        panel_layer.alpha_composite(artwork, (left, top))
        bounds = [left, top, left + artwork.width, top + artwork.height]
    return panel_layer, dict(style=args.card_style, bounds=bounds, lines=records, tiltDegrees=args.card_tilt,
                             lineBoundsBeforeTilt=bool(args.card_tilt), label=args.card_label, strip=args.card_strip,
                             accentTerms=args.card_accent or [])


def foreground_alpha(path):
    with Image.open(path) as opened:
        layer = opened.convert("RGBA")
    if layer.size != CANVAS:
        raise ValueError("foreground must match the 1080×1440 canvas")
    alpha = layer.getchannel("A")
    lo, hi = alpha.getextrema()
    if lo == 255 or hi == 0:
        raise ValueError("foreground must contain both visible pixels and transparency")
    return layer, alpha


def alpha_sum(image):
    return sum(level * count for level, count in enumerate(image.histogram()))


def visible_headline(headline, records, foreground_mask):
    original = headline.getchannel("A")
    visible = ImageChops.multiply(original, ImageOps.invert(foreground_mask))
    for line in records:
        bounds = line["bounds"]
        before = alpha_sum(original.crop(bounds))
        after = alpha_sum(visible.crop(bounds))
        covered = 1 - after / before
        if covered > 0.25:
            raise ValueError(f"foreground obscures too much of the headline line {line['text']!r}; shift or resize it")
        line["foregroundOverlap"] = round(covered, 4)
    return visible


def render(args: argparse.Namespace) -> dict:
    weight = getattr(args, "headline_weight", 0)
    skin_file = getattr(args, "skin_mask", None)
    lift = getattr(args, "skin_lift", 0)
    if not 0 <= weight <= 12 or not 0 <= lift <= 0.25 or bool(skin_file) != bool(lift):
        raise ValueError("use a headline weight from 0 to 12 and pair the skin mask with a positive lift up to 0.25")
    lines = text_lines(args.title)
    accented = args.accent_line if args.accent_line is not None else [len(lines)]
    if accented != [0] and any(not 1 <= index <= len(lines) for index in accented):
        raise ValueError("--accent-line takes a one-based line number or 0 for all white")
    if not 0 <= args.shade <= 1 or args.line_gap < 0:
        raise ValueError("shade must be between 0 and 1 and line gap must be nonnegative")
    if not 0 <= args.slant <= 24 or not -12 <= args.tilt <= 12:
        raise ValueError("slant must be 0–24 degrees and tilt must be −12–12 degrees")
    if not -8 <= args.card_tilt <= 8:
        raise ValueError("card tilt must be −8–8 degrees")
    if not args.card and (args.card_label or args.card_strip or args.card_tilt):
        raise ValueError("pass --card to add a short label, conclusion strip, or tilt")
    face_boxes = args.face_box or []
    boxes = [args.text_box, *face_boxes]
    if args.card:
        boxes.append(args.card_box)
    if any(box[2] > CANVAS[0] or box[3] > CANVAS[1] for box in boxes):
        raise ValueError("layout box exceeds the 1080×1440 canvas")

    source_path, out = args.frame.resolve(), args.out.resolve()
    foreground_path = args.foreground.resolve() if args.foreground else None
    skin_path = skin_file.resolve() if skin_file else None
    if out in (source_path, foreground_path, skin_path) or out.suffix.lower() != ".png":
        raise ValueError("use a separate PNG output path")
    manifest_out = args.manifest_out.resolve() if args.manifest_out else None
    if manifest_out is not None and manifest_out in (source_path, foreground_path, skin_path, out):
        raise ValueError("use a separate manifest path")
    with Image.open(source_path) as image:
        source = ImageOps.exif_transpose(image).convert("RGB")
    crop = args.crop or (0, 0, source.width, source.height)
    scene = source_crop(source, crop)

    font = find_chinese_font(args.font)
    x0, y0, x1, y1 = args.text_box
    headline_box = (x0 + TITLE_MARGIN, y0 + TITLE_MARGIN, x1 - TITLE_MARGIN, y1 - TITLE_MARGIN)
    headline_size = (headline_box[2] - headline_box[0], headline_box[3] - headline_box[1])
    fills = [GOLD if index in accented else WHITE for index in range(1, len(lines) + 1)]
    art = fit_lines(
        lines, font, args.line_sizes or [1.0] * len(lines), headline_size, args.line_gap, fills,
        max_font=1080, outline=6, slant=args.slant, tilt=args.tilt, weight=weight,
    )
    headline, records = place_lines(art, lines, headline_box, args.line_gap, args.align)
    for index, entry in enumerate(records, start=1):
        entry["accent"] = index in accented

    panel, card_record = (None, None)
    if args.card:
        panel, card_record = evidence_card(args, font, records[-1]["bounds"][3])
    foreground = None
    visible = headline.getchannel("A")
    if foreground_path:
        foreground, mask = foreground_alpha(foreground_path)
        visible = visible_headline(headline, records, mask)
    panel_mask = panel.getchannel("A") if panel is not None else None
    for face in face_boxes:
        if visible.crop(face).getbbox() or (panel_mask is not None and panel_mask.crop(face).getbbox()):
            raise ValueError("headline or evidence card crosses a protected face; revise the layout boxes")

    if skin_file:
        with Image.open(skin_file) as opened:
            if opened.size != CANVAS or opened.mode != "L":
                raise ValueError("skin mask must be a canvas-aligned grayscale image")
            skin = opened.copy()
        lut = [min(255, round(v + 4 * lift * v * (1 - v / 255))) for v in range(256)]
        scene = Image.composite(scene.point(lut * 3), scene, skin)
        if foreground is not None:
            rgb = foreground.convert("RGB")
            graded = Image.composite(rgb.point(lut * 3), rgb, skin).convert("RGBA")
            graded.putalpha(mask)
            foreground = graded
    backing = scene_with_contrast(scene, headline, records, args.shade, face_boxes)
    backing.alpha_composite(headline)
    if foreground is not None:
        backing.alpha_composite(foreground)
    if panel is not None:
        backing.alpha_composite(panel)
    out.parent.mkdir(parents=True, exist_ok=True)
    backing.convert("RGB").save(out, format="PNG")
    manifest = {
        "schemaVersion": 1,
        "style": "scene-bold",
        "dimensions": list(CANVAS),
        "source": str(source_path),
        "sourceSha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "sourceDimensions": list(source.size),
        "sourceCropSelection": list(crop),
        "output": str(out),
        "outputSha256": hashlib.sha256(out.read_bytes()).hexdigest(),
        "textBox": list(args.text_box),
        "protectedFaces": face_boxes,
        "headlineWeight": weight,
        "skinLift": lift,
        "skinMaskSha256": hashlib.sha256(skin_file.read_bytes()).hexdigest() if skin_file else None,
        "foreground": ({"source": str(foreground_path), "sha256": hashlib.sha256(foreground_path.read_bytes()).hexdigest()}
                       if foreground_path else None),
        "shade": args.shade,
        "slantDegrees": args.slant,
        "tiltDegrees": args.tilt,
        "align": args.align,
        "lines": records,
        "card": card_record,
    }
    if manifest_out is not None:
        manifest_out.parent.mkdir(parents=True, exist_ok=True)
        manifest_out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame", required=True, type=Path, help="Original photograph or still frame")
    parser.add_argument("--crop", type=parse_box, help="Selection in oriented source pixels, center-cropped to 3:4 when needed")
    parser.add_argument("--title", required=True, help="Exact headline lines separated by |")
    parser.add_argument("--headline-weight", type=int, default=0, help="Additional same-colour headline stroke in pixels, 0 to 12")
    parser.add_argument("--skin-mask", type=Path, help="Canvas-aligned soft grayscale facial skin mask; exclude eyes and frames")
    parser.add_argument("--skin-lift", type=float, default=0, help="Facial midtone lift fraction, up to 0.25, with --skin-mask")
    parser.add_argument("--accent-line", type=int, action="append", help="One-based gold line, repeatable; last line by default; 0 for white only")
    parser.add_argument("--text-box", type=parse_box, default=(40, 46, 850, 740), help="Headline space on the 1080×1440 canvas")
    parser.add_argument("--line-sizes", type=parse_ratios, help="Relative font sizes for the headline, e.g. 1,1,1.18")
    parser.add_argument("--line-gap", type=int, default=7, help="Gap between headline glyph bounds")
    parser.add_argument("--align", choices=("left", "center", "right"), default="left")
    parser.add_argument("--slant", type=float, default=10, help="Rightward shear of headline glyphs, in degrees")
    parser.add_argument("--tilt", type=float, default=4, help="Counterclockwise rotation of each headline line, in degrees")
    parser.add_argument("--shade", type=float, default=0.18, help="Local contrast under the headline, from 0 to 1")
    parser.add_argument("--card", help="Lower conclusion and evidence lines separated by |")
    parser.add_argument("--card-box", type=parse_box, default=(48, 1040, 1032, 1384), help="Available space for the lower card")
    parser.add_argument("--card-style", choices=("dark", "light"), default="dark")
    parser.add_argument("--card-label", help="Short white title on a dark-blue label overlapping the card")
    parser.add_argument("--card-strip", help="Short conclusion in a gold strip within the card")
    parser.add_argument("--card-tilt", type=float, default=0, help="Tilt the entire card counterclockwise")
    parser.add_argument("--card-accent", action="append", help="Highlight a literal term or number in the card; repeatable")
    parser.add_argument("--card-line-sizes", type=parse_ratios, help="Relative font sizes for the card lines")
    parser.add_argument("--foreground", type=Path, help="Canvas-sized transparent subject cover layer, aligned to the cropped scene")
    parser.add_argument("--face-box", action="append", type=parse_box, help="Keep this face area free of graphic overlays; repeatable")
    parser.add_argument("--font", type=Path, help="Local heavy sans-serif font")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path, help="Optional private QA manifest")
    manifest = render(parser.parse_args())
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()

