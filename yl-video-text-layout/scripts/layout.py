"""Resolve portrait or landscape overlay geometry without accessing media or editing timelines."""
import argparse
import json
import os
from pathlib import Path


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def settings(video, key, folder):
    path = video.get(key)
    return read_json(folder / Path(path).expanduser()) if path else {}


def landscape_layout(width, height, style, backdrop, side=None, region=None):
    if not width > height > 0:
        raise ValueError("Expected a landscape display canvas")
    scale = height / 1080
    size = round(style.get("subtitleSizeAt1080", 76) * scale)
    baseline = round(style.get("subtitleBaselineAt1080", 1000) * scale)
    max_width = round(style.get("subtitleWidthFraction", 0.9) * width)
    if not (0 < size < baseline < height and 0 < max_width <= width):
        raise ValueError("Invalid caption geometry")
    layout = {
        "canvas": [width, height], "subtitleSize": size,
        "subtitleBaseline": baseline, "subtitleMaxWidth": max_width,
        "subtitleCenterX": width / 2,
    }
    if side is None:
        if region is not None:
            raise ValueError("Select a side for the title region")
        return layout
    if side not in ("left", "right"):
        raise ValueError("Expected left or right")
    if region is None:
        region = (0.05, 0.14, 0.46, 0.57) if side == "left" else (0.54, 0.14, 0.95, 0.57)
    left, top, right, bottom = region
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ValueError("Invalid normalized title region")
    if (side == "left" and left + right >= 1) or (side == "right" and left + right <= 1):
        raise ValueError("Title region must be centered on the selected side")
    alpha = backdrop.get("alpha", 0.55)
    feather = round(backdrop.get("featherPixelsAt1080", 50) * scale)
    if not 0 < alpha < 1 or feather < 1:
        raise ValueError("Title backdrop needs translucency and a positive feather")
    layout["title"] = {
        "side": side,
        "regionLTRB": [round(left * width), round(top * height),
                       round(right * width), round(bottom * height)],
        "backdrop": {"color": "black", "alpha": alpha, "featherPx": feather},
    }
    return layout


def title_backdrop(layout, ink_bounds):
    """Render only the feathered plate. ink_bounds is the measured title block (LTRB)."""
    from PIL import Image, ImageDraw, ImageFilter

    width, height = layout["canvas"]
    title = layout["title"]
    x0, y0, x1, y1 = ink_bounds
    left, top, right, bottom = title["regionLTRB"]
    if not (left <= x0 < x1 <= right and top <= y0 < y1 <= bottom):
        raise ValueError("Title ink does not fit the selected region")
    radius = title["backdrop"]["featherPx"]
    padding = round(radius * 0.8)
    mask = Image.new("L", (width, height))
    ImageDraw.Draw(mask).rectangle((x0-padding, y0-padding, x1+padding, y1+padding),
                                   fill=round(255 * title["backdrop"]["alpha"]))
    plate = Image.new("RGBA", (width, height))
    plate.putalpha(mask.filter(ImageFilter.GaussianBlur(radius / 2)))
    return plate


def portrait_layout(width, height, style, title, region):
    reference_width, reference_height = style.get("canvas", [1080, 1920])
    if not (0 < width < height and 0 < reference_width < reference_height):
        raise ValueError("Expected portrait display and reference canvases")
    scale_x, scale_y = width / reference_width, height / reference_height
    size = round(style.get("subtitleSize", 124) * scale_x)
    baseline = round(style.get("subtitleBaseline", 1473) * scale_y)
    max_width = round(style.get("subtitleMaxWidth", 960) * scale_x)
    if not (0 < size < baseline < height and 0 < max_width <= width):
        raise ValueError("Invalid portrait caption geometry")
    layout = {"canvas": [width, height], "subtitleSize": size, "subtitleBaseline": baseline,
              "subtitleMaxWidth": max_width, "subtitleCenterX": width / 2}
    if title:
        left, top, right, bottom = region or (0.035, 0.035, 0.965, 0.255)
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            raise ValueError("Invalid normalized title region")
        layout["title"] = {"regionLTRB": [round(left * width), round(top * height),
                                          round(right * width), round(bottom * height)],
                           "size": round(style.get("titleSize", 130) * scale_x),
                           "alignment": "center"}
        if region is None:
            baselines = [round(value * scale_y) for value in style.get("titleBaselines", [201, 327])]
            if not baselines or any(not 0 < value < height for value in baselines):
                raise ValueError("Invalid portrait title baselines")
            layout["title"]["baselines"] = baselines
            # A custom reference can put the title lower than the default top band.
            layout["title"]["regionLTRB"][1] = max(0, min(round(top * height),
                                                           min(baselines) - layout["title"]["size"]))
            layout["title"]["regionLTRB"][3] = min(height, max(round(bottom * height),
                                                                max(baselines) + layout["title"]["size"] // 3))
    elif region is not None:
        raise ValueError("Select --title for a portrait title region")
    return layout


def resolve(width, height, style, backdrop, side=None, region=None, title=False):
    if width < height:
        if side is not None:
            raise ValueError("Use --title for portrait placement")
        return portrait_layout(width, height, style, title, region)
    if title and side is None:
        raise ValueError("Select the clear side for the landscape title")
    return landscape_layout(width, height, style, backdrop, side, region)


def main(landscape_only=False):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--title", action="store_true")
    parser.add_argument("--side", choices=["left", "right"])
    parser.add_argument("--title-region", nargs=4, type=float)
    parser.add_argument("--profile", type=Path)
    args = parser.parse_args()
    configured = args.profile or os.environ.get("YL_PROFILE")
    profile = Path(configured or "~/.config/yl-toolbox/profile.json").expanduser()
    try:
        video = read_json(profile).get("video", {}) if configured or profile.exists() else {}
        if landscape_only and args.width <= args.height:
            raise ValueError("Expected a landscape display canvas")
        key = "landscape_style_file" if args.width > args.height else "visual_style_file"
        style = settings(video, key, profile.parent)
        motion = settings(video, "emphasis_style_file", profile.parent) if args.side else {}
        layout = resolve(args.width, args.height, style, motion.get("backdrop", {}),
                         args.side, args.title_region, args.title)
    except (OSError, TypeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(layout, indent=2))


if __name__ == "__main__":
    main()
