import importlib.util
from pathlib import Path
import unittest


script = Path(__file__).resolve().parents[1] / "scripts/render-emphasis-overlays.py"
module = importlib.util.spec_from_file_location("emphasis", script)
emphasis = importlib.util.module_from_spec(module)
module.loader.exec_module(emphasis)


def example(x, y, x2, y2):
    line = dict(kind="line", arrow=True, x=x, y=y, x2=x2, y2=y2, width=5,
                headLength=15, headWidth=14, startFrame=0, endFrame=18,
                keyframes=[dict(frame=0, draw=0), dict(frame=8, draw=1, ease="linear"),
                           dict(frame=13, draw=1), dict(frame=17, draw=0, ease="linear")])
    return dict(width=200, height=160, fps=25, durationInFrames=18, fonts={}, components=[line])


class MotionTest(unittest.TestCase):
    def test_circle_opacity_and_legacy_override(self):
        spec = dict(width=160, height=160, fps=30, durationInFrames=1, fonts={},
                    backdrop={"alpha": .6, "circleAlpha": .4})
        component = dict(kind="backdrop", shape="circle", x=30, y=30,
                         width=100, height=100, feather=4, startFrame=0, endFrame=1)
        spec["components"] = [component]
        def mask():
            return emphasis.Renderer(spec, Path.cwd()).frame(0).getchannel("A")
        alpha = mask()
        self.assertEqual(alpha.getpixel((80, 80)), 102)
        self.assertLess(0, alpha.getpixel((30, 80)))
        self.assertLess(alpha.getpixel((30, 80)), 102)
        self.assertEqual(alpha.getpixel((0, 80)), 0)
        component["alpha"] = .3
        self.assertEqual(mask().getpixel((80, 80)), round(255 * .3))
        del component["alpha"]
        component["shape"] = "rectangle"
        self.assertEqual(mask().getpixel((80, 80)), 153)

    def test_head_travels_with_tip_in_all_directions(self):
        for end in [(170, 80), (30, 80), (100, 150), (100, 10), (160, 140)]:
            with self.subTest(end=end):
                spec = example(100, 80, *end)
                renderer = emphasis.Renderer(spec, Path.cwd())
                get_mask = lambda f: renderer.frame(f).getchannel("A")
                self.assertIsNone(get_mask(0).getbbox())
                self.assertIsNone(get_mask(17).getbbox())
                xy = tuple((p + q) // 2 for p, q in zip((100, 80), end))
                self.assertGreater(get_mask(4).getpixel(xy), 0)
                self.assertEqual(get_mask(4).getpixel(end), 0)
                self.assertEqual(get_mask(8).getpixel(end), 255)
                self.assertEqual(get_mask(4).tobytes(), get_mask(15).tobytes())
                self.assertNotIn(10, renderer.boundaries())

    def test_mobile_scale_uses_full_picture_and_excludes_head(self):
        spec = example(10, 80, 180, 80)
        spec["motionReview"] = {"displayWidth": 2000, "previewWidth": 400}
        report = emphasis.motion_report(spec)
        arrow = report["arrows"][0]
        self.assertEqual(arrow["shaft"], 31)
        self.assertEqual(arrow["stroke"], 1)
        self.assertFalse(report["passed"])  # head is only 2.8 pixels wide
        spec["components"][0]["headWidth"] = 24
        self.assertTrue(emphasis.motion_report(spec)["passed"])
        spec["components"][0]["x2"] = 27
        self.assertFalse(emphasis.motion_report(spec)["passed"])

    def test_legacy_dimensions_and_short_shaft(self):
        spec = example(25, 80, 30, 80)
        item = spec["components"][0]
        del item["headLength"], item["headWidth"]
        mask = emphasis.Renderer(spec, Path.cwd()).frame(8).getchannel("A")
        self.assertGreaterEqual(mask.getbbox()[0], 25)
        self.assertEqual(mask.getpixel((30, 80)), 255)
        item["arrow"] = False
        self.assertEqual(emphasis.motion_report(spec)["arrows"], [])


if __name__ == "__main__":
    unittest.main()
