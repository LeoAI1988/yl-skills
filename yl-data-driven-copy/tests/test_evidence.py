"""Synthetic regression cases for source identity, freshness and local history."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('copy_evidence', Path(__file__).parents[1] / 'scripts/evidence.py')
e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.work = self.root / 'work'

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, data):
        path = self.root / name
        e.atomic_json(path, data)
        return path

    def fixture(self):
        manuscript = self.root / 'source.md'
        manuscript.write_text('# 标题\n\n成交金额 ¥10\n\n一句很短的本人原话。\n\n---\n\n内部更新', encoding='utf-8')
        post = {'publication_id': 'one', 'title': '标题', 'date': '2026-01-01',
                'published_at': '2026-01-01T09:00:00+08:00', 'public': True,
                'mature': True, 'content_type': 'video', 'views': 100,
                'follows': 20, 'completion_pct': 30, 'fast_flip_pct': 40,
                'duration_seconds': 45}
        review = {'meta': {'captured_at': '2026-01-10 10:00 +08:00',
                           'from': '2026-01-01', 'to': '2026-01-09'}, 'posts': [post]}
        source = self.write('review.json', review)
        sales = self.write('sales_20260110.json', [{'title': '标题', 'account': 'a',
                           'published': '2026-01-01', 'amount': '10', 'window': '发布筛选',
                           'manuscript': str(manuscript), 'evidence': 'snapshot.png'}])
        config = {'accounts': [{'account': 'a', 'review_glob': str(source)}],
                  'sales_glob': str(sales), 'work_root': str(self.work)}
        return config, source, manuscript

    def packet(self, result):
        return e.read_json(result['packet'])

    def test_short_body_and_sales_window_preserved(self):
        config, _, _ = self.fixture()
        packet = self.packet(e.prepare(config, self.work))
        self.assertEqual(packet['sales'][0]['body'], '一句很短的本人原话。')
        self.assertNotIn('current_post_key', packet['sales'][0])
        self.assertEqual(packet['sales'][0]['sales_period_type'], 'unknown_or_publication_filter')
        self.assertNotIn('total_sales', packet)

    def test_accounts_isolate_duplicate_platform_ids(self):
        config, source, _ = self.fixture()
        config['accounts'].append({'account': 'b', 'review_glob': str(source)})
        packet = self.packet(e.prepare(config, self.work))
        self.assertEqual(len(packet['posts']), 2)
        self.assertEqual({r['cohort_ranked_n'] for r in packet['posts']}, {1})
        self.assertEqual({r['综合评分'] for r in packet['posts']}, {6.0})

    def test_missing_follow_is_unranked(self):
        config, source, _ = self.fixture()
        review = e.read_json(source)
        review['posts'][0]['follows'] = None
        e.atomic_json(source, review)
        packet = self.packet(e.prepare(config, self.work))
        self.assertIsNone(packet['posts'][0]['综合评分'])

    def test_latest_uses_capture_not_modified_time(self):
        config, source, _ = self.fixture()
        old = e.read_json(source)
        old['meta']['captured_at'] = '2025-12-01'
        self.write('review_old.json', old)
        config['accounts'][0]['review_glob'] = str(self.root / 'review*.json')
        packet = self.packet(e.prepare(config, self.work))
        self.assertEqual(packet['accounts'][0]['captured_at'], '2026-01-10 10:00 +08:00')

    def test_same_capture_conflict_does_not_replace_last_success(self):
        config, source, _ = self.fixture()
        e.prepare(config, self.work)
        before = (self.work / 'latest.json').read_bytes()
        conflict = e.read_json(source)
        conflict['posts'][0]['views'] = 99
        self.write('review_conflict.json', conflict)
        config['accounts'][0]['review_glob'] = str(self.root / 'review*.json')
        with self.assertRaisesRegex(ValueError, 'Conflicting sources'):
            e.prepare(config, self.work)
        self.assertEqual((self.work / 'latest.json').read_bytes(), before)

    def test_changed_verified_body_loses_verified_link(self):
        config, _, manuscript = self.fixture()
        links = self.write('links.json', [{'account': 'a', 'publication_id': 'one',
                           'path': str(manuscript), 'source_sha256': e.digest(manuscript.read_bytes()),
                           'status': 'verified', 'evidence': 'Reviewed direct publication record'}])
        config['links_file'] = str(links)
        first = self.packet(e.prepare(config, self.work))
        self.assertEqual(first['summary']['verified_transcript_links'], 1)
        manuscript.write_text('Changed version', encoding='utf-8')
        second = self.packet(e.prepare(config, self.work))
        self.assertNotEqual(first['snapshot_fingerprint'], second['snapshot_fingerprint'])
        self.assertEqual(second['summary']['verified_transcript_links'], 0)
        self.assertEqual(second['warnings'][0]['kind'], 'changed_verified_link')

    def test_ambiguous_versions_are_not_counted_as_single_body(self):
        config, _, manuscript = self.fixture()
        manuscript.write_text('# 标题\n## 同题参考稿一\n第一稿\n## 同题参考稿二\n第二稿', encoding='utf-8')
        packet = self.packet(e.prepare(config, self.work))
        self.assertEqual(packet['summary']['sales_ambiguous_body'], 1)
        self.assertEqual(packet['summary']['sales_single_body'], 0)

    def test_register_retry_and_feedback_conflict(self):
        config, _, manuscript = self.fixture()
        result = e.prepare(config, self.work)
        packet = self.packet(result)
        draft = self.root / 'draft.md'
        draft.write_text('完整的新口播。', encoding='utf-8')
        plan = {key: 'provided' for key in e.PLAN_FIELDS}
        plan.update(mode='remix', parent_sources=[str(manuscript)],
                    source_spans=[{'path': str(manuscript), 'lines': [5, 5],
                                   'sha256': e.digest(manuscript.read_bytes())}],
                    snapshot_fingerprint=packet['snapshot_fingerprint'])
        plan_path = self.write('plan.json', plan)
        one = e.register(self.work, draft, plan_path)
        two = e.register(self.work, draft, plan_path)
        self.assertEqual(one, two)
        self.assertEqual(len(list((self.work / 'history/drafts').glob('*.json'))), 1)
        event = {'draft_id': one['draft_id'], 'account': 'a', 'publication_id': 'one',
                 'published_draft_sha256': one['draft_id'], 'evidence': 'publication confirmed'}
        event_path = self.write('event.json', event)
        self.assertEqual(e.feedback(self.work, event_path), e.feedback(self.work, event_path))
        linked = self.packet(e.prepare(config, self.work))
        self.assertEqual(linked['feedback'][0]['current_metrics']['views'], 100)
        event['published_draft_sha256'] = 'different'
        e.atomic_json(event_path, event)
        with self.assertRaisesRegex(ValueError, 'different draft version'):
            e.feedback(self.work, event_path)

    def test_os_lock_releases_and_rejects_concurrent_mutation(self):
        with e.exclusive_lock(self.work, 'test'):
            with self.assertRaises(OSError):
                with e.exclusive_lock(self.work, 'test'):
                    self.fail('Concurrent lock was acquired')
        with e.exclusive_lock(self.work, 'test'):
            pass


if __name__ == '__main__':
    unittest.main()
