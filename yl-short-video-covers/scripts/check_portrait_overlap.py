#!/usr/bin/env python3
"""Pixel-level portrait-overlap check for a rendered cover.

Reads the JSON manifest written by render_bold_cover.py, rebuilds the
per-line glyph masks and the portrait mask from the recorded geometry, and
reports the percentage of each headline line's glyph pixels covered by the
portrait. Use when visual image inspection is unavailable, or to hard-verify
the 25% target. Per-character boundaries are estimates for rotated/boxed
type; inspect the real image before accepting a 50% hard-max requirement.

Usage:
    python -X utf8 scripts/check_portrait_overlap.py --manifest "path/to/cover.json"
    python -X utf8 scripts/check_portrait_overlap.py --image "path/to/cover.png"
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

from PIL import Image, ImageFilter, ImageFont, ImageOps

SKILL_DIR = Path(__file__).resolve().parent.parent


def load_render_module():
    spec = importlib.util.spec_from_file_location(
        "rc", SKILL_DIR / "scripts" / "render_bold_cover.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest", type=Path, help="Path to the cover JSON manifest")
    source.add_argument("--image", type=Path, help="Path to the cover PNG (manifest must sit beside it)")
    parser.add_argument("--warn", type=float, default=25.0, help="Warn threshold in percent (default 25)")
    parser.add_argument(
        "--per-char",
        action="store_true",
        help="Also split each line by character and report the worst single-character coverage",
    )
    return parser.parse_args()


def char_coverage(line_text, font, glyph_px, portrait_px, width, height, pad, x0):
    """Coverage per character, splitting the line mask by cumulative glyph advances."""
    results = []
    cursor = x0 + pad
    for char in line_text:
        char_w = max(1, int(round(font.getlength(char))))
        total = hit = 0
        for yy in range(height):
            for xx in range(cursor, min(cursor + char_w, width)):
                if glyph_px[xx, yy]:
                    total += 1
                    if portrait_px[xx, yy]:
                        hit += 1
        if total:
            results.append((char, 100.0 * hit / total))
        cursor += char_w
    return results


def main() -> int:
    args = parse_args()
    manifest_path = args.manifest or args.image.with_suffix(".json")
    if not manifest_path.exists():
        print(f"CHECK=PORTRAIT_OVERLAP ERROR manifest not found: {manifest_path}")
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest.get("avatar"):
        print("CHECK=PORTRAIT_OVERLAP PASS no portrait used")
        return 0

    width = int(manifest.get("width", 1080))
    height = int(manifest.get("height", 1440))
    boxed = set(manifest.get("boxedTerms", []))
    yellow = set(manifest.get("yellowTerms", []))
    placement = manifest["avatarPlacement"]
    avatar_path = Path(manifest["avatar"])
    font_path = Path(manifest["font"])

    rc = load_render_module()

    # Per-line glyph masks (opaque glyph pixels only: alpha > 200).
    glyph_masks = []
    for style in manifest["lineStyles"]:
        font = ImageFont.truetype(str(font_path), size=int(style["fontSize"]))
        line_image = rc.render_line_image(
            style["text"], font, boxed, yellow, float(style["angle"])
        )
        if manifest.get("lineAlignment") == "left":
            visible_bbox = line_image.getchannel("A").getbbox()
            if visible_bbox:
                line_image = line_image.crop(visible_bbox)
        mask = line_image.getchannel("A").point(lambda v: 255 if v > 200 else 0)
        canvas = Image.new("1", (width, height), 0)
        canvas.paste(mask, (int(style["x"]), int(style["y"])))
        glyph_masks.append((style, font, canvas))

    # Portrait mask, replicating avatar_layer() placement math.
    source = Image.open(avatar_path).convert("RGBA")
    alpha = source.getchannel("A")
    if alpha.getextrema()[0] < 250:
        bbox = alpha.getbbox()
        if bbox:
            source = source.crop(bbox)
    target_h = int(height * float(placement["scale"]))
    target_w = round(source.width * target_h / source.height)
    source = source.resize((target_w, target_h), Image.Resampling.LANCZOS)
    alpha = source.getchannel("A")
    if alpha.getextrema()[0] < 250:
        portrait_mask = alpha.filter(ImageFilter.GaussianBlur(radius=0.6))
    else:
        gray = ImageOps.grayscale(source.convert("RGB"))
        portrait_mask = gray.point(
            lambda v: max(0, min(255, round((v - 2) * 22)))
        )
        portrait_mask = portrait_mask.filter(ImageFilter.MaxFilter(size=9)).filter(
            ImageFilter.GaussianBlur(radius=1.0)
        )
    pos_x = width - target_w + int(width * float(placement["xShift"]))
    pos_y = height - target_h + int(height * float(placement["yShift"]))
    portrait = Image.new("1", (width, height), 0)
    portrait.paste(portrait_mask.point(lambda v: 255 if v > 128 else 0), (pos_x, pos_y))

    # Head-clip check: a clipped NARROW band in the top half of the person means
    # the head is cut (shoulders are wide and their overflow is the intended
    # corner anchoring). Narrow = band width below 60% of the widest band.
    head_fail = False
    head_overflow = 0
    frame_mask = portrait_mask.point(lambda v: 255 if v > 128 else 0)
    fb = frame_mask.getbbox()
    if fb:
        ph = fb[3] - fb[1]
        bands = []
        for i in range(10):
            y0 = fb[1] + int(ph * i / 10)
            y1 = fb[1] + int(ph * (i + 1) / 10)
            band = frame_mask.crop((0, y0, target_w, y1)).getbbox()
            if band:
                bands.append((i, band))
        if bands:
            max_band_w = max(b[2] - b[0] for _, b in bands)
            for i, band in bands:
                if i >= 5:
                    continue
                if (band[2] - band[0]) < 0.6 * max_band_w:
                    head_overflow = max(
                        head_overflow,
                        (pos_x + band[2]) - width,
                        -(pos_x + band[0]),
                    )
                if pos_y + fb[1] < 0:
                    head_overflow = max(head_overflow, -(pos_y + fb[1]))
        head_fail = head_overflow > 8
        note = "FAIL" if head_fail else ("minor" if head_overflow > 0 else "ok")
        print(f"head-clip: overflow={max(0, head_overflow)}px  {note}")
    else:
        print("head-clip: skipped (empty portrait mask)")

    print(f"portrait: {target_w}x{target_h} placed at ({pos_x},{pos_y})")
    worst = 0.0
    worst_char_pct = 0.0
    worst_char_label = "-"
    for style, font, glyphs in glyph_masks:
        glyph_px = glyphs.load()
        portrait_px = portrait.load()
        total = hit = 0
        for yy in range(0, height, 2):
            for xx in range(0, width, 2):
                if glyph_px[xx, yy]:
                    total += 1
                    if portrait_px[xx, yy]:
                        hit += 1
        pct = 100.0 * hit / total if total else 0.0
        worst = max(worst, pct)
        status = "OK" if pct <= args.warn else "WARN"
        print(f"{style['text']:<12} glyph_px={total * 4:>7} covered={pct:5.1f}%  {status}")
        if args.per_char:
            pad = max(28, int(style["fontSize"]) // 5)
            chars = char_coverage(
                style["text"], font, glyph_px, portrait_px, width, height, pad, int(style["x"])
            )
            line_chars = ", ".join(f"{c}={v:.0f}%" for c, v in chars)
            print(f"    chars: {line_chars}")
            for c, v in chars:
                if v > worst_char_pct:
                    worst_char_pct, worst_char_label = v, c

    char_fail = args.per_char and worst_char_pct >= 50
    verdict = "PASS" if worst <= args.warn and not head_fail and not char_fail else "FAIL"
    reasons = []
    if worst > args.warn:
        reasons.append(f"line-overlap {worst:.1f}%>{args.warn:.0f}%")
    if head_fail:
        reasons.append(f"head clipped {head_overflow}px")
    if char_fail:
        reasons.append(f"estimated character overlap {worst_char_pct:.1f}% >= 50%")
    detail = (" (" + "; ".join(reasons) + ")") if reasons else ""
    print(f"CHECK=PORTRAIT_OVERLAP {verdict}{detail} worst_line={worst:.1f}% warn={args.warn:.0f}%")
    if args.per_char:
        print(f"worst single character: {worst_char_label} {worst_char_pct:.1f}%")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
