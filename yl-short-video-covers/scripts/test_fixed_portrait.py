"""Verify external portrait expectations cannot be dropped or silently moved."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from PIL import Image
from fixed_portrait import fixed_portrait_layer
from tech_background import prepared_background


class FixedPortraitTests(unittest.TestCase):
    def test_independent_reference_identity_and_position(self):
        with tempfile.TemporaryDirectory(prefix="fixed-portrait-") as temp:
            root = Path(temp)
            avatar = root / "avatar.png"
            Image.new("RGBA", (100, 200), (150, 180, 210, 255)).save(avatar)
            spec = {"canvas": [1080, 1440],
                    "avatarSha256": hashlib.sha256(avatar.read_bytes()).hexdigest(),
                    "x": 820, "y": 1000, "height": 400, "minRightMargin": 24,
                    "minTitleLines": 3, "maxMovementPx": 0, "maxScaleChange": 0}
            layout = root / "layout.json"
            layout.write_text(json.dumps(spec), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "reference"):
                fixed_portrait_layer(avatar, (1080, 1440), layout)
            # Construct a separately approved synthetic plate, without private media.
            reference = prepared_background(1080, 1440)
            from PIL import ImageFilter
            resized = Image.open(avatar).resize((200, 400), Image.Resampling.LANCZOS)
            layer = Image.new("RGBA", reference.size)
            layer.paste(resized, (820, 1000), resized.getchannel("A").filter(ImageFilter.GaussianBlur(.6)))
            reference.alpha_composite(layer)
            reference.save(root / "reference.png")
            spec["referenceImage"] = str(root / "reference.png")
            layout.write_text(json.dumps(spec), encoding="utf-8")
            _, evidence = fixed_portrait_layer(avatar, (1080, 1440), layout)
            self.assertEqual((evidence["x"], evidence["y"], evidence["height"]), (820, 1000, 400))
            spec["x"] = 819
            layout.write_text(json.dumps(spec), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "reference"):
                fixed_portrait_layer(avatar, (1080, 1440), layout)
            spec["x"] = 820
            spec["maxMovementPx"] = 1
            layout.write_text(json.dumps(spec), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "movement"):
                fixed_portrait_layer(avatar, (1080, 1440), layout)

    def test_validator_rejects_removed_fixed_evidence(self):
        with tempfile.TemporaryDirectory(prefix="fixed-validator-") as temp:
            root = Path(temp)
            scripts = Path(__file__).resolve().parent
            image = root / "cover.png"
            render = subprocess.run([sys.executable, "-B", str(scripts / "render_bold_cover.py"),
                "--title", "从想法|到作品", "--yellow-terms", "作品", "--out", str(image)], capture_output=True)
            self.assertEqual(render.returncode, 0, render.stderr.decode(errors="replace"))
            # A valid adaptive cover must not pass when the caller expects a fixed plate.
            check = subprocess.run([sys.executable, "-B", str(scripts / "validate_bold_cover.py"),
                "--image", str(image), "--expected-title", "从想法到作品",
                "--portrait-layout", str(root / "independent-layout.json")], capture_output=True)
            self.assertNotEqual(check.returncode, 0)
            self.assertIn(b"requires fixedPortrait evidence", check.stdout)


if __name__ == "__main__":
    unittest.main()
