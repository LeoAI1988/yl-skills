"""Render frame-timed emphasis graphics and optional existing caption layers.

Pillow is required. Input coordinates and keyframes belong to the final output
frame grid. Fonts, private reference media and task text are supplied externally.
Produces the PNG-state manifest and ffconcat consumed by the existing compositor.
"""
import argparse
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageFilter


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def progress(frame, start, end):
    return min(1.0, max(0.0, (frame - start) / max(1, end - start)))


def arrow_size(line, canvas_height):
    stroke = max(1, line.get("width", 2))
    length = line.get("headLength", max(4 * stroke, canvas_height * .017))
    width = line.get("headWidth", max(3 * stroke, length * .85))
    if length <= 0 or width <= 0:
        raise ValueError("Arrowhead dimensions must be positive")
    return length, width


def draw_connector(draw, line, color, canvas_height):
    x, y = line["x"], line["y"]
    dx, dy = line["x2"] - x, line["y2"] - y
    distance = math.hypot(dx, dy)
    reach = distance * min(1, max(0, line.get("draw", 1)))
    if not reach:
        return
    ux, uy = dx / distance, dy / distance
    tip = (x + ux * reach, y + uy * reach)
    stroke = max(1, round(line.get("width", 2)))
    if not line.get("arrow"):
        draw.line((x, y, *tip), fill=color, width=stroke)
        return
    head, breadth = arrow_size(line, canvas_height)
    scale = min(1, reach / head)
    half = breadth * scale / 2
    bx, by = tip[0] - ux * head * scale, tip[1] - uy * head * scale
    if reach > head:
        draw.line((x, y, bx + ux, by + uy), fill=color, width=stroke)
    draw.polygon([tip, (bx - uy * half, by + ux * half),
                  (bx + uy * half, by - ux * half)], fill=color)


def values_at(component, frame):
    values = dict(component)
    keys = component.get("keyframes", [])
    if not keys:
        return values
    if frame <= keys[0]["frame"]:
        values.update({k: v for k, v in keys[0].items() if k != "frame"})
        return values
    for left, right in zip(keys, keys[1:]):
        if frame <= right["frame"]:
            ratio = progress(frame, left["frame"], right["frame"])
            if right.get("ease", "out-cubic") == "out-cubic":
                ratio = 1 - (1 - ratio) ** 3
            for name in set(left) | set(right):
                if name in {"frame", "ease"}:
                    continue
                a = left.get(name, component.get(name, 0))
                b = right.get(name, a)
                values[name] = a + (b - a) * ratio
            return values
    values.update({k: v for k, v in keys[-1].items() if k not in {"frame", "ease"}})
    return values


