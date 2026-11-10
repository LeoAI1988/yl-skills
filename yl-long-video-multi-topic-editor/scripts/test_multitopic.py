"""Behavior checks for frame accounting, source reuse and two-stage delivery."""
import copy
import http.client
import json
import tempfile
import threading
import unittest
from fractions import Fraction
from http.server import ThreadingHTTPServer
from pathlib import Path

import multitopic as tool


def segment(source="source-a", start=0, end=10_000_000, rate="1"):
    return {"source": source, "start_us": start, "end_us": end, "rate": rate,
            "text": "完整原声片段", "purpose": "本段用于解释原因"}


def clip(ident="clip-a", segments=None):
    return {"id": ident, "title": "标题 " + ident, "question": "问题 " + ident,
            "thesis": "判断 " + ident, "logic": ["提出问题", "解释原因", "落点"],
            "opening": "开头 " + ident, "ending": "结尾 " + ident,
            "segments": segments or [segment()]}


def plan(clips=None):
    return {"fps": "30/1", "max_duration_seconds": 180, "shared_ratio_warning": .15,
            "sources": [{"id": "source-a", "duration_us": 7_200_000_000},
                        {"id": "source-b", "duration_us": 7_200_000_000}],
            "clips": clips or [clip()]}


class TimelineTests(unittest.TestCase):
    def test_piecewise_speed_accounts_for_the_opening_separately(self):
        a = segment(end=36_000_000, rate="6/5")
        b = segment(start=40_000_000, end=79_000_000, rate="13/10")
        result = tool.audit(plan([clip(segments=[a, b])]))["clips"][0]
        self.assertEqual((result["frames"], result["duration_seconds"]), (1800, 60))
        self.assertEqual(result["mapping"][1]["output_start_frame"], 900)

    def test_thousands_of_cuts_do_not_accumulate_per_cut_rounding(self):
        cuts = [segment(start=n * 41_000, end=(n + 1) * 41_000) for n in range(1000)]
        result = tool.audit(plan([clip(segments=cuts)]))["clips"][0]
        self.assertEqual(result["frames"], 1230)
        self.assertEqual(result["duration_seconds"], 41)
        for a, b in zip(result["mapping"], result["mapping"][1:]):
            self.assertEqual(a["output_end_frame"], b["output_start_frame"])

    def test_fractional_fps_is_not_silently_rounded_to_thirty(self):
        data = plan([clip(segments=[segment(end=1_001_000_000)])])
        data["fps"] = "30000/1001"
        data["max_duration_seconds"] = 1100
        result = tool.audit(data)["clips"][0]
        self.assertEqual(result["frames"], 30000)
        self.assertEqual(result["duration_seconds"], 1001)

    def test_repeated_usage_does_not_inflate_source_overlap_denominator(self):
        a = clip("a", [segment(), segment()])
        b = clip("b", [segment(start=5_000_000, end=15_000_000)])
        result = tool.audit(plan([a, b]))
        self.assertEqual(result["clips"][0]["unique_source_seconds"], 10)
        self.assertEqual(result["clips"][0]["duration_seconds"], 20)
        self.assertEqual(result["pairs"][0]["shared_source_seconds"], 5)
        self.assertEqual(result["pairs"][0]["shared_min_ratio"], .5)
        self.assertAlmostEqual(result["pairs"][0]["jaccard"], 1 / 3)

    def test_different_sources_are_separate_and_adjacent_intervals_do_not_overlap(self):
        data = plan([clip("a"), clip("b", [segment(source="source-b")]),
                     clip("c", [segment(start=10_000_000, end=20_000_000)])])
        self.assertTrue(all(p["shared_source_seconds"] == 0 for p in tool.audit(data)["pairs"]))

    def test_different_titles_do_not_hide_identical_openings(self):
        a, b = clip("a"), clip("b", [segment(source="source-b")])
        a["opening"] = "同一个开头！"
        b["opening"] = "同一个开头"
        result = tool.audit(plan([a, b]))
        self.assertTrue(any(w["kind"] == "identical_opening" for w in result["warnings"]))
        self.assertEqual(result["actual_listening"], "NOT_PERFORMED")

    def test_invalid_or_out_of_bounds_time_and_speed_are_rejected(self):
        for key, value in [("start_us", -1), ("end_us", 9_000_000_000),
                           ("end_us", 0), ("rate", "0"), ("rate", "-1"),
                           ("start_us", True)]:
            data = plan()
            data["clips"][0]["segments"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                tool.audit(data)

    def test_duration_cap_and_unexplained_frame_loss_are_rejected(self):
        data = plan()
        data["max_duration_seconds"] = 9
        with self.assertRaises(ValueError):
            tool.audit(data)
        data = plan()
        data["clips"][0]["segments"][0]["output_frames"] = 100
        with self.assertRaises(ValueError):
            tool.audit(data)


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="yl-multitopic-test-")
        self.root = Path(self.temp.name)
        (self.root / "edited.mp4").write_bytes(b"edited-current-voice")
        (self.root / "enhanced.mp4").write_bytes(b"enhanced-current-voice")
        fingerprint = {"timeline_sha256": "a" * 64, "audio_sha256": "b" * 64}
        self.data = {"batch": "B0006", "edit_status": "feedback_applied", "clips": [
            {"id": "clip-a", "title": "主题甲", "content_revision": "c03",
             "duration_seconds": 90, **fingerprint,
             "edited": {"path": "edited.mp4", **fingerprint},
             "enhanced": {"path": "enhanced.mp4", **fingerprint}}]}

    def tearDown(self):
        self.temp.cleanup()

    def test_both_stages_reference_exact_assets_without_copies_or_media_changes(self):
        before = {p.name: p.read_bytes() for p in self.root.glob("*.mp4")}
        tool.snapshot(self.data, self.root, self.root / "review")
        assets = tool.read_json(self.root / "review/assets.json")
        self.assertEqual(Path(assets["clip-a.edited"]["path"]), self.root / "edited.mp4")
        self.assertEqual(Path(assets["clip-a.enhanced"]["path"]), self.root / "enhanced.mp4")
        self.assertNotEqual(assets["clip-a.edited"]["sha256"], assets["clip-a.enhanced"]["sha256"])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.glob("*.mp4")})
        self.assertFalse(list((self.root / "review").glob("*.mp4")))
        with self.assertRaises(ValueError):
            tool.snapshot(self.data, self.root, self.root / "review")

    def test_missing_enhanced_stage_does_not_fall_back_to_edited(self):
        self.data["clips"][0]["enhanced"] = None
        tool.snapshot(self.data, self.root, self.root / "review")
        batch = tool.read_json(self.root / "review/batch.json")
        self.assertIsNone(batch["clips"][0]["enhanced"])
        self.assertNotIn("clip-a.enhanced", tool.read_json(self.root / "review/assets.json"))

    def test_stale_timeline_original_audio_hash_and_same_file_stage_are_rejected(self):
        for mutate in [lambda c: c["enhanced"].update(timeline_sha256="c" * 64),
                       lambda c: c["enhanced"].update(audio_sha256="c" * 64),
                       lambda c: c["edited"].update(sha256="0" * 64),
                       lambda c: c["enhanced"].update(path="edited.mp4")]:
            data = copy.deepcopy(self.data)
            mutate(data["clips"][0])
            with self.assertRaises(ValueError):
                tool.snapshot(data, self.root, self.root / "bad-review")
            self.assertFalse((self.root / "bad-review").exists())

    def test_outdated_review_points_and_script_content_cannot_corrupt_the_page(self):
        self.data["clips"][0]["edited"]["points"] = [{"time": 91, "label": "错误位置"}]
        with self.assertRaises(ValueError):
            tool.snapshot(self.data, self.root, self.root / "bad-review")
        self.data["clips"][0]["edited"]["points"] = [{"time": 20, "label": "复核点"}]
        self.data["clips"][0]["title"] = "</script><script>window.unexpected=true</script>"
        tool.snapshot(self.data, self.root, self.root / "review")
        page = (self.root / "review/index.html").read_text("utf-8")
        self.assertNotIn("</script><script>window.unexpected", page)
        self.assertIn("\\u003c/script\\u003e", page)

    def test_http_ranges_head_unknown_paths_and_changed_asset_detection(self):
        tool.snapshot(self.data, self.root, self.root / "review")
        server = ThreadingHTTPServer(("127.0.0.1", 0), tool.handler(self.root / "review"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def request(path, headers=None, method="GET"):
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
                connection.request(method, path, headers=headers or {})
                response = connection.getresponse()
                result = response.status, dict(response.getheaders()), response.read()
                connection.close()
                return result
            status, headers, body = request("/asset/clip-a.edited", {"Range": "bytes=2-7"})
            self.assertEqual((status, body), (206, b"ited-c"))
            self.assertEqual(headers["Content-Range"], "bytes 2-7/20")
            self.assertEqual(request("/asset/clip-a.enhanced", {"Range": "bytes=-5"})[2], b"voice")
            self.assertEqual(request("/asset/clip-a.edited", {"Range": "bytes=200-"})[0], 416)
            self.assertEqual(request("/asset/../../edited.mp4")[0], 404)
            self.assertEqual(request("/assets.json")[0], 404)
            self.assertEqual(request("/asset/clip-a.edited", method="HEAD")[2], b"")
            (self.root / "edited.mp4").write_bytes(b"changed")
            self.assertEqual(request("/asset/clip-a.edited")[0], 409)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_runtime_outputs_cannot_enter_the_core(self):
        with self.assertRaises(ValueError):
            tool.external(tool.CORE / "new-runtime-data")


if __name__ == "__main__":
    unittest.main()
