"""Isolated observable file behavior; never touches real user media."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('entropy', Path(__file__).parents[1] / 'scripts/entropy.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class EntropyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='entropy-test-')
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'project'; self.root.mkdir()
        self.records = self.base / 'records'; self.records.mkdir()
        self.original = self.root / 'original.mp4'; self.original.write_bytes(b'original' * 17)
        self.final = self.root / 'final.mp4'; self.final.write_bytes(b'final' * 13)
        self.copy = self.root / 'copy.mp4'; self.copy.write_bytes(self.original.read_bytes())
        self.manifest = self.records / 'manifest.json'; self.plan = self.records / 'plan.json'; self.receipt = self.records / 'result.json'

    def tearDown(self):
        self.temp.cleanup()

    def make_plan(self, actions=None, preserve=None, roots=None):
        data = {'scope_roots': roots or [str(self.root)],
                'preserve': preserve if preserve is not None else [{'path': str(self.original), 'role': 'original'}, {'path': str(self.final), 'role': 'final'}],
                'actions': actions or [{'kind': 'duplicate', 'path': str(self.copy), 'keep': str(self.original)}]}
        m.dump(self.manifest, data)
        return m.build_plan(self.manifest, self.plan)

    def test_scan_dedup_and_no_backup(self):
        scan = self.records / 'scan'; m.inventory([self.root], scan)
        r = m.duplicates(scan / 'inventory.sqlite', self.records / 'dups.json', 0)
        self.assertEqual(r['groups'], 1)
        self.assertEqual(r['maximum_redundant_bytes'], self.original.stat().st_size)
        before = self.original.read_bytes(); self.make_plan(); self.assertTrue(self.copy.exists())
        result = m.execute(self.plan, self.receipt)
        self.assertEqual(result['state'], 'COMPLETED'); self.assertFalse(self.copy.exists())
        self.assertEqual(self.original.read_bytes(), before)
        self.assertFalse(result['backup_created'])
        self.assertEqual({p.name for p in self.root.iterdir()}, {'original.mp4', 'final.mp4'})

    def test_same_size_different_content_is_not_duplicate(self):
        self.copy.write_bytes(b'X' * self.original.stat().st_size)
        scan = self.records / 'scan'; m.inventory([self.root], scan)
        r = m.duplicates(scan / 'inventory.sqlite', self.records / 'dups.json', 0)
        self.assertEqual(r['groups'], 0)
        with self.assertRaises(ValueError): self.make_plan()
        self.assertTrue(self.copy.exists())

    def test_apply_without_execute_does_not_mutate(self):
        self.make_plan()
        call = subprocess.run([sys.executable, '-B', str(Path(m.__file__)), 'apply', '--plan', str(self.plan), '--receipt', str(self.receipt)],
                              text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(call.stdout)['state'], 'NOT_EXECUTED')
        self.assertTrue(self.copy.exists()); self.assertFalse(self.receipt.exists())

    def test_changed_original_refuses_all_deletion(self):
        self.make_plan(); self.original.write_bytes(b'changed')
        with self.assertRaises(ValueError): m.execute(self.plan, self.receipt)
        self.assertTrue(self.copy.exists()); self.assertTrue(self.final.exists())

    def test_changed_tree_requires_new_plan(self):
        work = self.root / 'work'; work.mkdir(); (work / 'part.bin').write_bytes(b'part')
        self.make_plan([{'kind': 'process_tree', 'path': str(work), 'result_confirmed': True}])
        (work / 'new.bin').write_bytes(b'new')
        with self.assertRaises(ValueError): m.execute(self.plan, self.receipt)
        self.assertTrue((work / 'part.bin').exists())

    def test_process_needs_confirmed_result_and_roles(self):
        work = self.root / 'work'; work.mkdir()
        for confirmed, preserve in [(False, None), (True, [])]:
            with self.assertRaises(ValueError):
                self.make_plan([{'kind': 'process_tree', 'path': str(work), 'result_confirmed': confirmed}], preserve=preserve)

    def test_preserve_overlap_and_cross_action_keep_rejected(self):
        with self.assertRaises(ValueError):
            self.make_plan([{'kind': 'process_tree', 'path': str(self.root), 'result_confirmed': True}])
        with self.assertRaises(ValueError):
            self.make_plan([{'kind': 'duplicate', 'path': str(self.copy), 'keep': str(self.original)},
                            {'kind': 'duplicate', 'path': str(self.original), 'keep': str(self.copy)}], preserve=[])

    def test_outside_scope_and_overlapping_roots_refused(self):
        outside = self.base / 'outside.bin'; outside.write_bytes(self.original.read_bytes())
        with self.assertRaises(ValueError): self.make_plan([{'kind': 'duplicate', 'path': str(outside), 'keep': str(self.original)}])
        with self.assertRaises(ValueError): m.validate_roots([self.root, self.root / 'nested'])
        with self.assertRaises(ValueError): m.validate_roots([Path(self.root.anchor)], deletion=True)

    def test_project_cache_removed_dependencies_preserved(self):
        cache = self.root / 'node_modules/.cache/webpack'; cache.mkdir(parents=True)
        (cache / 'packed.bin').write_bytes(b'generated')
        dep = self.root / 'node_modules/installed.js'; dep.write_bytes(b'dependency')
        self.make_plan([{'kind': 'cache_tree', 'path': str(cache), 'inactive': True, 'inactive_evidence': 'fixture idle project'}])
        self.assertEqual(m.execute(self.plan, self.receipt)['state'], 'COMPLETED')
        self.assertFalse(cache.exists()); self.assertEqual(dep.read_bytes(), b'dependency')

    def test_active_or_broad_cache_refused(self):
        cache = self.root / 'node_modules/.cache/webpack'; cache.mkdir(parents=True)
        for path, inactive in [(cache, False), (cache.parents[1], True)]:
            with self.assertRaises(ValueError):
                self.make_plan([{'kind': 'cache_tree', 'path': str(path), 'inactive': inactive, 'inactive_evidence': 'fixture'}])

    def test_plan_tampering_refused(self):
        self.make_plan(); p = m.read(self.plan); p['actions'][0]['path'] = str(self.original); m.dump(self.plan, p)
        with self.assertRaises(ValueError): m.execute(self.plan, self.receipt)
        self.assertTrue(self.original.exists()); self.assertTrue(self.copy.exists())

    def test_receipt_cannot_be_inside_target(self):
        work = self.root / 'work'; work.mkdir(); (work / 'part').write_bytes(b'part')
        self.make_plan([{'kind': 'process_tree', 'path': str(work), 'result_confirmed': True}])
        with self.assertRaises(ValueError): m.execute(self.plan, work / 'receipt.json')
        self.assertTrue((work / 'part').exists())

    def test_hardlinks_not_counted_as_reclaimable_copies(self):
        self.copy.unlink()
        try: os.link(self.original, self.copy)
        except OSError as e: self.skipTest(str(e))
        scan = self.records / 'scan'; m.inventory([self.root], scan)
        result = m.read(scan / 'scan.json')
        self.assertEqual(result['logical_bytes'] - result['unique_identity_bytes'], self.original.stat().st_size)
        r = m.duplicates(scan / 'inventory.sqlite', self.records / 'dups.json', 0)
        self.assertEqual(r['maximum_redundant_bytes'], 0)

    def test_changed_scan_entry_reported(self):
        scan = self.records / 'scan'; m.inventory([self.root], scan); self.copy.write_bytes(b'changed')
        r = m.duplicates(scan / 'inventory.sqlite', self.records / 'dups.json', 0)
        self.assertEqual(r['errors'], 1)

    def test_invalid_timestamp_is_recorded_without_losing_file(self):
        real_lstat = os.lstat
        def unusual_date(path, *args, **kwargs):
            actual = real_lstat(path, *args, **kwargs)
            if Path(path) != self.copy:
                return actual
            values = {key: getattr(actual, key) for key in dir(actual) if key.startswith('st_')}
            values['st_birthtime_ns'] = -(2**64)
            values['st_mtime_ns'] = -(2**64)
            return SimpleNamespace(**values)
        scan = self.records / 'bad-date'
        with mock.patch.object(m.os, 'lstat', unusual_date):
            result = m.inventory([self.root], scan)
        self.assertEqual(result['files'], 3)
        self.assertEqual(result['errors'], 1)
        import sqlite3
        with sqlite3.connect(scan / 'inventory.sqlite') as db:
            row = db.execute('select size,mtime_ns,created_ns from files where path=?', (str(self.copy),)).fetchone()
        db.close()
        self.assertEqual(row, (self.copy.stat().st_size, None, None))
        self.assertTrue(self.copy.exists())

    def test_resume_reuses_unchanged_records_and_refreshes_changed_files(self):
        first = self.records / 'first'; m.inventory([self.root], first)
        self.copy.write_bytes(b'new content')
        (self.root / 'additional.txt').write_bytes(b'additional')
        second = self.records / 'second'
        result = m.inventory([self.root], second, resume_inventory=first / 'inventory.sqlite')
        report = m.read(second / 'scan.json')
        self.assertEqual(result['files'], 4)
        self.assertEqual(report['resumed_file_records'], 2)
        self.assertEqual(report['logical_bytes'], sum(p.stat().st_size for p in self.root.iterdir()))
        self.assertTrue(self.original.exists()); self.assertTrue(self.copy.exists())

    def test_metadata_pass_has_no_database_or_identity_space_claim(self):
        out = self.records / 'quick'
        result = m.quick_inventory([self.root], out)
        report = m.read(out / 'scan.json')
        self.assertEqual(result['files'], 3)
        self.assertEqual(report['logical_bytes'], sum(p.stat().st_size for p in self.root.iterdir()))
        self.assertIsNone(report['unique_identity_bytes'])
        self.assertFalse((out / 'inventory.sqlite').exists())
        self.assertTrue(self.copy.exists())

    def test_metadata_pass_rejects_core_output_and_incomparable_baseline(self):
        with self.assertRaises(ValueError): m.quick_inventory([self.root], m.CORE / 'runtime-output')
        out = self.records / 'first-quick'; m.quick_inventory([self.root], out)
        with self.assertRaises(ValueError):
            m.quick_inventory([self.records], self.base / 'second-quick', out / 'scan.json')

    def test_growth_requires_same_roots_and_exclusions(self):
        first = self.records / 'first'; m.inventory([self.root], first)
        (self.root / 'new.txt').write_bytes(b'12345')
        second = self.records / 'second'; m.inventory([self.root], second, first / 'scan.json')
        self.assertEqual(m.read(second / 'scan.json')['logical_growth_bytes'], 5)
        with self.assertRaises(ValueError): m.inventory([self.records], self.base / 'third', first / 'scan.json')

    @unittest.skipUnless(os.name == 'nt', 'Windows shortcut and junction behavior')
    def test_windows_shortcut_and_junction_target_preserved(self):
        self.make_plan([{'kind': 'duplicate', 'path': str(self.copy), 'keep': str(self.original), 'mode': 'shortcut'}])
        self.assertEqual(m.execute(self.plan, self.receipt)['state'], 'COMPLETED')
        self.assertFalse(self.copy.exists()); self.assertTrue(Path(str(self.copy) + '.lnk').is_file())
        work = self.root / 'work'; work.mkdir(); (work / 'part').write_bytes(b'part')
        external = self.base / 'shared'; external.mkdir(); (external / 'dependency').write_bytes(b'preserve')
        payload = json.dumps({'path': str(work / 'shared'), 'target': str(external)})
        code = "$d=[Console]::In.ReadToEnd()|ConvertFrom-Json;New-Item -ItemType Junction -Path $d.path -Target $d.target|Out-Null"
        subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',code],input=payload,text=True,check=True,capture_output=True)
        scan = self.records / 'linked-scan'; m.inventory([work], scan)
        self.assertEqual(m.read(scan / 'scan.json')['files'], 1)
        quick = self.records / 'quick-linked'; m.quick_inventory([work], quick)
        self.assertEqual(m.read(quick / 'scan.json')['files'], 1)
        self.make_plan([{'kind': 'process_tree', 'path': str(work), 'result_confirmed': True}])
        self.assertEqual(m.execute(self.plan, self.receipt)['state'], 'COMPLETED')
        self.assertFalse(work.exists()); self.assertEqual((external / 'dependency').read_bytes(), b'preserve')


if __name__ == '__main__':
    unittest.main()
