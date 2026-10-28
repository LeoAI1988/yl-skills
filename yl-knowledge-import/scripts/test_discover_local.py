import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from discover_local import discover


class DiscoveryTests(unittest.TestCase):
    def test_finds_without_sidecar_and_preserves_registered_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root/'sources'; source.mkdir()
            new = source/'new.md'; new.write_text('new source')
            changed = source/'changed.md'; changed.write_text('revised')
            old = source/'old.md'; old.write_text('same')
            registry = root/'known.json'
            registry.write_text(json.dumps({'sources': [
                {'path': str(changed), 'sha256': hashlib.sha256(b'previous').hexdigest()},
                {'path': str(old), 'sha256': hashlib.sha256(b'same').hexdigest(), 'processing_status': 'pending'}]}))
            result = discover({'knowledge_root': str(root)}, [str(source), str(source)], [registry])
            self.assertEqual({Path(r['path']).name: r['state'] for r in result['candidates']}, {'new.md': 'unregistered', 'changed.md': 'changed'})
            self.assertEqual(len(result['unchanged']), 1)
            self.assertEqual(result['unchanged'][0]['processing_status'], 'pending')
            self.assertEqual(changed.read_text(), 'revised')

    def test_missing_and_outside_roots_are_not_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'knowledge'; root.mkdir()
            cfg = {'knowledge_root': str(root)}
            self.assertEqual(len(discover(cfg, [str(root/'missing')])['errors']), 1)
            with self.assertRaises(ValueError):
                discover(cfg, [str(Path(tmp))])

    def test_conflicting_registries_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/'known.json'
            p.write_text(json.dumps({'sources': [{'path':str(root/'a.md'),'sha256':'a'*64}, {'path':str(root/'a.md'),'sha256':'b'*64}]}))
            with self.assertRaises(ValueError):
                discover({'knowledge_root':str(root)}, [], [p])


if __name__ == '__main__':
    unittest.main()
