"""Regression checks for the scene cover's two text layers and face-safe layout."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw, ImageOps


SCRIPT = Path(__file__).with_name("render_scene_cover.py")


class SceneCoverTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="scene-cover-test-")
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name).resolve()
        self.assertEqual(self.work.parent, Path(tempfile.gettempdir()).resolve())
        self.photo = ImageOps.colorize(Image.linear_gradient("L").resize((1920, 1440)), "#eff0d6", "#756958")
        ImageDraw.Draw(self.photo).ellipse((1240, 250, 1560, 760), fill="#c99676")
        self.source = self.work / "photo.png"
        self.cover = self.work / "cover.png"
        self.manifest = self.work / "layout.json"
        self.photo.save(self.source)

    def run_cover(self, *extra):
        return subprocess.run(
            [
                sys.executable, "-B", "-X", "utf8", str(SCRIPT),
                "--frame", str(self.source), "--crop", "570,0,1650,1440",
                "--title", "找到重复|先试一遍",
                "--text-box", "30,45,665,750", "--line-sizes", "0.8,1",
                "--card", "少做重复工作|先找一个例子", "--card-accent", "重复",
                "--card-box", "40,1030,1015,1390", "--card-line-sizes", "1,0.82",
                "--out", str(self.cover), "--manifest-out", str(self.manifest), *extra,
            ],
            capture_output=True, text=True, encoding="utf-8",
        )

    def test_two_layer_scene_keeps_bright_face_and_paints_gold_accent(self):
        result = self.run_cover("--face-box", "660,235,1000,785")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(data["style"], "scene-bold")
        self.assertGreater(data["slantDegrees"], 0)
        self.assertEqual(data["dimensions"], [1080, 1440])
        self.assertEqual(data["sourceSha256"], hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(data["outputSha256"], hashlib.sha256(self.cover.read_bytes()).hexdigest())
        self.assertEqual([line["text"] for line in data["lines"]], ["找到重复", "先试一遍"])
        self.assertEqual([line["text"] for line in data["card"]["lines"]], ["少做重复工作", "先找一个例子"])
        self.assertLess(data["lines"][-1]["bounds"][3], data["card"]["bounds"][1])
        self.assertGreaterEqual(data["lines"][-1]["bounds"][2] - data["lines"][-1]["bounds"][0], 590)
        with Image.open(self.cover) as rendered:
            self.assertEqual(rendered.size, (1080, 1440))
            self.assertEqual(rendered.getpixel((820, 550)), self.photo.getpixel((1390, 550)))
            lead = data["lines"][-1]["bounds"]
            card = data["card"]["bounds"]
            self.assertIn((255, 205, 52), set(rendered.crop(lead).getdata()))
            self.assertIn((255, 205, 52), set(rendered.crop(card).getdata()))

    def test_masked_skin_lift_preserves_unmasked_pixels(self):
        skin = Image.new("L", (1080,1440))
        ImageDraw.Draw(skin).ellipse((760,490,880,610),fill=255)
        mask = self.work / "skin.png"
        skin.save(mask)
        self.assertEqual(self.run_cover("--headline-weight","2").returncode,0)
        with Image.open(self.cover) as original:
            before = original.copy()
        result = self.run_cover("--headline-weight","2","--skin-mask",str(mask),"--skin-lift","0.09")
        self.assertEqual(result.returncode,0,result.stderr)
        with Image.open(self.cover) as graded:
            self.assertGreater(graded.getpixel((820,550))[1],before.getpixel((820,550))[1])
            self.assertEqual(graded.getpixel((940,810)),before.getpixel((940,810)))

    def test_foreground_allows_edge_occlusion_without_changing_face_pixels(self):
        plain = self.run_cover()
        self.assertEqual(plain.returncode, 0, plain.stderr)
        layout = json.loads(self.manifest.read_text(encoding="utf-8"))
        x0, y0, x1, y1 = layout["lines"][-1]["bounds"]
        face = (x1 - 56, y0, x1 + 30, y1)
        photo_crop = self.photo.crop((570, 0, 1650, 1440))
        front = Image.new("RGBA", (1080, 1440))
        front.paste(photo_crop.crop(face).convert("RGBA"), face[:2])
        foreground = self.work / "front.png"
        front.save(foreground)
        protected = ",".join(map(str, face))
        result = self.run_cover("--foreground", str(foreground), "--face-box", protected)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        covered = data["lines"][-1]["foregroundOverlap"]
        self.assertGreater(covered, 0)
        self.assertLess(covered, 0.25)
        with Image.open(self.cover) as rendered:
            center = (face[0]+face[2])//2, (face[1]+face[3])//2
            self.assertEqual(rendered.getpixel(center), photo_crop.getpixel(center))

        front.paste(photo_crop.crop((x0, y0, x1, y1)).convert("RGBA"), (x0, y0))
        front.save(foreground)
        result = self.run_cover("--foreground", str(foreground), "--face-box", protected)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("obscures too much", result.stderr)

    def test_reference_card_variants_stay_inside_card_space(self):
        cases = [
            (("--card-style", "light", "--card-label", "新方法"), {"label": "新方法", "style": "light"}),
            (("--card-strip", "先试一个", "--card-tilt", "3"), {"strip": "先试一个", "tiltDegrees": 3.0}),
        ]
        for args, checks in cases:
            with self.subTest(args=args):
                result = self.run_cover(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                card = json.loads(self.manifest.read_text(encoding="utf-8"))["card"]
                for field, expected in checks.items():
                    self.assertEqual(card[field], expected)
                self.assertEqual(card["bounds"][:2], [40, 1030])
                self.assertLessEqual(card["bounds"][2], 1015)
                self.assertLessEqual(card["bounds"][3], 1390)

    def test_face_guard_rejects_headline_and_card_overlap(self):
        for protected in ("44,95,250,520", "78,1050,280,1200"):
            with self.subTest(protected=protected):
                result = self.run_cover("--face-box", protected)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("crosses a protected face", result.stderr)
                self.assertFalse(self.cover.exists())
                self.assertFalse(self.manifest.exists())


if __name__ == "__main__":
    unittest.main()
