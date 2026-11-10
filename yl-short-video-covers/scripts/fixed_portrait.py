"""Render a user's external, hash-bound portrait layout without adaptive movement."""
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageFilter


def fixed_portrait_layer(avatar_path, canvas_size, layout_path):
    layout_path = Path(layout_path)
    spec = json.loads(layout_path.read_text(encoding="utf-8-sig"))
    if not spec.get("referenceImage"):
        raise ValueError("Fixed portrait requires an independent approved reference image")
    if spec.get("maxMovementPx", 0) != 0 or spec.get("maxScaleChange", 0) != 0:
        raise ValueError("Fixed portrait does not permit adaptive movement or scaling")
    if list(canvas_size) != spec["canvas"]:
        raise ValueError("Fixed portrait canvas differs; do not rescale the template")
    avatar_path = Path(avatar_path)
    digest = hashlib.sha256(avatar_path.read_bytes()).hexdigest()
    if digest != spec["avatarSha256"]:
        raise ValueError("Portrait identity differs from the fixed layout")
    source = Image.open(avatar_path).convert("RGBA")
    bbox = source.getchannel("A").getbbox()
    if not bbox:
        raise ValueError("Empty portrait")
    source = source.crop(bbox)
    h = spec["height"]
    w = round(source.width * h / source.height)
    x, y = spec["x"], spec["y"]
    approved_crop = spec.get("approvedRightCropPx", 0)
    actual_crop = max(0, x + w - canvas_size[0])
    if x < 0 or y < 0 or actual_crop != approved_crop:
        raise ValueError("Fixed portrait differs from the explicitly approved right-shoulder crop")
    if not approved_crop and x + w > canvas_size[0] - spec.get("minRightMargin", 24):
        raise ValueError("Fixed portrait violates the approved right margin")
    resized = source.resize((w, h), Image.Resampling.LANCZOS)
    alpha = resized.getchannel("A").filter(ImageFilter.GaussianBlur(.6))
    layer = Image.new("RGBA", canvas_size)
    layer.paste(resized, (x, y), alpha)
    evidence = {"layoutPath": str(layout_path.resolve()), "layoutSha256": hashlib.sha256(layout_path.read_bytes()).hexdigest(),
                "avatarSha256": digest, "x": x, "y": y, "width": w, "height": h,
                "minTitleLines": spec.get("minTitleLines", 3),
                "approvedRightCropPx": approved_crop,
                "pixelMaskSha256": hashlib.sha256(layer.getchannel("A").tobytes()).hexdigest()}
    reference = spec.get("referenceImage")
    if reference:
        reference = Path(reference)
        if not reference.is_file():
            raise ValueError("Open and restore the fixed portrait reference before rendering")
        from tech_background import prepared_background
        expected_reference = prepared_background(*canvas_size)
        expected_reference.alpha_composite(layer)
        with Image.open(reference) as approved:
            if approved.size != canvas_size or approved.convert("RGB").tobytes() != expected_reference.convert("RGB").tobytes():
                raise ValueError("Portrait position/scale differs from the fixed reference image")
        evidence["referenceSha256"] = hashlib.sha256(reference.read_bytes()).hexdigest()
    return layer, evidence