class Renderer:
    def __init__(self, spec, base_dir):
        self.spec = spec
        self.backdrop_style = spec.get("backdrop", {})
        self.width = spec["width"]
        self.height = spec["height"]
        self.diagram_text_color = spec.get("diagramTextColor")
        self.white_diagram_text = bool(self.diagram_text_color) and ImageColor.getrgb(self.diagram_text_color)[:3] == (255, 255, 255)
        self.fonts = {}
        for name, value in spec["fonts"].items():
            path = Path(value)
            if not path.is_absolute():
                path = base_dir / path
            if not path.is_file():
                raise ValueError(f"Missing font {name}: {path}")
            self.fonts[name] = path.resolve()
        for component in spec["components"]:
            if component["kind"] not in {"text", "caption", "line", "circle", "pill", "backdrop"}:
                raise ValueError(f"Unsupported kind {component['kind']}")
            if not 0 <= component["startFrame"] < component["endFrame"] <= spec["durationInFrames"]:
                raise ValueError("Component interval outside output")
            keys = component.get("keyframes", [])
            frames = [k["frame"] for k in keys]
            if frames != sorted(set(frames)):
                raise ValueError("Keyframe times must increase strictly")
            if frames and (frames[0] < component["startFrame"] or frames[-1] >= component["endFrame"]):
                raise ValueError("Keyframe outside component interval")

    @lru_cache(maxsize=256)
    def text_image(self, text, font_name, size, color, stroke, shadow, pill, caption=False):
        font = ImageFont.truetype(str(self.fonts[font_name]), size)
        box = font.getbbox(text)
        padding = max(2, round(size * .32)) if caption else 12
        vertical = max(2, round(size * .16)) if caption else padding
        width = math.ceil(font.getlength(text)) + 2 * padding
        height = box[3] - box[1] + 2 * vertical
        image = Image.new("RGBA", (width, height))
        draw = ImageDraw.Draw(image)
        if caption:
            draw.rectangle((0, 0, width - 1, height - 1), fill=(0, 0, 0, 224))
            color, stroke, shadow = "white", 0, False
        elif pill:
            background = (0, 0, 0, 224) if self.white_diagram_text else "white"
            draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=height / 2, fill=background)
        if shadow and not pill:
            layer = Image.new("RGBA", image.size)
            ImageDraw.Draw(layer).text((padding + 2, padding - box[1] + 3), text,
                                      font=font, fill=(0, 0, 0, 170), stroke_width=stroke)
            image.alpha_composite(layer.filter(ImageFilter.GaussianBlur(2)))
        ImageDraw.Draw(image).text((padding, vertical - box[1]), text, font=font,
                                   fill=color, stroke_width=stroke, stroke_fill="black")
        return image

    @lru_cache(maxsize=64)
    def backdrop_image(self, x, y, width, height, feather, alpha, shape="rectangle"):
        mask = Image.new("L", (self.width, self.height))
        draw = ImageDraw.Draw(mask)
        if shape == "circle" and width != height:
            raise ValueError("Circular backdrop requires equal width and height")
        paint = draw.ellipse if shape == "circle" else draw.rectangle
        paint((x, y, x + width, y + height), fill=round(255 * alpha))
        mask = mask.filter(ImageFilter.GaussianBlur(feather))
        layer = Image.new("RGBA", mask.size, (0, 0, 0, 0))
        layer.putalpha(mask)
        return layer

    def frame(self, frame):
        canvas = Image.new("RGBA", (self.width, self.height))
        for component in self.spec["components"]:
            if not component["startFrame"] <= frame < component["endFrame"]:
                continue
            value = values_at(component, frame)
            opacity = min(1, max(0, value.get("opacity", 1)))
            if opacity == 0:
                continue
            kind = value["kind"]
            if kind == "backdrop":
                shape = value.get("shape", "rectangle")
                alpha = self.backdrop_style.get("alpha", 0.55)
                if shape == "circle":
                    alpha = self.backdrop_style.get("circleAlpha", alpha)
                alpha = value.get("alpha", alpha)
                if not math.isfinite(alpha) or not 0 <= alpha <= 1:
                    raise ValueError("Backdrop alpha must be an opacity from 0 to 1")
                layer = self.backdrop_image(value["x"], value["y"], value["width"],
                                            value["height"], value.get("feather", 50),
                                            alpha, shape).copy()
                if opacity != 1:
                    layer.putalpha(layer.getchannel("A").point(lambda a: round(a * opacity)))
                canvas.alpha_composite(layer)
            elif kind in {"text", "pill", "caption"}:
                layer = self.text_image(value["text"], value.get("font", "main"),
                                        value["size"], self.diagram_text_color or value.get("color", "white"),
                                        value.get("stroke", 0), value.get("shadow", True), kind == "pill", kind == "caption").copy()
                scale = value.get("scale", 1)
                if scale != 1:
                    layer = layer.resize((max(1, round(layer.width * scale)), max(1, round(layer.height * scale))), Image.Resampling.LANCZOS)
                x, y = value["x"], value["y"]
                if value.get("align") == "center":
                    x -= layer.width / 2
                if value.get("align") == "right":
                    x -= layer.width
                if opacity != 1:
                    layer.putalpha(layer.getchannel("A").point(lambda a: round(a * opacity)))
                canvas.alpha_composite(layer, (round(x), round(y)))
            else:
                layer = Image.new("RGBA", canvas.size)
                draw = ImageDraw.Draw(layer)
                color = (255, 255, 255, round(255 * opacity))
                x, y = value["x"], value["y"]
                if kind == "circle":
                    radius = value["radius"]
                    draw.ellipse((x - radius, y - radius, x + radius, y + radius),
                                 fill=color if value.get("filled", True) else None,
                                 outline=color, width=max(1, round(value.get("width", 2))))
                else:
                    draw_connector(draw, value, color, self.height)
                canvas.alpha_composite(layer)
        return canvas

    def boundaries(self):
        bounds = {0, self.spec["durationInFrames"]}
        for component in self.spec["components"]:
            bounds.update((component["startFrame"], component["endFrame"]))
            keys = component.get("keyframes", [])
            bounds.update(k["frame"] for k in keys)
            for left, right in zip(keys, keys[1:]):
                props = (set(left) | set(right)) - {"frame", "ease"}
                if any(left.get(k, component.get(k, 0)) != right.get(k, left.get(k, component.get(k, 0))) for k in props):
                    bounds.update(range(left["frame"], right["frame"] + 1))
        return bounds


