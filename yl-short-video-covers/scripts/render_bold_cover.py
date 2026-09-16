#!/usr/bin/env python3
"""Render exact title text on a dark cover, with optional yellow accents and portrait."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from font_utils import find_chinese_font

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps


YELLOW = (255, 196, 0)
WHITE = (247, 247, 245)
BLACK = (5, 7, 10)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True, help="Exact title; use | for deliberate line breaks")
    parser.add_argument(
        "--supplement",
        default="",
        help="Optional source-grounded supporting hook; use | for deliberate line breaks",
    )
    parser.add_argument("--boxed-terms", default="", help="Comma-separated terms drawn black on yellow")
    parser.add_argument("--yellow-terms", default="", help="Comma-separated terms drawn in yellow")
    parser.add_argument(
        "--line-angles",
        default="",
        help="Optional comma-separated per-line rotation angles in degrees",
    )
    parser.add_argument(
        "--line-widths",
        default="",
        help="Optional comma-separated target width ratios, one per line (0.35-1.0)",
    )
    parser.add_argument(
        "--line-gap",
        type=int,
        default=40,
        help="Extra vertical gap in pixels between headline lines (0-120)",
    )
    parser.add_argument(
        "--left-align",
        action="store_true",
        help="Align every headline line to one visible left edge and disable line rotation",
    )
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--manifest-out", type=Path, help="Private manifest path; defaults beside output")
    parser.add_argument("--accent", choices=("none", "yellow"), default="none")
    parser.add_argument("--background", type=Path, help="Optional user-supplied licensed background")
    parser.add_argument("--avatar", type=Path, help="Optional user-supplied transparent portrait")
    parser.add_argument(
        "--portrait-label",
        default="",
        help="Human-readable portrait subject recorded in the manifest",
    )
    parser.add_argument(
        "--avatar-scale",
        type=float,
        help="Optional portrait height as a canvas ratio; defaults from headline density",
    )
    parser.add_argument(
        "--avatar-x-shift",
        type=float,
        help="Optional right-edge portrait shift as a canvas-width ratio",
    )
    parser.add_argument(
        "--avatar-y-shift",
        type=float,
        help="Optional bottom-edge portrait shift as a canvas-height ratio",
    )
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1440)
    parser.add_argument("--font", type=Path)
    return parser.parse_args()


def find_font(explicit: Path | None) -> Path:
    return find_chinese_font(explicit, serif=False)


def cover_resize(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(image.convert("RGB"), size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))


def avatar_layer(
    avatar_path: Path,
    canvas_size: tuple[int, int],
    scale: float,
    x_shift: float,
    y_shift: float,
) -> Image.Image:
    width, height = canvas_size
    source = Image.open(avatar_path).convert("RGBA")
    # Transparent portraits are often exported on a wide canvas. Crop those
    # empty margins before sizing so the visible person—not the source canvas—
    # controls scale and placement.
    source_alpha = source.getchannel("A")
    if source_alpha.getextrema()[0] < 250:
        visible_bbox = source_alpha.getbbox()
        if visible_bbox:
            source = source.crop(visible_bbox)
    target_h = int(height * scale)
    target_w = round(source.width * target_h / source.height)
    source = source.resize((target_w, target_h), Image.Resampling.LANCZOS)
    avatar = source.convert("RGB")

    layer = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    x = width - target_w + int(width * x_shift)
    y = height - target_h + int(height * y_shift)

    source_alpha = source.getchannel("A")
    if source_alpha.getextrema()[0] < 250:
        mask = source_alpha.filter(ImageFilter.GaussianBlur(radius=0.6))
    else:
        # Opaque legacy portraits sit on a matte-black backdrop. Keep only actual
        # non-black subject pixels; do not restore the person with broad polygon
        # masks, because those create a visible black halo around hair/shoulders.
        mask = ImageOps.grayscale(avatar).point(
            lambda value: max(0, min(255, round((value - 2) * 22)))
        )
        mask = mask.filter(ImageFilter.MaxFilter(size=9)).filter(
            ImageFilter.GaussianBlur(radius=1.0)
        )
    layer.paste(avatar.convert("RGBA"), (x, y), mask)
    return layer


def split_terms(line: str, terms: list[str]) -> list[tuple[str, str | None]]:
    terms = sorted((term for term in terms if term), key=len, reverse=True)
    chunks: list[tuple[str, str | None]] = []
    cursor = 0
    while cursor < len(line):
        match = next((term for term in terms if line.startswith(term, cursor)), None)
        if match:
            chunks.append((match, match))
            cursor += len(match)
            continue
        next_positions = [line.find(term, cursor + 1) for term in terms]
        next_positions = [pos for pos in next_positions if pos >= 0]
        end = min(next_positions) if next_positions else len(line)
        chunks.append((line[cursor:end], None))
        cursor = end
    return chunks


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, stroke: int = 0) -> int:
    if not text:
        return 0
    box = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
    return box[2] - box[0]


def measured_line_width(
    draw: ImageDraw.ImageDraw,
    line: str,
    font: ImageFont.FreeTypeFont,
    boxed: set[str],
    yellow: set[str],
) -> int:
    chunks = split_terms(line, list(boxed | yellow))
    total = 0
    for text, term in chunks:
        width = text_width(draw, text, font, 3)
        if term in boxed:
            width += max(12, font.size // 8) * 2
        total += width
    return total


def parse_number_list(value: str, label: str) -> list[float]:
    if not value.strip():
        return []
    try:
        return [float(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise ValueError(f"{label} must be a comma-separated number list") from exc


def auto_line_angles(count: int) -> list[float]:
    patterns = {
        1: [-0.8],
        2: [-1.4, 1.0],
        3: [-1.2, 0.7, -1.8],
        4: [-1.0, 0.8, -1.6, 0.9],
        5: [-1.0, 0.7, -1.5, 0.8, -0.9],
    }
    return patterns[count]


def auto_line_widths(lines: list[str]) -> list[float]:
    widths: list[float] = []
    for index, line in enumerate(lines):
        units = sum(1.0 if ord(char) > 127 else 0.62 for char in line)
        if units <= 2.2:
            target = 0.58
        elif units <= 3.3:
            target = 0.72
        elif index == 0:
            target = 0.94
        elif index == len(lines) - 1:
            target = 0.92
        else:
            target = 0.90
        widths.append(target)
    return widths


def fit_line_font(
    draw: ImageDraw.ImageDraw,
    font_path: Path,
    line: str,
    boxed: set[str],
    yellow: set[str],
    target_width: int,
) -> ImageFont.FreeTypeFont:
    for size in range(320, 103, -2):
        font = ImageFont.truetype(str(font_path), size=size)
        if measured_line_width(draw, line, font, boxed, yellow) <= target_width:
            return font
    return ImageFont.truetype(str(font_path), size=102)


def draw_rich_line(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    line: str,
    font: ImageFont.FreeTypeFont,
    boxed: set[str],
    yellow: set[str],
) -> None:
    x, y = xy
    chunks = split_terms(line, list(boxed | yellow))
    pad_x = max(12, font.size // 8)
    pad_y = max(6, font.size // 22)
    for text, term in chunks:
        width = text_width(draw, text, font, 3)
        if term in boxed:
            top = y + max(2, font.size // 12)
            bottom = y + round(font.size * 1.02)
            draw.rounded_rectangle(
                (x, top, x + width + pad_x * 2, bottom + pad_y),
                radius=max(6, font.size // 18),
                fill=YELLOW,
            )
            draw.text(
                (x + pad_x, y),
                text,
                font=font,
                fill=BLACK,
                stroke_width=2,
                stroke_fill=BLACK,
            )
            x += width + pad_x * 2
        else:
            fill = YELLOW if term in yellow else WHITE
            draw.text(
                (x, y),
                text,
                font=font,
                fill=fill,
                stroke_width=7,
                stroke_fill=(0, 0, 0),
            )
            draw.text(
                (x, y),
                text,
                font=font,
                fill=fill,
                stroke_width=2,
                stroke_fill=fill,
            )
            x += width


def render_line_image(
    line: str,
    font: ImageFont.FreeTypeFont,
    boxed: set[str],
    yellow: set[str],
    angle: float,
) -> Image.Image:
    probe = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    probe_draw = ImageDraw.Draw(probe)
    width = measured_line_width(probe_draw, line, font, boxed, yellow)
    padding = max(28, font.size // 5)
    height = round(font.size * 1.34) + padding * 2
    line_image = Image.new("RGBA", (width + padding * 2, height), (0, 0, 0, 0))

    shadow = Image.new("RGBA", line_image.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.text(
        (padding + 9, padding + 8),
        line,
        font=font,
        fill=(0, 0, 0, 190),
        stroke_width=10,
        stroke_fill=(0, 0, 0, 190),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=7))
    line_image = Image.alpha_composite(line_image, shadow)
    draw_rich_line(ImageDraw.Draw(line_image), (padding, padding), line, font, boxed, yellow)
    return line_image.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)


def draw_decorations(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    margin = 34
    length = 55
    weight = 7
    draw.line((margin, margin, margin + length, margin), fill=YELLOW, width=weight)
    draw.line((margin, margin, margin, margin + length), fill=YELLOW, width=weight)
    draw.line((width - margin, margin, width - margin - length, margin), fill=YELLOW, width=weight)
    draw.line((width - margin, margin, width - margin, margin + length), fill=YELLOW, width=weight)
    draw.line((margin, height - margin, margin + length, height - margin), fill=YELLOW, width=weight)
    draw.line((margin, height - margin, margin, height - margin - length), fill=YELLOW, width=weight)
    for index in range(7):
        x = 62 + index * 18
        draw.rectangle((x, 102, x + 7, 109), fill=(76, 80, 82))
    for index in range(5):
        x = 62 + index * 28
        y = height - 95 + (index % 2) * 8
        draw.line((x, y, x + 14, y - 14), fill=YELLOW, width=5)


def render(args: argparse.Namespace) -> dict[str, object]:
    if args.width <= 0 or args.height <= 0:
        raise ValueError("Canvas dimensions must be positive")
    if args.avatar_scale is not None and not 0.55 <= args.avatar_scale <= 0.92:
        raise ValueError("avatar scale must stay between 0.55 and 0.92")
    if args.avatar_x_shift is not None and not 0.0 <= args.avatar_x_shift <= 0.30:
        raise ValueError("avatar x shift must stay between 0.0 and 0.30")
    if args.avatar_y_shift is not None and not 0.0 <= args.avatar_y_shift <= 0.30:
        raise ValueError("avatar y shift must stay between 0.0 and 0.30")
    if not 0 <= args.line_gap <= 120:
        raise ValueError("line gap must stay between 0 and 120 pixels")
    primary_lines = [line.strip() for line in args.title.split("|") if line.strip()]
    supplement_lines = [line.strip() for line in args.supplement.split("|") if line.strip()]
    lines = primary_lines + supplement_lines
    if not 1 <= len(lines) <= 5:
        raise ValueError("Use between 1 and 5 non-empty title lines including supplement")

    boxed = {term.strip() for term in args.boxed_terms.split(",") if term.strip()}
    yellow = {term.strip() for term in args.yellow_terms.split(",") if term.strip()} - boxed
    if args.accent == "none" and (boxed or yellow):
        raise ValueError("Yellow or boxed terms require --accent yellow")
    primary_title_plain = "".join(primary_lines)
    supplement_plain = "".join(supplement_lines)
    title_plain = primary_title_plain + supplement_plain
    for term in boxed | yellow:
        if term not in title_plain:
            raise ValueError(f"Highlighted term is not present in title: {term}")

    background = (
        cover_resize(Image.open(args.background), (args.width, args.height))
        if args.background else Image.new("RGB", (args.width, args.height), BLACK)
    )
    background = ImageEnhance.Contrast(background).enhance(1.05).convert("RGBA")

    shade = Image.new("RGBA", background.size, (0, 0, 0, 0))
    shade_draw = ImageDraw.Draw(shade)
    for x in range(args.width):
        alpha = round(145 * max(0.0, 1.0 - x / (args.width * 0.78)))
        shade_draw.line((x, 0, x, args.height), fill=(0, 0, 0, alpha))
    background = Image.alpha_composite(background, shade)
    draw = ImageDraw.Draw(background)
    if args.accent == "yellow":
        draw_decorations(draw, args.width, args.height)
    font_path = find_font(args.font)
    title_x = 42
    title_y = 72
    max_width = args.width - 78
    max_title_bottom = round(args.height * 0.74)

    if args.left_align and args.line_angles.strip():
        raise ValueError("--left-align cannot be combined with --line-angles")
    angles = (
        [0.0] * len(lines)
        if args.left_align
        else parse_number_list(args.line_angles, "line angles") or auto_line_angles(len(lines))
    )
    width_ratios = parse_number_list(args.line_widths, "line widths") or auto_line_widths(lines)
    if len(angles) != len(lines):
        raise ValueError("line angles count must match the total number of title lines")
    if len(width_ratios) != len(lines):
        raise ValueError("line widths count must match the total number of title lines")
    if any(not 0.35 <= ratio <= 1.0 for ratio in width_ratios):
        raise ValueError("line width ratios must stay between 0.35 and 1.0")
    if any(abs(angle) > 8 for angle in angles):
        raise ValueError("line angles must stay between -8 and 8 degrees")

    fonts = [
        fit_line_font(draw, font_path, line, boxed, yellow, round(max_width * ratio))
        for line, ratio in zip(lines, width_ratios)
    ]
    advances = [round(font.size * 0.91) + args.line_gap for font in fonts]
    available_height = max_title_bottom - title_y
    total_advance = sum(advances[:-1]) + round(fonts[-1].size * 1.12)
    if total_advance > available_height:
        shrink = available_height / total_advance
        fonts = [
            ImageFont.truetype(str(font_path), size=max(102, round(font.size * shrink)))
            for font in fonts
        ]
        advances = [round(font.size * 0.91) + args.line_gap for font in fonts]

    line_offsets = [0, 18, 2, 30, 12]
    cursor_y = title_y
    rendered_line_data: list[dict[str, object]] = []
    for index, (line, font, angle, width_ratio) in enumerate(zip(lines, fonts, angles, width_ratios)):
        line_image = render_line_image(line, font, boxed, yellow, angle)
        if args.left_align:
            visible_bbox = line_image.getchannel("A").getbbox()
            if visible_bbox:
                line_image = line_image.crop(visible_bbox)
            x = title_x
        else:
            x = title_x + line_offsets[index]
        if x + line_image.width > args.width - 18 and not args.left_align:
            x = max(18, args.width - 18 - line_image.width)
        elif x + line_image.width > args.width - 18:
            raise ValueError(
                f"Left-aligned line is too wide for the canvas: {line}. "
                "Lower its --line-widths ratio."
            )
        paste_y = cursor_y - max(18, font.size // 5)
        background.alpha_composite(line_image, (x, paste_y))
        rendered_line_data.append(
            {
                "text": line,
                "fontSize": font.size,
                "angle": angle,
                "targetWidthRatio": width_ratio,
                "x": x,
                "y": paste_y,
            }
        )
        cursor_y += advances[index]

    title_bottom = max(
        style["y"] + round(style["fontSize"] * 1.12) for style in rendered_line_data
    )
    headline_coverage = title_bottom / args.height
    if args.avatar_scale is not None:
        avatar_scale = args.avatar_scale
    elif len(lines) >= 5:
        avatar_scale = 0.74
    elif headline_coverage < 0.63:
        avatar_scale = 0.82
    else:
        avatar_scale = 0.78
    avatar_x_shift = (
        args.avatar_x_shift
        if args.avatar_x_shift is not None
        else (0.12 if avatar_scale >= 0.78 else 0.14)
    )
    avatar_y_shift = (
        args.avatar_y_shift
        if args.avatar_y_shift is not None
        else (0.15 if avatar_scale >= 0.78 else 0.16)
    )

    # Put the portrait in the foreground so the head and shoulder can overlap the
    # lower-right edge of the headline. Its scale follows headline density instead
    # of using one fixed portrait size for every cover.
    if args.avatar:
        background = Image.alpha_composite(
            background,
            avatar_layer(args.avatar, background.size, avatar_scale, avatar_x_shift, avatar_y_shift),
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    final = background.convert("RGB")
    final.save(args.out, format="PNG", optimize=True)
    digest = hashlib.sha256(args.out.read_bytes()).hexdigest()
    manifest = {
        "schemaVersion": 1,
        "style": "bold-black-white",
        "accent": args.accent,
        "image": str(args.out.resolve()),
        "width": args.width,
        "height": args.height,
        "title": title_plain,
        "primaryTitle": primary_title_plain,
        "supplement": supplement_plain,
        "lines": lines,
        "boxedTerms": sorted(boxed),
        "yellowTerms": sorted(yellow),
        "background": str(args.background.resolve()) if args.background else "generated-solid-black",
        "avatar": str(args.avatar.resolve()) if args.avatar else None,
        "portraitLabel": args.portrait_label or (args.avatar.stem if args.avatar else ""),
        "avatarPlacement": {
            "scale": avatar_scale,
            "xShift": avatar_x_shift,
            "yShift": avatar_y_shift,
            "headlineCoverage": round(headline_coverage, 4),
        },
        "font": str(font_path.resolve()),
        "lineStyles": rendered_line_data,
        "lineAlignment": "left" if args.left_align else "dynamic",
        "lineGap": args.line_gap,
        "sha256": digest,
    }
    manifest_path = args.manifest_out or args.out.with_suffix(".json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    args = parse_args()
    manifest = render(args)
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
