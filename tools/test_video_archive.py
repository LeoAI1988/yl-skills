"""Isolated file-behavior tests; no real media quality or live archive mutation."""
from pathlib import Path
from types import SimpleNamespace
import contextlib,hashlib,importlib.util,io,json,os,subprocess,tempfile,unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('yl_archive',ROOT/'yl-video-archive/scripts/archive_files.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class ArchiveTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='yl-video-archive-test-');self.base=Path(self.tmp.name).resolve();self.root=self.base/'project';self.root.mkdir();self.input=self.root/'records/input.json';self.plan=self.root/'records/plan.json';self.receipt=self.root/'records/receipt.json';self.original=self.root/'input/camera.MTS';self.excluded=self.root/'input/not-selected.MP4'
  self.original.parent.mkdir();self.original.write_bytes(b'original camera bytes'*31);self.excluded.write_bytes(b'not selected'*23);p=self.root/'process';p.mkdir();(p/'final.mp4').write_bytes(b'final video bytes'*17);(p/'cover.png').write_bytes(b'cover bytes'*13);(p/'review.md').write_text('original / actual marked / full final / history / validation',encoding='utf-8');(p/'junk.bin').write_bytes(b'regenerable')
  self.raw={'workspace_root':str(self.root),'files':[{'item_id':'clip','role':role,'source':'process/'+source,'target':'final/clip/'+source} for role,source in [('final_video','final.mp4'),('cover','cover.png'),('review','review.md')]]+[{'item_id':'clip','role':'mother','source':'input/camera.MTS','target':'final/clip/素材原件/camera.MTS','capture_date':'2026-01-01','date_basis':'fixture declared filming date'}],'cleanup_roots':['process'],'protected_paths':['input/not-selected.MP4'],'status':{'actual_listening':'PENDING','enhancement':'SKIPPED_USER_REQUEST','published':False}}
 def tearDown(self):self.tmp.cleanup()
 def write(self):self.input.parent.mkdir(exist_ok=True);self.input.write_text(json.dumps(self.raw),encoding='utf-8')
 def run_plan(self):self.write();m.plan(SimpleNamespace(manifest=self.input,output=self.plan))
 def apply(self):m.apply(SimpleNamespace(plan=self.plan,receipt=self.receipt))
 def cleanup(self,apply=False):m.cleanup(SimpleNamespace(receipt=self.receipt,apply=apply))
 def test_archive_clean_repeat_and_pending_preserved(self):
  before=self.excluded.read_bytes();mother=self.original.read_bytes();self.run_plan();self.assertTrue(self.original.exists());self.assertFalse((self.root/'final').exists());self.apply();self.assertFalse(self.original.exists());self.assertEqual((self.root/'final/clip/素材原件/camera.MTS').read_bytes(),mother);self.apply()
  self.assertRaises(ValueError,self.cleanup,True);self.cleanup();self.assertTrue((self.root/'process').exists());self.cleanup(True);self.assertFalse((self.root/'process').exists());self.assertEqual(self.excluded.read_bytes(),before);self.apply();r=m.load(self.receipt);self.assertEqual(r['state'],'ARCHIVED_AND_CLEANED');self.assertEqual(r['plan']['status'],self.raw['status']);self.assertEqual(len(list((self.root/'final/clip').iterdir())),4)
 def test_target_conflict_has_no_media_mutation(self):
  dest=self.root/'final/clip/final.mp4';dest.parent.mkdir(parents=True);dest.write_bytes(b'other version');self.assertRaises(ValueError,self.run_plan);self.assertTrue(self.original.exists());self.assertEqual(dest.read_bytes(),b'other version');self.assertFalse(self.plan.exists())
 def test_root_outside_and_final_inside_cleanup_rejected(self):
  for bad in ['..','/',str(self.base)]:
   self.raw['cleanup_roots']=[bad];self.assertRaises(ValueError,self.run_plan)
  self.raw['cleanup_roots']=['final'];self.assertRaises(ValueError,self.run_plan);self.assertTrue(self.original.exists())
 def test_changed_snapshot_requires_fresh_precheck(self):
  self.run_plan();self.apply();self.cleanup();(self.root/'process/new.bin').write_bytes(b'new');self.assertRaises(ValueError,self.cleanup,True);self.assertTrue((self.root/'process/new.bin').exists());self.cleanup();self.cleanup(True)
 def test_failure_persists_and_retry_after_source_saved(self):
  self.run_plan();saved=self.root/'final/clip/素材原件/camera.MTS';saved.parent.mkdir(parents=True);saved.write_bytes(self.original.read_bytes());unlink=m.os.unlink
  def fail(p,*a,**kw):
   if Path(p).absolute()==self.original:raise PermissionError('fixture occupied mother')
   return unlink(p,*a,**kw)
  m.os.unlink=fail
  try:self.assertRaises(PermissionError,self.apply)
  finally:m.os.unlink=unlink
  self.assertTrue(self.original.exists());self.assertTrue((self.root/'final/clip/素材原件/camera.MTS').exists());self.assertTrue(self.receipt.exists());self.assertRaises(ValueError,self.cleanup);self.apply();self.assertFalse(self.original.exists());self.assertEqual(m.load(self.receipt)['state'],'ARCHIVED_VERIFIED')
 def test_cleanup_failure_can_resume_after_partial_deletion(self):
  self.run_plan();self.apply();self.cleanup();old=m.purge
  def fail(root,p):
   if p.name=='junk.bin':raise PermissionError('fixture occupied process')
   return old(root,p)
  m.purge=fail
  try:self.assertRaises(PermissionError,self.cleanup,True)
  finally:m.purge=old
  self.assertEqual(m.load(self.receipt)['state'],'CLEANUP_INCOMPLETE');m.verify_receipt(m.load(self.receipt));self.cleanup();self.cleanup(True);self.assertEqual(m.load(self.receipt)['state'],'ARCHIVED_AND_CLEANED')
 def test_tampered_source_prevents_finish(self):
  self.run_plan();(self.root/'process/final.mp4').write_bytes(b'changed');self.assertRaises(ValueError,self.apply);self.assertTrue(self.original.exists());self.assertFalse((self.root/'final/clip/final.mp4').exists())
 def test_missing_mother_prevents_cleanup(self):
  self.run_plan();saved=self.original.read_bytes();self.original.unlink();self.assertRaises(ValueError,self.apply);self.assertEqual(m.load(self.receipt)['state'],'ARCHIVING');self.assertRaises(ValueError,self.cleanup);self.original.write_bytes(saved);self.apply();self.assertEqual(m.load(self.receipt)['state'],'ARCHIVED_VERIFIED')
 def test_rejects_two_covers_and_fake_published_marker(self):
  self.raw['files'].append({'item_id':'clip','role':'cover','source':'process/cover.png','target':'final/clip/second.png'});self.assertRaises(ValueError,self.run_plan);self.raw['files'].pop();self.raw['files'].append({'item_id':'clip','role':'published_marker','source':'process/review.md','target':'final/clip/published.txt'});self.assertRaises(ValueError,self.run_plan)
 def course_setup(self):
  self.raw['archive_type']='course_slices';self.raw['files']=[x for x in self.raw['files'] if x['role']!='mother'];self.course=self.base/'course/source.mp4';self.course.parent.mkdir();self.course.write_bytes(b'course source bytes');self.raw['course_source_references']=[str(self.course)]
 def test_standard_mother_outside_final_directory_rejected(self):
  self.raw['files'][-1]['target']='separate-mothers/camera.MTS';self.assertRaises(ValueError,self.run_plan);self.assertTrue(self.original.exists());self.assertFalse(self.plan.exists())
 def test_course_reference_stays_in_place_and_no_mother_copy(self):
  self.course_setup();before=self.course.read_bytes();self.run_plan();self.apply();self.cleanup();self.cleanup(True);self.assertEqual(self.course.read_bytes(),before);self.assertEqual(len(list((self.root/'final/clip').iterdir())),3);self.assertTrue(self.original.exists());m.verify_receipt(m.load(self.receipt))
 def test_course_requires_source_and_rejects_mother_copy(self):
  mother=self.raw['files'][-1].copy();self.course_setup();self.raw['files'].append(mother);self.assertRaises(ValueError,self.run_plan);self.raw['files'].pop();self.raw['course_source_references']=[];self.assertRaises(ValueError,self.run_plan);self.raw['course_source_references']=[str(self.base/'missing.mp4')];self.assertRaises(ValueError,self.run_plan);self.assertFalse(self.plan.exists())
 def test_changed_course_source_prevents_cleanup(self):
  self.course_setup();self.run_plan();self.apply();self.cleanup();self.course.write_bytes(b'replaced source');self.assertRaises(ValueError,self.cleanup,True);self.assertTrue((self.root/'process').exists())
 def test_course_source_inside_cleanup_rejected(self):
  self.course_setup();self.raw['course_source_references']=[str(self.root/'process/final.mp4')];self.assertRaises(ValueError,self.run_plan);self.assertFalse(self.plan.exists())
 def test_linked_inputs_rejected_cleanup_link_does_not_follow(self):
  outside=self.base/'outside';outside.mkdir();asset=outside/'important.txt';asset.write_bytes(b'keep outside');link=self.root/'linked'
  if os.name=='nt':
   env={**os.environ,'YL_ARCHIVE_TEST_LINK':str(link),'YL_ARCHIVE_TEST_TARGET':str(outside)};proc=subprocess.run(['powershell','-NoProfile','-Command','New-Item -ItemType Junction -Path $env:YL_ARCHIVE_TEST_LINK -Target $env:YL_ARCHIVE_TEST_TARGET | Out-Null'],env=env,capture_output=True)
   if proc.returncode:self.skipTest('Junction creation not available')
  else:link.symlink_to(outside,target_is_directory=True)
  self.raw['files'][0]['source']='linked/important.txt';self.assertRaises(ValueError,self.run_plan);self.raw['files'][0]['source']='process/final.mp4';self.run_plan();self.apply();link.rename(self.root/'process/linked');self.cleanup();self.cleanup(True);self.assertEqual(asset.read_bytes(),b'keep outside');self.assertFalse((self.root/'process').exists())
if __name__=='__main__':
 with contextlib.redirect_stdout(io.StringIO()):result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ArchiveTests))
 print(json.dumps({'tests':result.testsRun,'failed':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'scope':'isolated file behavior only'}));raise SystemExit(not result.wasSuccessful())
