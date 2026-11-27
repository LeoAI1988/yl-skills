"""Resolve a named landscape presenter style to display-pixel bounds."""
import argparse
import json
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def resolve_style(style, profile=None):
    path = Path(style).expanduser()
    if not path.is_file():
        config = Path(profile) if profile else Path.home() / ".config/yl-toolbox/profile.json"
        names = read(config).get("video", {}).get("presenter_board_styles", {})
        if style not in names:
            raise ValueError(f"Unknown style {style!r}. Supply a preset path or registered name.")
        path = config.parent / Path(names[style]).expanduser()
    result = read(path)
    if result.get("schema") != 1:
        raise ValueError("Expected a version 1 presenter-board preset.")
    return result


def geometry(preset, width, height):
    if width <= height or min(width, height) < 2:
        raise ValueError("Use a positive landscape canvas.")
    windows = {}
    for mode in ("split", "hero", "demo"):
        rect = preset["windows"][mode]
        if len(rect) != 4 or not (0 <= rect[0] < rect[2] <= 1 and 0 <= rect[1] < rect[3] <= 1):
            raise ValueError(f"Invalid rectangle for {mode}.")
        windows[mode] = [round(v * (width if i % 2 == 0 else height)) for i, v in enumerate(rect)]
    lines = preset["caption_centres"]
    if not 0 < lines[0] < lines[1] < 1:
        raise ValueError("Caption centres must be ordered and inside the canvas.")
    layout = {"width": width, "height": height, "windows": windows,
            "caption_centres": [round(v * height) for v in lines],
            "palette": preset["palette"], "style": preset["name"]}
    opening = preset.get("opening")
    if opening and opening.get("mode") == "fullscreen_to_split":
        if float(opening["transition_seconds"]) <= 0:
            raise ValueError("Opening transition duration must be positive.")
        layout["opening"] = {**opening, "start_rect": [0, 0, width, height],
                             "end_rect": windows["split"]}
    return layout


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--style", required=True)
    parser.add_argument("--profile")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    args = parser.parse_args()
    print(json.dumps(geometry(resolve_style(args.style, args.profile), args.width, args.height),
                     ensure_ascii=False, indent=2))
