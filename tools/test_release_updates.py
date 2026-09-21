"""Synthetic behavioral regressions; no real video or backend acceptance claimed."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT/path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


review = module('review', 'yl-remotion-talking-head-editor/scripts/review_final.py')
coverage = module('coverage', 'yl-remotion-talking-head-editor/scripts/check_asr_coverage.py')
analytics = module('analytics', 'yl-channels-analytics/scripts/summarize.py')


def row(ident='001', views='100', at='2026-01-01T00:00:00+08:00', **kw):
    return {'publication_id': ident, 'views': views, 'captured_at': at,
            'data_maturity': 'mature', 'content_origin': 'original_short_video',
            'metric_scope': 'demo:lifetime', **kw}


class VideoTests(unittest.TestCase):
    def test_caption_containing_character_and_seven_character_repeat(self):
        f = review.candidates([{'text': '今天我们一起去今天我们一起去', 'startMs': 1000, 'endMs': 4000},
                               {'text': '下一页', 'startMs': 4000, 'endMs': 5000}])
        hit = next(x for x in f if x['type'] == 'adjacent_repeat' and x['length'] == 7)
        self.assertEqual(hit['at'], 1)

    def test_near_repeat_and_empty(self):
        self.assertTrue(any(x['type'] == 'adjacent_near_repeat' for x in review.candidates(
            [{'text': '今天我们一起出去今天我们一起出门', 'startMs': 0, 'endMs': 5000}])))
        self.assertEqual(review.candidates([]), [])

    def test_invalid_timing(self):
        with self.assertRaises(ValueError):
            review.candidates([{'text': '你好', 'startMs': 10, 'endMs': 0}])

    def test_failed_audio_scan_is_not_clearance(self):
        with patch.object(review.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'failure')):
            with self.assertRaises(ValueError):
                review.silence('unused', 'ffmpeg')

    def test_no_audio_is_not_clearance(self):
        with patch.object(review.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', 'video only')):
            with self.assertRaises(ValueError):
                review.silence('unused', 'ffmpeg')

    def test_coverage_union_and_difference(self):
        self.assertEqual(coverage.uncovered([[0, 3], [2, 4]], [[0, 1], [.5, 2], [2.3, 3.5]]), [[2, 2.3], [3.5, 4]])
        self.assertEqual(coverage.uncovered([[0, 1]], [[0, 2]]), [])

    def test_coverage_rejects_invalid(self):
        with self.assertRaises(ValueError):
            coverage.uncovered([[2, 1]], [])


class AnalyticsTests(unittest.TestCase):
    def test_latest_dedup_and_string_ids(self):
        result = analytics.summarize([row(), row(views='200', at='2026-01-02T00:00:00+08:00'), row('1', '50')])
        self.assertEqual(result['views_total'], 250)
        self.assertEqual(result['eligible_publications'], 2)

    def test_missing_latest_does_not_fallback(self):
        result = analytics.summarize([row(), row(views='', at='2026-01-02T00:00:00+08:00')])
        self.assertEqual(result['missing_views_count'], 1)
        self.assertIsNone(result['views_median'])

    def test_conflict_and_scope(self):
        for rows in ([row(), row(views='2')], [row(), row('2', metric_scope='other')]):
            with self.assertRaises(ValueError):
                analytics.summarize(rows)

    def test_filter_and_distribution(self):
        rows = [row(str(i), str(v)) for i, v in enumerate([0, 999, 1000, 10000, 50000, 100000])]
        rows += [row('live', '999999', content_origin='live_clip'), row('early', '999999', data_maturity='early')]
        r = analytics.summarize(rows, top=1)
        self.assertEqual(list(r['bands'].values()), [2, 1, 1, 1, 1])
        self.assertEqual(r['trimmed_median_remove_one_each'], 5500)
        self.assertEqual(r['breakout_count'], 1)
        self.assertEqual(r['excluded_rows'], 2)

    def test_zero_total_and_naive_time(self):
        self.assertIsNone(analytics.summarize([row(views='0')])['top_views_share'])
        with self.assertRaises(ValueError):
            analytics.summarize([row(at='2026-01-01')])

    def test_cli_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            output = Path(d)/'existing.json'; output.write_text('protected')
            r = subprocess.run([sys.executable, '-B', str(ROOT/'yl-channels-analytics/scripts/summarize.py'),
                                '--input', str(Path(d)/'missing.csv'), '--output', str(output)], capture_output=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual(output.read_text(), 'protected')


if __name__ == '__main__':
    unittest.main()
