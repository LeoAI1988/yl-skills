#!/usr/bin/env python3
"""Validate dimensions, title provenance metadata, and thumbnail readability inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import unicodedata

from PIL import Image


def visible_character_count(text: str) -> int:
    return sum(1 for character in text if unicodedata.category(character)[0] in {"L", "N"})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--expected-title", required=True)
    parser.add_argument("--thumbnail", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    errors: list[str] = []
    if not args.image.is_file():
        raise FileNotFoundError(f"Image does not exist: {args.image}")
    if not args.manifest.is_file():
        raise FileNotFoundError(f"Manifest does not exist: {args.manifest}")

    with Image.open(args.image) as image:
        if image.size != (1080, 1440):
            errors.append(f"dimensions must be 1080x1440, got {image.size}")
        if image.format != "PNG":
            errors.append(f"format must be PNG, got {image.format}")
        if args.thumbnail:
            thumbnail = image.convert("RGB").resize((270, 360), Image.Resampling.LANCZOS)
            args.thumbnail.parent.mkdir(parents=True, exist_ok=True)
            thumbnail.save(args.thumbnail, format="PNG", optimize=True)

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("outputSha256") != hashlib.sha256(args.image.read_bytes()).hexdigest():
        errors.append("image hash does not match manifest")
    if manifest.get("style") != "translucent-black-white":
        errors.append("manifest style is not translucent-black-white")
    if manifest.get("dimensions") != [1080, 1440]:
        errors.append("manifest dimensions are not 1080x1440")
    if manifest.get("title") != args.expected_title:
        errors.append(
            f"title mismatch: expected {args.expected_title!r}, got {manifest.get('title')!r}"
        )
    lines = manifest.get("lines", [])
    if not 2 <= len(lines) <= 3:
        errors.append("title must contain 2 or 3 lines")
    visible_count = visible_character_count("".join(lines))
    if manifest.get("visibleCharacterCount") != visible_count:
        errors.append("manifest visible character count is incorrect")
    if not manifest.get("allowLongTitle", False):
        if not 3 <= visible_count <= 12:
            errors.append("minimalist title must contain 3-12 visible characters")
        for line in lines:
            if visible_character_count(line) > 7:
                errors.append(f"minimalist title line is too long: {line!r}")
    opacity = manifest.get("opacity")
    if not isinstance(opacity, (int, float)) or not 0.42 <= opacity <= 0.68:
        errors.append("overlay opacity must stay between 0.42 and 0.68")
    for box in manifest.get("textBoxes", []):
        if len(box) != 4 or box[0] < 70 or box[2] > 1010 or box[1] < 80 or box[3] > 1360:
            errors.append(f"text box leaves the safe area: {box}")

    if errors:
        raise SystemExit("COVER VALIDATION FAILED\n- " + "\n- ".join(errors))
    print("COVER VALIDATION PASSED")


if __name__ == "__main__":
    main()
