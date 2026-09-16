#!/usr/bin/env python3
"""Enlarge the upper part of a low-resolution screenshot for title verification."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--top-ratio", type=float, default=0.35)
    parser.add_argument("--scale", type=int, default=4)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 0.15 <= args.top_ratio <= 0.65:
        raise ValueError("--top-ratio must be between 0.15 and 0.65")
    if not 2 <= args.scale <= 8:
        raise ValueError("--scale must be between 2 and 8")
    image = Image.open(args.input).convert("RGB")
    crop_height = max(1, round(image.height * args.top_ratio))
    crop = image.crop((0, 0, image.width, crop_height))
    crop = crop.resize(
        (crop.width * args.scale, crop.height * args.scale),
        Image.Resampling.LANCZOS,
    )
    crop = crop.filter(ImageFilter.UnsharpMask(radius=1.2, percent=145, threshold=3))
    crop = ImageEnhance.Contrast(crop).enhance(1.08)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    crop.save(args.out, format="PNG", optimize=True)
    print(f"TITLE_CROP=PASS source={image.width}x{image.height} output={crop.width}x{crop.height}")


if __name__ == "__main__":
    main()