def motion_report(spec):
    review = spec.get("motionReview", {})
    display_width = review.get("displayWidth", spec["width"])
    preview = review.get("previewWidth", 390)
    limits = {"shaft": review.get("minShaft", 18), "stroke": review.get("minStroke", 1),
              "headWidth": review.get("minHead", 4)}
    if not all(math.isfinite(x) and x > 0 for x in [display_width, preview, *limits.values()]):
        raise ValueError("Review dimensions must be finite and positive")
    ratio = preview / display_width
    rows = []
    for index, component in enumerate(spec["components"]):
        if component["kind"] != "line" or not component.get("arrow"):
            continue
        # Measure a visible drawn state. Geometry and draw can both change over time.
        visible = []
        for f in range(component["startFrame"], component["endFrame"]):
            v = values_at(component, f)
            if v.get("opacity", 1) < .5 or v.get("draw", 1) < .95:
                continue
            head, width = arrow_size(v, spec["height"])
            distance = math.hypot(v["x2"] - v["x"], v["y2"] - v["y"]) * min(1, v.get("draw", 1))
            visible.append((max(0, distance - head) * ratio, max(1, round(v.get("width", 2))) * ratio,
                            width * min(1, distance / head) * ratio, f))
        def margin(sample):
            return min(sample[i] / threshold for i, threshold in enumerate(limits.values())), sample[0]
        shaft, stroke, head_width, frame = max(visible, key=margin, default=(0, 0, 0, None))
        metrics = {"shaft": shaft, "stroke": stroke, "headWidth": head_width}
        rows.append({"componentIndex": index, "frame": frame,
                     **{k: round(v, 2) for k, v in metrics.items()},
                     "passed": all(metrics[k] >= v for k, v in limits.items())})
    return {"passed": all(r["passed"] for r in rows), "previewWidth": preview, "limits": limits, "arrows": rows}


def cadence_report(spec):
    fps = spec["fps"]
    total = spec["durationInFrames"]
    if not math.isfinite(fps) or fps <= 0 or not isinstance(total, int) or total <= 0:
        raise ValueError("Expected positive frame rate and duration")
    low, high = spec.get("cadenceSeconds", [7, 10])
    if not 0 < low <= high or not math.isfinite(high):
        raise ValueError("Invalid target interval")
    points = []
    for anchor in spec.get("anchors", []):
        index = anchor["componentIndex"]
        if type(index) is not int or not 0 <= index < len(spec["components"]):
            raise ValueError("Anchor must reference a diagram component")
        c = spec["components"][index]
        if c["kind"] not in {"text", "pill", "line", "circle"} or not anchor["meaning"].strip():
            raise ValueError("Each anchor needs an information-bearing component and meaning")
        frame = c["startFrame"]
        if type(frame) is not int or not 0 <= frame < c["endFrame"] <= total:
            raise ValueError("Invalid semantic component interval")
        points.append(frame)
    points.sort()
    if len(set(points)) != len(points):
        raise ValueError("Combine components that introduce one point at the same frame")
    edges = [0, *points, total]
    gaps = [{"startFrame": a, "endFrame": b, "seconds": (b-a) / fps}
            for a, b in zip(edges, edges[1:])]
    return {"passed": bool(points) and all(g["seconds"] <= high + 1e-9 for g in gaps),
            "anchorCount": len(points), "targetSeconds": [low, high], "gaps": gaps}


