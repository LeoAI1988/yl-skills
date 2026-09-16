#!/usr/bin/env python3
"""Render a 3:4 source-frame cover with a translucent black veil and white serif title."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from font_utils import find_chinese_font
import shutil
import subprocess
import tempfile
import unicodedata

from PIL import Image, ImageDraw, ImageFont, ImageOps


CANVAS = (1080, 1440)
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}


def unit_float(value: str) -> float:
    number = float(value)
    if not 0 <= number <= 1:
        raise argparse.ArgumentTypeError("value must be between 0 and 1")
    return number


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--source-time", type=float, default=0.0)
    parser.add_argument("--title", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--manifest-out", type=Path)
    parser.add_argument("--opacity", type=unit_float, default=0.54)
    parser.add_argument("--crop-x", type=unit_float, default=0.5)
    parser.add_argument("--crop-y", type=unit_float, default=0.5)
    parser.add_argument("--zoom", type=float, default=1.0)
    parser.add_argument("--title-y", type=unit_float, default=0.5)
    parser.add_argument("--font", type=Path)
    parser.add_argument("--font-size", type=int)
    parser.add_argument("--line-gap", type=int)
    parser.add_argument("--allow-long-title", action="store_true")
    return parser.parse_args()


def visible_character_count(text: str) -> int:
    return sum(1 for character in text if unicodedata.category(character)[0] in {"L", "N"})


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_video_frame(source: Path, source_time: float, output: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FileNotFoundError("Required executable is not on PATH: ffmpeg")
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{source_time:.3f}",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-q:v",
            "1",
            str(output),
        ],
        check=True,
    )


def load_source(source: Path, source_time: float) -> Image.Image:
    if source.suffix.lower() not in VIDEO_EXTENSIONS:
        return ImageOps.exif_transpose(Image.open(source)).convert("RGB")
    with tempfile.TemporaryDirectory(prefix="translucent-cover-") as temp_dir:
        frame = Path(temp_dir) / "frame.png"
        extract_video_frame(source, source_time, frame)
        return Image.open(frame).convert("RGB").copy()


def cover_crop(
    image: Image.Image, crop_x: float, crop_y: float, zoom: float
) -> tuple[Image.Image, dict[str, object]]:
    width, height = image.size
    if not 1 <= zoom <= 1.25:
        raise ValueError("zoom must stay between 1 and 1.25")
    scale = max(CANVAS[0] / width, CANVAS[1] / height) * zoom
    resized_size = (round(width * scale), round(height * scale))
    resized = image.resize(resized_size, Image.Resampling.LANCZOS)
    overflow_x = max(0, resized.width - CANVAS[0])
    overflow_y = max(0, resized.height - CANVAS[1])
    left = round(overflow_x * crop_x)
    top = round(overflow_y * crop_y)
    cropped = resized.crop((left, top, left + CANVAS[0], top + CANVAS[1]))
    return cropped, {
        "sourceSize": [width, height],
        "resizedSize": list(resized_size),
        "cropBox": [left, top, left + CANVAS[0], top + CANVAS[1]],
        "cropX": crop_x,
        "cropY": crop_y,
        "zoom": zoom,
    }


def choose_font(explicit: Path | None) -> Path:
    return find_chinese_font(explicit, serif=True)


def text_metrics(
    lines: list[str], font_path: Path, size: int, line_gap: int | None
) -> tuple[ImageFont.FreeTypeFont, list[tuple[int, int, int, int]], int, int, int]:
    font = ImageFont.truetype(str(font_path), size=size)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    boxes = [probe.textbbox((0, 0), line, font=font, stroke_width=1) for line in lines]
    widths = [box[2] - box[0] for box in boxes]
    heights = [box[3] - box[1] for box in boxes]
    gap = line_gap if line_gap is not None else max(20, round(size * 0.22))
    block_height = sum(heights) + gap * (len(lines) - 1)
    return font, boxes, max(widths), block_height, gap


def fit_font(
    lines: list[str], font_path: Path, requested: int | None, line_gap: int | None
) -> tuple[ImageFont.FreeTypeFont, list[tuple[int, int, int, int]], int, int]:
    if requested is not None and not 72 <= requested <= 360:
        raise ValueError("font size must stay between 72 and 360")
    sizes = [requested] if requested is not None else range(260, 71, -2)
    for size in sizes:
        font, boxes, width, block_height, gap = text_metrics(lines, font_path, size, line_gap)
        if width <= 920 and block_height <= 680:
            return font, boxes, block_height, gap
    raise ValueError("Title cannot fit the safe area; shorten or rebreak it")


def main() -> None:
    args = parse_args()
    source = args.source.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Source does not exist: {source}")
    if not 0 <= args.source_time:
        raise ValueError("source time must be non-negative")
    if not 0.42 <= args.opacity <= 0.68:
        raise ValueError("opacity must stay between 0.42 and 0.68 for this style")

    lines = [line.strip() for line in args.title.split("|") if line.strip()]
    if not 2 <= len(lines) <= 3:
        raise ValueError("Title must contain 2 or 3 non-empty lines separated by |")
    visible_count = visible_character_count("".join(lines))
    longest_line = max(visible_character_count(line) for line in lines)
    if not args.allow_long_title and not 3 <= visible_count <= 12:
        raise ValueError(
            "This minimalist style requires 3-12 visible characters; shorten the title "
            "or pass --allow-long-title only for explicit user wording"
        )
    if not args.allow_long_title and longest_line > 7:
        raise ValueError(
            "Each line must stay at 7 visible characters or fewer for this minimalist style"
        )

    image, crop = cover_crop(
        load_source(source, args.source_time), args.crop_x, args.crop_y, args.zoom
    )
    base = image.convert("RGBA")
    veil = Image.new("RGBA", CANVAS, (0, 0, 0, round(args.opacity * 255)))
    composited = Image.alpha_composite(base, veil)
    draw = ImageDraw.Draw(composited)

    font_path = choose_font(args.font)
    font, boxes, block_height, gap = fit_font(lines, font_path, args.font_size, args.line_gap)
    block_top = round(args.title_y * CANVAS[1] - block_height / 2)
    block_top = min(max(80, block_top), CANVAS[1] - 80 - block_height)

    visible_boxes: list[list[int]] = []
    cursor_y = block_top
    for line, box in zip(lines, boxes):
        text_width = box[2] - box[0]
        text_height = box[3] - box[1]
        visible_left = round((CANVAS[0] - text_width) / 2)
        draw_x = visible_left - box[0]
        draw_y = cursor_y - box[1]
        draw.text(
            (draw_x, draw_y),
            line,
            font=font,
            fill=(247, 247, 245, 255),
            stroke_width=1,
            stroke_fill=(18, 18, 18, 220),
        )
        visible_boxes.append([visible_left, cursor_y, visible_left + text_width, cursor_y + text_height])
        cursor_y += text_height + gap

    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    composited.convert("RGB").save(out, format="PNG", optimize=True)

    manifest = {
        "schemaVersion": 1,
        "style": "translucent-black-white",
        "source": str(source),
        "sourceSha256": file_hash(source),
        "sourceTimeSeconds": args.source_time if source.suffix.lower() in VIDEO_EXTENSIONS else None,
        "output": str(out),
        "outputSha256": file_hash(out),
        "dimensions": list(CANVAS),
        "title": "".join(lines),
        "lines": lines,
        "visibleCharacterCount": visible_count,
        "allowLongTitle": args.allow_long_title,
        "opacity": args.opacity,
        "font": str(font_path),
        "fontSize": font.size,
        "lineGap": gap,
        "titleY": args.title_y,
        "textBoxes": visible_boxes,
        "crop": crop,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
    if args.manifest_out:
        manifest_out = args.manifest_out.resolve()
        manifest_out.parent.mkdir(parents=True, exist_ok=True)
        manifest_out.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
