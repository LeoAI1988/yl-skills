"""Isolated synthetic checks for writing integration; not a prose-quality benchmark."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from library import ROOT, read_json
from writing_foundation import SHARED_FILES, HOOK, validate

class WritingChecks(unittest.TestCase):
    def check_text(self, value, skill='yl-writing'):
        with tempfile.TemporaryDirectory(prefix='yl-writing-input-') as name:
            path = Path(name)/'article.md'
            raw = value.encode('utf-8')
            path.write_bytes(raw)
            result = subprocess.run([sys.executable, '-B', '-X', 'utf8',
                                     str(ROOT/skill/'scripts/check_writing.py'), str(path)],
                                    capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(path.read_bytes(), raw, 'checker must never edit the input')
            return result

    def test_empty_input_is_not_approval(self):
        self.assertEqual(self.check_text('').returncode, 2)

    def test_plain_text_still_needs_semantic_review(self):
        result = self.check_text('灯亮了。桌上有一张地图。')
        self.assertEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertEqual(report['status'], 'SEMANTIC_REVIEW_REQUIRED')
        self.assertEqual(report['candidate_count'], 0)
        self.assertNotIn('ai_probability', report)

    def test_original_rhetoric_is_candidate_not_automatic_edit(self):
        report = json.loads(self.check_text('我当时说：“不是换人，而是先修好灯。”').stdout)
        self.assertGreater(report['candidate_count'], 0)
        self.assertTrue(all(c['decision']=='unresolved' for c in report['candidates']))

    def test_code_and_url_do_not_create_punctuation_candidates(self):
        result = self.check_text('灯亮了。\n\n```text\n赋能：不是甲而是乙——\n```\n\nhttps://example.org/a:b\n')
        self.assertEqual(json.loads(result.stdout)['candidate_count'], 0)

    def test_bom_and_crlf_hash_is_explicit(self):
        raw = '\ufeff灯亮了。\r\n桌上有地图。'
        report = json.loads(self.check_text(raw).stdout)
        self.assertEqual(report['draft_sha256'], hashlib.sha256(raw.lstrip('\ufeff').encode('utf-8')).hexdigest())

    def test_all_writing_members_work_standalone(self):
        release = read_json(ROOT/'release.json')
        for member, config in release['skills'].items():
            if config['category'] != 'writing':
                continue
            with self.subTest(member=member), tempfile.TemporaryDirectory(prefix='yl-writing-standalone-') as tmp:
                folder = Path(tmp)/member
                shutil.copytree(ROOT/member, folder)
                article = Path(tmp)/'draft.md'
                article.write_text('灯亮了。地图还在桌上。', encoding='utf-8')
                result = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(folder/'scripts/check_writing.py'), str(article)], capture_output=True, text=True, encoding='utf-8', cwd=tmp)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)['status'], 'SEMANTIC_REVIEW_REQUIRED')

    def test_drift_and_missing_contract_are_rejected(self):
        release = read_json(ROOT/'release.json')
        validate(ROOT, release)
        with tempfile.TemporaryDirectory(prefix='yl-writing-drift-') as tmp:
            work = Path(tmp)
            for name, config in release['skills'].items():
                if config['category'] == 'writing':
                    folder = work/name
                    for rel in (*SHARED_FILES, 'SKILL.md'):
                        target = folder/rel
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(ROOT/name/rel, target)
            validate(work, release)
            edited = work/'yl-write-impact-wechat/references/anti-ai-rules.md'
            before = edited.read_bytes()
            edited.write_bytes(before+b'\nDrift\n')
            with self.assertRaisesRegex(ValueError, 'copy differs'):
                validate(work, release)
            edited.write_bytes(before)
            entry = work/'yl-write-impact-wechat/SKILL.md'
            entry.write_text(entry.read_text(encoding='utf-8').replace(HOOK, ''), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'direct-call'):
                validate(work, release)

    def test_voice_style_dependencies_are_public_and_present(self):
        values = read_json(ROOT/'yl-write-voice-led-wechat/references/style-dependencies.json')
        self.assertEqual(set(values['frameworks']), {'chekhov','impact','editorial'})
        for name in values['frameworks'].values():
            if name:
                self.assertTrue((ROOT/name/'SKILL.md').is_file())
                self.assertIn(name, read_json(ROOT/'release.json')['skills'])

if __name__ == '__main__':
    unittest.main()
