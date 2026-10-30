#!/usr/bin/env python3
"""Validate a rendered cover and its manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import math
from tech_background import texture_pixels, prepared_background, STYLE_VERSION, BACKGROUND_ID, BACKGROUND_SHA256
from pathlib import Path

from PIL import Image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--manifest", type=Path, help="Private manifest path; defaults beside image")
    parser.add_argument("--expected-title")
    parser.add_argument("--expected-primary-title")
    parser.add_argument("--expected-supplement")
    parser.add_argument("--source-mode", choices=("screenshot", "script", "video"))
    parser.add_argument(
        "--check-line-overlap",
        action="store_true",
        help="Reject headline lines whose visible glyph areas overlap too heavily.",
    )
    parser.add_argument(
        "--allow-sparse-headline",
        action="store_true",
        help="Deprecated compatibility flag; concise headlines are accepted by default.",
    )
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1440)
    args = parser.parse_args()
    if not args.expected_title and not args.expected_primary_title:
        parser.error("pass --expected-title or --expected-primary-title")
    return args


def visible_content_units(text: str) -> int:
    """Count visible letters, numbers, and CJK characters for density checks."""
    return len(re.findall(r"[\w\u3400-\u9fff]", text, flags=re.UNICODE))


def main() -> None:
    args = parse_args()
    errors: list[str] = []
    if not args.image.exists():
        errors.append(f"missing image: {args.image}")
    manifest_path = args.manifest or args.image.with_suffix(".json")
    if not manifest_path.exists():
        errors.append(f"missing manifest: {manifest_path}")

    if errors:
        print("VALIDATE_COVER=FAIL")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    lines = manifest.get("lines", [])
    if not 1 <= len(lines) <= 4 or any(not isinstance(line, str) or not line.strip() for line in lines):
        errors.append("headline must contain 1-4 non-empty lines including supplement; prefer three semantic lines")
    with Image.open(args.image) as image:
        if image.size != (args.width, args.height):
            errors.append(f"dimensions {image.size} != {(args.width, args.height)}")
        if image.format != "PNG":
            errors.append(f"format {image.format} != PNG")
        preview = image.convert("RGB").resize((270, 360))
        colors = preview.getcolors(maxcolors=270 * 360)
        if colors is not None and len(colors) < 16:
            errors.append("image appears visually sparse or corrupted")
        yellow_pixels = sum(
            1 for red, green, blue in preview.getdata() if red > 200 and 120 < green < 235 and blue < 80
        )
        white_pixels = sum(1 for red, green, blue in preview.getdata() if red > 220 and green > 220 and blue > 215)
        if manifest.get("accent") == "yellow" and yellow_pixels < 350:
            errors.append(f"insufficient yellow accent pixels: {yellow_pixels}")
        if white_pixels < 350:
            errors.append(f"insufficient white headline pixels: {white_pixels}")

    if manifest.get("style") != "outlined-tech":
        errors.append("missing outlined technology style; legacy solid-black output is not accepted")
    if manifest.get("styleVersion") != STYLE_VERSION or manifest.get("background") != BACKGROUND_ID:
        errors.append("approved mature circuit template identity is required")
    if manifest.get("backgroundSha256") != BACKGROUND_SHA256:
        errors.append("background master hash does not match the approved template")
    if manifest.get("outline") != {"align": "outside", "width": 9}:
        errors.append("9px outward black outline is required")
    if manifest.get("boxedTerms"):
        errors.append("yellow rectangles are not part of this style")
    if manifest.get("lineAlignment") != "left":
        errors.append("all lines must share the left edge")
    if len(manifest.get("yellowTerms", [])) > 3:
        errors.append("at most three yellow keywords are allowed")
    title = manifest.get("title", "")
    if "".join(lines) != title:
        errors.append("line text does not reconstruct exact headline")
    marked = set()
    for term in manifest.get("yellowTerms", []):
        if not term:
            errors.append("empty yellow keyword")
            continue
        offset = 0
        while (at := title.find(term, offset)) >= 0:
            marked.update(i for i in range(at, at+len(term)) if title[i].isalnum())
            offset = at + len(term)
    if len(marked) > math.ceil(sum(c.isalnum() for c in title)/3):
        errors.append("yellow emphasis exceeds one third of headline, rounded up")
    with Image.open(args.image) as rendered:
        # Exclude measured visible text and portrait bounds, rather than reserving
        # a fixed corridor that can legitimately contain large lower-left words.
        from PIL import ImageDraw, ImageChops
        expected = prepared_background(args.width, args.height).convert("RGB")
        sample = Image.new("L", expected.size, 255)
        draw = ImageDraw.Draw(sample)
        boxes = [style.get("actualBounds") for style in manifest.get("lineStyles", [])]
        portrait = manifest.get("avatarPlacement", {}).get("visibleBounds")
        if manifest.get("avatar") and not portrait:
            errors.append("portrait visible bounds missing")
        if portrait: boxes.append(portrait)
        for box in boxes:
            if (not isinstance(box, list) or len(box) != 4
                    or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in box)):
                errors.append("measured visible bounds missing or invalid")
                continue
            x0,y0,x1,y1 = box
            if not (0 <= x0 < x1 <= args.width and 0 <= y0 < y1 <= args.height):
                errors.append("visible bounds exceed canvas")
                continue
            draw.rectangle((max(0,x0-3),max(0,y0-3),min(args.width-1,x1+3),min(args.height-1,y1+3)), fill=0)
        samples = sample.histogram()[255]
        if samples < args.width * args.height * .12:
            errors.append("insufficient exposed background for verification")
        diff = ImageChops.difference(rendered.convert("RGB"), expected)
        channels = diff.split()
        worst = ImageChops.lighter(ImageChops.lighter(channels[0],channels[1]),channels[2])
        bad = ImageChops.multiply(worst.point(lambda v: 255 if v > 2 else 0),sample).histogram()[255]
        if samples and bad / samples > .02:
            errors.append("exposed background pixels differ from the approved master")
    if any(abs(x.get("angle", 0)) > 0.001 for x in manifest.get("lineStyles", [])):
        errors.append("rotated text is not part of technology cover style")

    if args.expected_title:
        expected = args.expected_title.replace("|", "").replace("\n", "").strip()
        if manifest.get("title") != expected:
            errors.append(f"title {manifest.get('title')!r} != {expected!r}")
    if args.expected_primary_title:
        expected_primary = args.expected_primary_title.replace("|", "").replace("\n", "").strip()
        actual_primary = manifest.get("primaryTitle", manifest.get("title"))
        if actual_primary != expected_primary:
            errors.append(f"primary title {actual_primary!r} != {expected_primary!r}")
    if args.expected_supplement is not None:
        expected_supplement = args.expected_supplement.replace("|", "").replace("\n", "").strip()
        if manifest.get("supplement", "") != expected_supplement:
            errors.append(
                f"supplement {manifest.get('supplement', '')!r} != {expected_supplement!r}"
            )

    line_styles = manifest.get("lineStyles")
    if line_styles:
        if len(line_styles) != len(manifest.get("lines", [])):
            errors.append("line style count does not match line count")
        font_sizes = [style.get("fontSize", 0) for style in line_styles]
        angles = [abs(style.get("angle", 0)) for style in line_styles]
        title_bottom = max(
            style.get("y", 0) + round(style.get("fontSize", 0) * 1.12)
            for style in line_styles
        )
        bounds = [style.get("actualBounds") for style in line_styles]
        if len({b[0] for b in bounds if isinstance(b,list) and len(b)==4}) > 1:
            errors.append("visible headline lines do not share left edge")
        for style in line_styles:
            if style.get("portraitOverlapRatio", 0) >= .5:
                errors.append("portrait obscures headline")
        if args.check_line_overlap:
            for a,b in zip(bounds,bounds[1:]):
                if isinstance(a,list) and isinstance(b,list) and len(a)==len(b)==4 and a[3] > b[1]:
                    errors.append("visible headline line bounds overlap")
    digest = hashlib.sha256(args.image.read_bytes()).hexdigest()
    if manifest.get("sha256") != digest:
        errors.append("image hash does not match manifest")
    if args.image.stat().st_size < 10_000:
        errors.append(f"image file too small: {args.image.stat().st_size} bytes")

    if errors:
        print("VALIDATE_COVER=FAIL")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)

    print(
        f"VALIDATE_COVER=PASS title={manifest['title']} "
        f"size={args.width}x{args.height} bytes={args.image.stat().st_size}"
    )


if __name__ == "__main__":
    main()
