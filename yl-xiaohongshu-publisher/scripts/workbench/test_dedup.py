"""Synthetic files only; no platform requests or real publication."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from engine import Store
from dedup import DedupService, signature, require_unchanged, visual_verdict, review_revision
from runner import execution, Runner
from batch_runner import BatchPublisher


class DedupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.s = Store(dict(platform='xiaohongshu',data_dir=str(self.root/'data'),ffprobe='missing'))
        self.d = DedupService(self.s)

    def tearDown(self): self.tmp.cleanup()

    def asset(self, ident, content, state='ready', title='', name=None):
        folder=self.root/ident;folder.mkdir()
        path=folder/(name or ident+'.mp4');path.write_bytes(content)
        a=dict(id=ident,video=str(path),name=path.name,title=title,duration=20,state=state,selected=True,date='2026-01-01')
        if state=='scheduled':a['sha256']=hashlib.sha256(content).hexdigest()
        return a

    def check(self, assets, deep=None, frames=None):
        self.s.set('assets',assets)
        with patch.object(self.d,'frames',side_effect=frames or (lambda a,h,n:[bytes([30 if a['id']=='a' else 220])*4096]*n)):
            self.d.check(assets,deep or set())
        return {a['id']:a for a in self.s.get('assets')}

    def test_gpt6_supported_and_default_preserved(self):
        self.assertEqual(execution('gpt-6-sol')['model'],'gpt-6-sol')
        self.assertEqual(execution()['model'],'gpt-6-astra')

    def test_renamed_copy_of_history_is_excluded(self):
        a=self.asset('a',b'video',state='scheduled');b=self.asset('b',b'video')
        result=self.check([b,a])
        self.assertEqual(result['a']['state'],'scheduled');self.assertEqual(result['b']['state'],'excluded')

    def test_three_copies_retain_planned_canonical(self):
        assets=[self.asset(i,b'same') for i in ['a','b','c']]
        self.s.set('plan',[dict(asset_id='b')])
        result=self.check(assets)
        self.assertEqual(result['b']['state'],'ready')
        self.assertEqual(sum(a['state']=='excluded' for a in result.values()),2)

    def test_same_title_is_only_suspect_then_distinct_released(self):
        assets=[self.asset(i,i.encode(),title='Same script') for i in ['a','b']]
        result=self.check(assets)
        self.assertTrue(all(a['state']=='duplicate_review' for a in result.values()))
        self.assertEqual(len(self.s.get('dedup_groups')),1)
        result=self.check(list(result.values()),{'a','b'})
        self.assertTrue(all(a['state']=='ready' for a in result.values()))

    def test_same_background_separate_take_not_auto_duplicate(self):
        assets=[self.asset(i,i.encode(),title='Same script') for i in ['a','b']]
        result=self.check(assets,{'a','b'},frames=lambda a,h,n:[bytes([100 if a['id']=='a' else 105])*4096]*n)
        self.assertTrue(all(a['state']=='duplicate_review' for a in result.values()))

    def test_platform_pending_never_released_by_local_distinct(self):
        a=self.asset('a',b'a',state='duplicate_pending',title='Same');b=self.asset('b',b'b',title='Same')
        result=self.check([a,b],{'a','b'})
        self.assertEqual(result['a']['state'],'duplicate_pending');self.assertEqual(result['b']['state'],'ready')

    def test_missing_decoder_holds_new_files(self):
        a=self.asset('a',b'a')
        def fail(*args): raise ValueError('decoder unavailable')
        result=self.check([a],frames=fail)
        self.assertEqual(result['a']['state'],'duplicate_review');self.assertEqual(len(self.s.get('dedup_groups')),1)

    def test_known_history_digest_survives_missing_file(self):
        a=self.asset('a',b'a',state='scheduled');Path(a['video']).unlink()
        result=self.check([a,self.asset('b',b'a')]);self.assertEqual(result['b']['state'],'excluded')

    def test_overwritten_history_keeps_old_digest(self):
        a=self.asset('a',b'a',state='scheduled');Path(a['video']).write_bytes(b'changed')
        result=self.check([a,self.asset('b',b'a')]);self.assertEqual(result['b']['state'],'excluded')

    def test_hash_cache_invalidated_and_publish_detects_source_change(self):
        a=self.asset('a',b'a');first,_=self.d.digest(a)
        a['dedup_signature']=signature(a['video']);Path(a['video']).write_bytes(b'bb')
        second,_=self.d.digest(a);self.assertNotEqual(first,second)
        with self.assertRaisesRegex(ValueError,'发生变化'):require_unchanged(a)

    def test_source_mutation_during_frames_aborts_commit(self):
        a=self.asset('a',b'a')
        def mutate(item,digest,count):
            Path(item['video']).write_bytes(b'changed');return [bytes([30])*4096]*count
        with self.assertRaisesRegex(ValueError,'变化'):self.check([a],frames=mutate)
        self.assertIsNone(self.s.get('dedup_status',{}).get('held'))

    def test_restart_never_releases_unfinished_check(self):
        a=self.asset('a',b'a',state='duplicate_checking');self.s.set('assets',[a]);self.s.set('dedup_status',{'state':'running'})
        DedupService(self.s)
        self.assertEqual(self.s.get('assets')[0]['state'],'duplicate_checking')
        self.assertEqual(self.s.get('dedup_status')['state'],'failed')

    def test_crash_between_scan_and_hold_is_recovered(self):
        self.s.set('assets',[self.asset('a',b'a')]);self.s.set('dedup_status',{'state':'running'})
        DedupService(self.s)
        self.assertEqual(self.s.get('assets')[0]['state'],'duplicate_checking')

    def test_publish_and_second_check_blocked_while_checking(self):
        self.s.dedup_busy=True
        with self.assertRaises(ValueError):self.d.start()
        runner=Runner(self.s)
        with self.assertRaisesRegex(ValueError,'查重'):BatchPublisher(runner).start([],execution(),None)
        with self.assertRaisesRegex(ValueError,'查重'):runner.start([])

    def test_only_strong_dynamic_plus_audio_match_confirms(self):
        frames=[bytes([i*15])*4096 for i in range(12)]
        self.assertEqual(visual_verdict(frames,frames,20,20,True)[0],'duplicate')
        self.assertEqual(visual_verdict(frames,frames,20,20,False)[0],'review')
        static=[bytes([100])*4096]*12
        self.assertEqual(visual_verdict(static,static,20,20,True)[0],'review')

    def test_group_deep_check_preserves_other_groups_and_ready_files(self):
        assets=[self.asset(i,i.encode(),title='Same' if i in 'ab' else '') for i in 'abcd']
        assets[2]['state']='duplicate_review'
        other=dict(id='other',ids=['c'],pairs=[],error='missing earlier')
        self.s.set('dedup_groups',[other])
        result=self.check(assets,{'a','b'})
        self.assertEqual(result['c']['state'],'duplicate_review')
        self.assertEqual(result['d']['state'],'ready')
        self.assertIn(other,self.s.get('dedup_groups'))

    def test_missing_visual_reference_never_clears_previous_suspect(self):
        assets=[self.asset(i,i.encode()) for i in 'ab']
        self.s.set('dedup_groups',[dict(id='pair',ids=['a','b'],pairs=[dict(ids=['a','b'],result='review')])])
        Path(assets[0]['video']).unlink()
        result=self.check(assets,{'a','b'})
        self.assertEqual(result['b']['state'],'duplicate_review')

    def suspect_group(self, names='abc'):
        assets=[self.asset(i,i.encode(),title='Same') for i in names]
        self.check(assets)
        return self.s.get('dedup_groups')[0]

    def test_manual_one_preserves_other_pair(self):
        g=self.suspect_group()
        result=self.d.clear_review(g['id'],'a',review_revision(self.s))
        self.assertEqual(result['released'],['a'])
        self.assertEqual(set(self.s.get('dedup_groups')[0]['ids']),{'b','c'})
        states={a['id']:a['state'] for a in self.s.get('assets')}
        self.assertEqual(states,dict(a='ready',b='duplicate_review',c='duplicate_review'))

    def test_manual_group_persists_on_scan(self):
        g=self.suspect_group()
        self.d.clear_review(g['id'],None,review_revision(self.s))
        result=self.check(self.s.get('assets'))
        self.assertTrue(all(a['state']=='ready' for a in result.values()))
        self.assertEqual(self.s.get('dedup_groups'),[])

    def test_manual_scope_does_not_whitelist_new_candidate(self):
        g=self.suspect_group('ab');self.d.clear_review(g['id'],None,review_revision(self.s))
        result=self.check(self.s.get('assets')+[self.asset('c',b'c',title='Same')])
        self.assertTrue(all(a['state']=='duplicate_review' for a in result.values()))

    def test_manual_changed_file_invalidates_decision(self):
        g=self.suspect_group('ab');self.d.clear_review(g['id'],None,review_revision(self.s))
        assets=self.s.get('assets');Path(assets[0]['video']).write_bytes(b'changed')
        result=self.check(assets)
        self.assertTrue(all(a['state']=='duplicate_review' for a in result.values()))

    def test_manual_changed_signature_rejected_before_mutation(self):
        g=self.suspect_group();before=self.s.get('assets');revision=review_revision(self.s)
        Path(before[0]['video']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'变化'):self.d.clear_review(g['id'],None,revision)
        self.assertEqual(self.s.get('assets'),before)

    def test_manual_stale_revision_rejected(self):
        g=self.suspect_group()
        with self.assertRaisesRegex(ValueError,'变化'):self.d.clear_review(g['id'],None,'stale')

    def test_manual_errors_cannot_be_cleared(self):
        a=self.asset('a',b'a')
        self.check([a],frames=lambda *args: (_ for _ in ()).throw(ValueError('decode failed')))
        g=self.s.get('dedup_groups')[0]
        with self.assertRaisesRegex(ValueError,'未完成'):self.d.clear_review(g['id'],None,review_revision(self.s))

    def test_manual_platform_history_not_released(self):
        a=self.asset('a',b'a',state='scheduled',title='Same');b=self.asset('b',b'b',title='Same')
        self.check([a,b]);g=self.s.get('dedup_groups')[0]
        with self.assertRaisesRegex(ValueError,'本地疑似'):self.d.clear_review(g['id'],None,review_revision(self.s))
        self.d.clear_review(g['id'],'b',review_revision(self.s))
        self.assertEqual(self.s.get('assets')[0]['state'],'scheduled')

    def test_manual_busy_and_exact_bytes_stay_blocked(self):
        g=self.suspect_group('ab');self.s.dedup_busy=True
        with self.assertRaisesRegex(ValueError,'查重'):self.d.clear_review(g['id'],None,review_revision(self.s))
        self.s.dedup_busy=False
        assets=self.s.get('assets');Path(assets[1]['video']).write_bytes(b'a')
        assets[1]['dedup_signature']=signature(assets[1]['video']);assets[1]['sha256']=assets[0]['sha256'];self.s.set('assets',assets)
        with self.assertRaisesRegex(ValueError,'完全相同'):self.d.clear_review(g['id'],None,review_revision(self.s))


if __name__=='__main__': unittest.main()
