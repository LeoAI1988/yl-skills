"""Batch lifecycle regression tests. No real browser, upload or publication."""
import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import test_workbench as fixtures
PNG=fixtures.PNG
from runner import Runner
from batch_runner import BatchPublisher, save_browser_images
from engine import now

class BatchChecks(unittest.TestCase):
    setUp=fixtures.Checks.setUp
    tearDown=fixtures.Checks.tearDown
    plan=fixtures.Checks.plan
    def batch(self):
        self.rows=self.plan(count=3);self.r=Runner(self.s);self.b=BatchPublisher(self.r)
        with patch('batch_runner.threading.Thread'):
            self.job=self.r.start([r['slot'] for r in self.rows],expected_revision=self.s.preparation_revision(),mode='batch_publish')
        self.manifest=json.loads((Path(self.job['folder'])/'queue.json').read_text(encoding='utf-8'))
        return self.job
    def receipt(self,index=0,state='scheduled',**changes):
        item=self.manifest['items'][index];folder=Path(self.job['folder'])/'receipt-test';folder.mkdir(exist_ok=True)
        (folder/'proof.png').write_bytes(PNG);context={**self.manifest,'items':[item],'attempt_started_at':self.job['created_at']}
        raw=dict(asset_id=item['asset_id'],state=state,at=item['at'],account=self.s.account(),observed_at=now().isoformat(),evidence=str(folder/'proof.png'),platform_id='abcdef0123456789abcdef01',platform_at=item['at'],match_basis='continuous_frames_and_record',**changes)
        return raw,folder,context
    def test_batch_freezes_all_three_and_rejects_duplicate_confirmation(self):
        self.batch();self.assertEqual(self.job['count'],3)
        self.assertEqual(len(self.manifest['items']),3)
        self.assertTrue(all(a['state']=='queued' for a in self.s.get('assets')))
        self.assertNotIn('body',self.manifest['items'][0]['asset'])
        with self.assertRaises(ValueError):self.r.start([r['slot'] for r in self.rows],expected_revision=self.s.preparation_revision(),mode='batch_publish')
    def test_any_invalid_item_aborts_before_any_job_or_lock(self):
        rows=self.plan(count=3);self.s.edit(rows[-1]['asset_id'],{'settings':{'ai_declaration':'unknown'}});r=Runner(self.s)
        with self.assertRaises(ValueError):r.start([x['slot'] for x in rows],expected_revision=self.s.preparation_revision(),mode='batch_publish')
        self.assertEqual(self.s.get('jobs'),[]);self.assertTrue(all(a['state']=='ready' for a in self.s.get('assets')))

    def test_browser_session_reused_with_frozen_model(self):
        self.batch();thread='00000000-0000-4000-8000-000000000001'
        self.r.update(self.job['id'],browser_thread_id=thread)
        command=self.r.command(self.job,Path(self.job['folder']))
        self.assertEqual(command[1:4],['exec','resume',thread])
        self.assertNotIn('-C',command)
        self.assertEqual(command[command.index('--model')+1],self.job['executor']['model'])

    def recovery(self):
        self.batch();self.r.active=None
        raw,folder,_=self.receipt(state='unknown',reason_code='browser_connection_unverified_after_upload',upload_started=True,submission_started=False)
        raw['attempt_folder']=str(folder);self.b.set_result(self.job,raw)
        for item in self.manifest['items'][1:]:self.b.set_result(self.job,dict(asset_id=item['asset_id'],state='not_started'))
        self.r.update(self.job['id'],state='attention',attempt_started_at=self.job['created_at'])
        (folder/'recovery-check.jpg').write_bytes(PNG)
        (folder/'events.jsonl').write_text(json.dumps(dict(type='thread.started',thread_id='00000000-0000-4000-8000-000000000001'))+'\n',encoding='utf-8')
        check=dict(observed_at=now().isoformat(),connection_ok=True,upload_complete=True,page_status='editor_upload_complete',account=self.s.account(),file=self.manifest['items'][0]['asset']['name'],tab_id='42')
        (folder/'recovery-check.json').write_text(json.dumps(check),encoding='utf-8')

    def test_resume_requires_new_evidence_and_unchanged_original_scope(self):
        self.recovery()
        with patch('batch_runner.threading.Thread'):
            job=self.b.resume(self.job['id'])
        self.assertEqual(job['state'],'running')
        self.assertEqual(job['resume_existing_asset'],self.job['items'][0])
        self.assertEqual(len(job['recovery_history']),1)
        self.assertEqual(len(job['results']),3)

    def test_recovered_connection_loss_keeps_original_upload(self):
        self.recovery();jobs=self.s.get('jobs');jobs[0]['results'][0]['reason_code']='browser_connection_lost';self.s.set('jobs',jobs)
        with patch('batch_runner.threading.Thread'):job=self.b.resume(self.job['id'])
        self.assertEqual(job['resume_existing_asset'],self.manifest['items'][0]['asset_id'])
        self.assertEqual(job['count'],3)

    def test_screenshots_are_persisted_without_claiming_success(self):
        import base64
        event={'type':'mcp_tool_call','status':'completed','result':{'content':[{'type':'image','mimeType':'image/png','data':base64.b64encode(PNG).decode()}]}}
        save_browser_images(event,self.root)
        self.assertEqual(len(list(self.root.glob('browser-shot-*.png'))),1)
        self.assertEqual(next(self.root.glob('browser-shot-*.png')).read_bytes(),PNG)
        event['result']['content'][0]['data']='invalid'
        save_browser_images(event,self.root)
        self.assertEqual(len(list(self.root.glob('browser-shot-*'))),1)
        self.assertEqual(self.s.get('jobs'),[])

    def test_unstable_connection_needs_same_new_proof_as_other_recovery(self):
        self.recovery();jobs=self.s.get('jobs');jobs[0]['results'][0]['reason_code']='browser_connection_unstable';self.s.set('jobs',jobs)
        with patch('batch_runner.threading.Thread'):job=self.b.resume(self.job['id'])
        self.assertEqual(job['resume_existing_asset'],self.manifest['items'][0]['asset_id'])

    def test_resume_cannot_repeat_a_possible_submission(self):
        self.recovery();jobs=self.s.get('jobs');jobs[0]['results'][0]['submission_started']=True;self.s.set('jobs',jobs)
        with self.assertRaisesRegex(ValueError,'恢复条件'):self.b.resume(self.job['id'])
        self.assertEqual(self.s.get('jobs')[0]['state'],'attention')
    def test_success_serially_continues_and_reports_submitted(self):
        self.batch();seen=[]
        def execute(job,manifest,item,index,mode):
            seen.append(item['asset_id'])
            return dict(asset_id=item['asset_id'],state='scheduled',platform_id='abcdef0123456789abcdef01',platform_at=item['at'])
        with patch.object(self.b,'execute',side_effect=execute):self.b.run(self.job,self.manifest,self.manifest['items'],'batch_publish')
        self.assertEqual(seen,self.job['items']);self.assertEqual(self.s.get('jobs')[0]['state'],'completed');self.assertIsNone(self.r.active)
        self.assertIn('提交 3 篇',self.s.get('jobs')[0]['message'])
    def test_second_uncertain_stops_third_and_keeps_first_receipt(self):
        self.batch();calls=[]
        def execute(job,manifest,item,index,mode):
            calls.append(index)
            return dict(asset_id=item['asset_id'],state='scheduled' if index==1 else 'unknown',platform_id='abcdef0123456789abcdef01',platform_at=item['at'])
        with patch.object(self.b,'execute',side_effect=execute):self.b.run(self.job,self.manifest,self.manifest['items'],'batch_publish')
        self.assertEqual(calls,[1,2]);saved=self.s.get('jobs')[0]
        self.assertEqual([r['state'] for r in saved['results']],['scheduled','unknown','not_started'])
        self.assertEqual(saved['state'],'attention')
        assets={a['id']:a for a in self.s.get('assets')};self.assertEqual(assets[self.job['items'][2]]['state'],'ready')
    def test_preflight_failure_does_not_require_pointless_verify(self):
        self.batch();raw,folder,context=self.receipt(state='not_uploaded',preflight_only=True,upload_started=False,submission_started=False)
        result=self.b.receipt(raw,folder,context,False,'batch_publish');self.assertEqual(result['state'],'not_uploaded')
        with patch.object(self.b,'execute',return_value=result):self.b.run(self.job,self.manifest,self.manifest['items'],'batch_publish')
        self.assertEqual(self.s.get('jobs')[0]['state'],'paused');self.assertTrue(all(a['state']=='ready' for a in self.s.get('assets')))
        with self.assertRaises(ValueError):self.b.verify(self.job['id'])
    def test_touched_item_cannot_be_claimed_not_uploaded(self):
        self.batch();raw,folder,context=self.receipt(state='not_uploaded',preflight_only=True,upload_started=False,submission_started=False)
        self.assertEqual(self.b.receipt(raw,folder,context,True,'batch_publish')['state'],'unknown')
        raw.pop('preflight_only');self.assertEqual(self.b.receipt(raw,folder,context,False,'batch_publish')['state'],'unknown')
    def test_unconfirmed_duplicate_is_held_while_other_items_submit(self):
        self.batch();raw,folder,context=self.receipt(state='duplicate_pending',preflight_only=True,upload_started=False,submission_started=False,block_scope='item',reason_code='duplicate_unconfirmed',pending_duplicate_record={'title':'Possible older note'})
        held=self.b.receipt(raw,folder,context,False,'batch_publish');self.assertEqual(held['state'],'duplicate_pending');seen=[]
        def execute(job,manifest,item,index,mode):
            seen.append(index)
            return held if index==1 else dict(asset_id=item['asset_id'],state='scheduled',platform_id='abcdef0123456789abcdef01',platform_at=item['at'])
        with patch.object(self.b,'execute',side_effect=execute):self.b.run(self.job,self.manifest,self.manifest['items'],'batch_publish')
        saved=self.s.get('jobs')[0]
        self.assertEqual(seen,[1,2,3]);self.assertEqual([r['state'] for r in saved['results']],['duplicate_pending','scheduled','scheduled'])
        self.assertEqual(saved['state'],'completed_with_skips');self.assertIn('提交 2 篇',saved['message'])
        self.assertEqual(next(a for a in self.s.get('assets') if a['id']==raw['asset_id'])['state'],'duplicate_pending')
    def test_duplicate_hold_requires_untouched_item_scope_and_current_proof(self):
        self.batch();raw,folder,context=self.receipt(state='duplicate_pending',preflight_only=True,upload_started=False,submission_started=False,block_scope='item',reason_code='duplicate_unconfirmed',pending_duplicate_record={'title':'Candidate'})
        self.assertEqual(self.b.receipt(raw,folder,context,True,'batch_publish')['state'],'unknown')
        self.assertEqual(self.b.receipt(raw,folder,context,False,'verify')['state'],'unknown')
        for change in [{'block_scope':'batch'},{'reason_code':'login_required'},{'preflight_only':False},{'upload_started':True},{'submission_started':True},{'account':'wrong'},{'pending_duplicate_record':{}}]:
            with self.subTest(change=change):self.assertEqual(self.b.receipt({**raw,**change},folder,context,False,'batch_publish')['state'],'unknown')
    def test_filechooser_failure_continues_but_mutation_and_global_faults_stop(self):
        self.batch();raw,folder,context=self.receipt(state='item_failed',preflight_only=True,upload_started=False,submission_started=False,block_scope='item',reason_code='filechooser_timeout',file_selection_completed=False,upload_page_empty=True,note='chooser timed out')
        result=self.b.receipt(raw,folder,context,False,'batch_publish')
        self.assertEqual(result['state'],'item_failed')
        for change in [{'upload_started':True},{'submission_started':True},{'file_selection_completed':True},{'upload_page_empty':False},{'reason_code':'login_required'},{'block_scope':'batch'},{'account':'wrong'}]:
            with self.subTest(change=change):self.assertEqual(self.b.receipt({**raw,**change},folder,context,False,'batch_publish')['state'],'unknown')
        rejected=self.b.receipt(raw,folder,context,True,'batch_publish')
        self.assertEqual(rejected['state'],'unknown');self.assertIn('chooser timed out',rejected['note'])
        calls=[]
        def execute(job,manifest,item,index,mode):
            calls.append(index)
            return result if index==1 else dict(asset_id=item['asset_id'],state='scheduled',platform_id='abcdef0123456789abcdef01',platform_at=item['at'])
        with patch.object(self.b,'execute',side_effect=execute):self.b.run(self.job,self.manifest,self.manifest['items'],'batch_publish')
        self.assertEqual(calls,[1,2,3]);self.assertEqual(self.s.get('jobs')[0]['state'],'completed_with_skips')
        self.assertEqual(next(a for a in self.s.get('assets') if a['id']==raw['asset_id'])['state'],'ready')

    def test_success_proof_and_duplicate_date_are_distinct(self):
        self.batch();raw,folder,context=self.receipt()
        self.assertEqual(self.b.receipt(raw,folder,context,True,'batch_publish')['state'],'scheduled')
        old={**raw,'platform_at':'2020-01-01 10:00'}
        self.assertEqual(self.b.receipt(old,folder,context,True,'batch_publish')['state'],'unknown')
        self.assertEqual(self.b.receipt({**old,'state':'duplicate'},folder,context,False,'batch_publish')['state'],'duplicate')
        self.assertEqual(self.b.receipt({**old,'state':'duplicate'},folder,context,True,'batch_publish')['state'],'unknown')
        self.assertEqual(self.b.receipt({**raw,'account':'wrong'},folder,context,True,'batch_publish')['state'],'unknown')
    def test_verify_failure_preserves_prior_submission_evidence(self):
        self.batch();raw,folder,context=self.receipt();result=self.b.receipt(raw,folder,context,True,'batch_publish')
        self.b.set_result(self.job,result);self.b.set_result(self.job,dict(asset_id=raw['asset_id'],state='unknown',note='browser unavailable'))
        saved=self.s.get('jobs')[0]['results'][0]
        self.assertEqual(saved['previous_confirmed']['state'],'scheduled')
        self.assertEqual(next(a for a in self.s.get('assets') if a['id']==raw['asset_id'])['state'],'scheduled')
    def test_cancel_leaves_remaining_unstarted(self):
        self.batch();self.r.cancel=True
        with patch.object(self.b,'execute') as execute:self.b.run(self.job,self.manifest,self.manifest['items'],'batch_publish');execute.assert_not_called()
        self.assertTrue(all(r['state']=='not_started' for r in self.s.get('jobs')[0]['results']))
    def test_restart_only_locks_interrupted_current_item(self):
        self.batch();Runner(self.s)
        saved=self.s.get('jobs')[0]
        self.assertEqual([r['state'] for r in saved['results']],['unknown','not_started','not_started'])
        assets={a['id']:a for a in self.s.get('assets')}
        self.assertEqual(assets[self.job['items'][0]]['state'],'unknown')
        self.assertEqual(assets[self.job['items'][1]]['state'],'ready')
    def test_stale_batch_confirmation_cannot_publish_updated_content(self):
        rows=self.plan(count=3);r=Runner(self.s);revision=self.s.preparation_revision()
        self.s.edit(rows[0]['asset_id'],{'caption':'changed after confirmation'})
        with self.assertRaises(ValueError):r.start([x['slot'] for x in rows],expected_revision=revision,mode='batch_publish')
        self.assertEqual(self.s.get('jobs'),[])
    def test_idle_executor_is_bounded_even_without_stdout(self):
        self.batch();self.s.config['executor_idle_timeout_seconds']=1
        command=[sys.executable,'-c','import sys,time; sys.stdin.read(); time.sleep(30)']
        start=time.monotonic()
        with patch.object(self.r,'command',return_value=command):result=self.b.execute(self.job,self.manifest,self.manifest['items'][0],1,'batch_publish')
        self.assertLess(time.monotonic()-start,8);self.assertEqual(result['state'],'unknown');self.assertIn('响应',result['note']);self.assertIsNone(self.r.process)

if __name__=='__main__':unittest.main()