def render(spec_path, output_dir, base_manifest=None):
    spec_path = Path(spec_path).resolve()
    spec = read(spec_path)
    if "anchors" in spec and not cadence_report(spec)["passed"]:
        raise ValueError("Diagram spacing exceeds the target or there are no semantic anchors")
    if "motionReview" in spec and not motion_report(spec)["passed"]:
        raise ValueError("An arrow is too small at the selected preview width; inspect --check-motion")
    output_dir = Path(output_dir).resolve()
    if output_dir.exists():
        raise ValueError("Use a new output directory")
    renderer = Renderer(spec, spec_path.parent)
    base_states = []
    bounds = renderer.boundaries()
    if base_manifest:
        base_manifest = Path(base_manifest).resolve()
        base = read(base_manifest)
        for field in ("width", "height", "fps", "durationInFrames"):
            if base[field] != spec[field]:
                raise ValueError(f"Base layer {field} differs")
        cursor = 0
        for state in base["states"]:
            if state["startFrame"] != cursor or state["endFrame"] <= cursor:
                raise ValueError("Base states must cover the output without gaps")
            cursor = state["endFrame"]
            path = Path(state["image"])
            if not path.is_absolute():
                path = base_manifest.parent / path
            base_states.append({**state, "image": str(path.resolve())})
            bounds.update((state["startFrame"], state["endFrame"]))
        if cursor != spec["durationInFrames"]:
            raise ValueError("Base duration differs")
    output_dir.mkdir(parents=True)
    states = []
    image_cache = {}
    base_index = 0
    last_base = None
    base_image = None
    edges = sorted(bounds)
    for start, end in zip(edges, edges[1:]):
        image = renderer.frame(start)
        if base_states:
            while start >= base_states[base_index]["endFrame"]:
                base_index += 1
            source = base_states[base_index]["image"]
            if source != last_base:
                base_image = Image.open(source).convert("RGBA")
                last_base = source
            combined = base_image.copy()
            combined.alpha_composite(image)
            image = combined
        identity = hashlib.sha256(image.tobytes()).hexdigest()
        if identity not in image_cache:
            target = output_dir / f"state_{len(image_cache):05d}.png"
            image.save(target, compress_level=3)
            image_cache[identity] = str(target)
        path = image_cache[identity]
        if states and states[-1]["image"] == path:
            states[-1]["endFrame"] = end
        else:
            states.append({"startFrame": start, "endFrame": end, "image": path})
    manifest = {key: spec[key] for key in ("width", "height", "fps", "durationInFrames")}
    manifest.update(states=states, specSha256=digest(spec_path), generatorSha256=digest(__file__),
                    fontHashes={name: digest(path) for name, path in renderer.fonts.items()},
                    baseManifestSha256=digest(base_manifest) if base_manifest else None)
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["ffconcat version 1.0"]
    for state in states:
        escaped = state["image"].replace("\\", "/").replace("'", "'\\''")
        lines.extend([f"file '{escaped}'", f"option framerate {spec['fps']}"])
        lines.append(f"duration {(state['endFrame'] - state['startFrame']) / spec['fps']:.12f}")
    escaped = states[-1]["image"].replace("\\", "/").replace("'", "'\\''")
    lines.extend([f"file '{escaped}'", f"option framerate {spec['fps']}"])
    (output_dir / "overlays.ffconcat").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"states": len(states), "uniqueImages": len(image_cache), "manifest": str(output_dir / "manifest.json")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--out-dir")
    action.add_argument("--check-cadence", action="store_true")
    action.add_argument("--check-motion", action="store_true")
    parser.add_argument("--base-manifest")
    args = parser.parse_args()
    if args.check_cadence or args.check_motion:
        report = (cadence_report if args.check_cadence else motion_report)(read(args.spec))
        print(json.dumps(report, ensure_ascii=False))
        raise SystemExit(0 if report["passed"] else 1)
    print(json.dumps(render(args.spec, args.out_dir, args.base_manifest), ensure_ascii=False))
