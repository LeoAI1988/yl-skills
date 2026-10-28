"""Behavior checks for version-bound archive knowledge receipts."""
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('handoff', Path(__file__).resolve().parents[1] / 'yl-video-archive/scripts/verify_knowledge_handoff.py')
handoff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handoff)

class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        video, text, self.receipt = root/'final.mp4', root/'final.md', root/'receipt.json'
        video.write_bytes(b'fixture media version')
        text.write_text('Complete original words.', encoding='utf-8')
        dedup = root/'dedup.json'
        dedup.write_text('{"decision":"existing body reused"}', encoding='utf-8')
        self.record = dict(source_id='fixture-1', source_sha256=handoff.sha256(text), full_source_read=True,
                           cross_source_dedup_checked=True, cross_source_dedup_receipt=str(dedup),
                           retrieval_verified=True, disposition='merged_into_existing', unresolved=[],
                           ownership='user_owned', dedup_reason='Same proposition; retained variant.',
                           expression_reason='Complete original words retained.', organization_reason='Linked to existing domain.',
                           artifacts=[str(text)])
        self.manifest = dict(items=[dict(source_id='fixture-1', video_path=str(video), video_sha256=handoff.sha256(video),
                                        text_path=str(text), text_sha256=handoff.sha256(text), receipt_path=str(self.receipt))])
    def run_check(self):
        self.receipt.write_text(json.dumps(self.record), encoding='utf-8')
        return handoff.verify(self.manifest)['status']
    def test_complete(self): self.assertEqual(self.run_check(), 'PASS')
    def test_missing_text(self):
        Path(self.manifest['items'][0]['text_path']).unlink()
        self.assertEqual(self.run_check(), 'FAIL')
    def test_changed_text(self):
        Path(self.manifest['items'][0]['text_path']).write_text('Revised', encoding='utf-8')
        self.assertEqual(self.run_check(), 'FAIL')
    def test_changed_video(self):
        Path(self.manifest['items'][0]['video_path']).write_bytes(b'new cut')
        self.assertEqual(self.run_check(), 'FAIL')
    def test_stale_receipt(self):
        self.record['source_sha256']='stale'
        self.assertEqual(self.run_check(), 'FAIL')
    def test_unread(self):
        self.record['full_source_read']=False
        self.assertEqual(self.run_check(), 'FAIL')
    def test_unindexed(self):
        self.record['retrieval_verified']=False
        self.assertEqual(self.run_check(), 'FAIL')
    def test_cross_source_unchecked(self):
        self.record['cross_source_dedup_checked']=False
        self.assertEqual(self.run_check(), 'FAIL')
    def test_missing_dedup_evidence(self):
        Path(self.record['cross_source_dedup_receipt']).unlink()
        self.assertEqual(self.run_check(), 'FAIL')
    def test_unresolved(self):
        self.record['unresolved']=['missing transcript span']
        self.assertEqual(self.run_check(), 'FAIL')
    def test_duplicate_media(self):
        self.manifest['items'].append(copy.deepcopy(self.manifest['items'][0]))
        self.assertEqual(self.run_check(), 'FAIL')
    def test_missing_artifact(self):
        self.record['artifacts']=[str(Path(self.tmp.name)/'absent.md')]
        self.assertEqual(self.run_check(), 'FAIL')
    def test_missing_receipt(self):
        self.assertEqual(handoff.verify(self.manifest)['status'],'FAIL')
    def test_explicit_media_only(self):
        self.manifest['items'][0]['knowledge_exception']={'user_instruction':'Archive media only for this batch.'}
        self.assertEqual(handoff.verify(self.manifest)['status'],'PASS')
    def test_empty(self): self.assertEqual(handoff.verify({})['status'],'FAIL')

if __name__ == '__main__': unittest.main()
