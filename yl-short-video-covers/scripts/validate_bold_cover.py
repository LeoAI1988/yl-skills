#!/usr/bin/env python3
"""Validate a rendered cover and its manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
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
        help="Allow a short script/video headline only when the user explicitly requests it.",
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

    if args.source_mode in {"script", "video"} and not args.allow_sparse_headline:
        primary = manifest.get("primaryTitle", manifest.get("title", ""))
        supplement = manifest.get("supplement", "")
        primary_units = visible_content_units(primary)
        total_units = primary_units + visible_content_units(supplement)
        line_count = len(manifest.get("lines", []))
        if primary_units <= 12 and not supplement.strip():
            errors.append(
                "short script/video primary title requires a source-grounded supplement"
            )
        if total_units < 16:
            errors.append(
                f"combined script/video headline is underfilled: content_units={total_units}"
            )
        if primary_units <= 12 and line_count < 4:
            errors.append(
                f"short script/video headline needs at least four meaningful lines: lines={line_count}"
            )

    line_styles = manifest.get("lineStyles")
    if line_styles:
        if len(line_styles) != len(manifest.get("lines", [])):
            errors.append("line style count does not match line count")
        font_sizes = [style.get("fontSize", 0) for style in line_styles]
        angles = [abs(style.get("angle", 0)) for style in line_styles]
        if len(font_sizes) >= 3 and max(font_sizes) - min(font_sizes) < 12:
            errors.append("headline lacks deliberate font-size variation")
        if angles and max(angles) < 0.5 and manifest.get("lineAlignment") != "left":
            errors.append("headline lacks deliberate line-angle variation")
        title_bottom = max(
            style.get("y", 0) + round(style.get("fontSize", 0) * 1.12)
            for style in line_styles
        )
        if title_bottom < round(args.height * 0.55):
            errors.append(f"headline footprint is too shallow: bottom={title_bottom}")
        if args.check_line_overlap:
            for current, following in zip(line_styles, line_styles[1:]):
                current_size = current.get("fontSize", 0)
                following_size = following.get("fontSize", 0)
                current_glyph_bottom = current.get("y", 0) + round(current_size * 1.22)
                following_glyph_top = following.get("y", 0) + round(following_size * 0.20)
                overlap = current_glyph_bottom - following_glyph_top
                allowed = round(min(current_size, following_size) * 0.08)
                if overlap > allowed:
                    errors.append(
                        "headline lines overlap too heavily: "
                        f"{current.get('text')!r} -> {following.get('text')!r}, pixels={overlap}"
                    )
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
