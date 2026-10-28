"""Behavior tests use temporary synthetic data; no real CLI or platform activity."""
import base64
import datetime as dt
import io
import json
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
import engine
from engine import Store, times, matching_tags, source_title, TZ
from rules import DEFAULTS, units, compose_caption, normalize_tags
from runner import Runner, execution, resolve_codex, PREPARE_CHECKS, VERIFY_VIEWS

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII=')

class Checks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.config={'platform':'xiaohongshu','data_dir':str(self.root/'data'),'account':'Synthetic test account','tag_pool':['AI','人工智能','Codex','OpenAI','智能体','知识库','短视频'],'codex':sys.executable,'ffprobe':'missing-test-ffprobe'}
        self.s=Store(self.config);self.media=self.root/'videos';self.media.mkdir()
        for i in range(3):(self.media/f'clip{i}.mp4').write_bytes((str(i)*30).encode())
        (self.media/'clip0-封面.png').write_bytes(PNG);self.s.scan(str(self.media))
        for asset in self.s.get('assets'):
            self.s.edit(asset['id'],{'title':'已确认标题','settings':{'ai_declaration':'none'}})
    def tearDown(self):self.tmp.cleanup()
    def test_batch_edit_is_atomic_and_preserves_other_fields(self):
        assets=self.s.get('assets');revision=self.s.preparation_revision()
        edits=[{'id':a['id'],'patch':{'title':'批量标题','settings':{'ai_declaration':'contains_ai'}}} for a in assets]
        edits[-1]['patch']['title']='字'*21
        with self.assertRaises(ValueError):self.s.edit_many(edits,revision)
        self.assertEqual(self.s.get('assets'),assets)
        edits[-1]['patch']['title']='批量标题'
        updated=self.s.edit_many(edits,revision)
        self.assertEqual(len(updated),3)
        for old,new in zip(assets,updated):
            self.assertEqual(new['cover'],old['cover'])
            self.assertEqual(new['settings']['visibility'],old['settings']['visibility'])
            self.assertEqual(new['settings']['ai_declaration'],'contains_ai')
            self.assertIn('title_source_original',new)
        with self.assertRaisesRegex(ValueError,'变化'):self.s.edit_many(edits,revision)
    def test_batch_locked_item_rejects_entire_batch(self):
        assets=self.s.get('assets');assets[-1]['state']='awaiting_manual';self.s.set('assets',assets)
        with self.assertRaisesRegex(ValueError,'锁定'):
            self.s.edit_many([{'id':a['id'],'patch':{'title':'新标题'}} for a in assets])
        self.assertEqual(self.s.get('assets'),assets)
    def test_source_title_boundaries_and_conflicts(self):
        video=self.media/'clip1.mp4'
        (self.media/'clip10.md').write_text('# 其他视频标题',encoding='utf-8')
        self.assertEqual(source_title(video)[0],'')
        review=self.media/'clip1-审查稿.md'
        review.write_text('# 内部审查稿\n- 发布标题：真实标题\n内部备注',encoding='utf-8')
        self.assertEqual(source_title(video)[0],'真实标题')
        (self.media/'clip1.md').write_text('# 另一个标题',encoding='utf-8')
        self.assertEqual(source_title(video)[0],'')
    def test_codex_upgrade_path_fallback(self):
        appdata=self.root/'appdata';new=appdata/'OpenAI'/'Codex'/'bin'/'new-version'/'codex.exe'
        new.parent.mkdir(parents=True);new.write_bytes(b'test only')
        with patch('runner.shutil.which',return_value=None),patch.dict('runner.os.environ',{'LOCALAPPDATA':str(appdata)}):
            config={'codex':str(self.root/'old-version'/'codex.exe')}
            self.assertEqual(resolve_codex(config),str(new))
            self.assertEqual(resolve_codex({'codex':sys.executable}),sys.executable)
            new.unlink();self.assertIsNone(resolve_codex(config))
    def plan(self,count=1,limit=None):
        ids=[a['id'] for a in self.s.get('assets')][:limit]
        return self.s.arrange(ids,(engine.now().date()+dt.timedelta(days=1)).isoformat(),count)
    def job(self,model=None,effort=None):
        rows=self.plan();self.r=Runner(self.s)
        with patch('runner.threading.Thread'):job=self.start([rows[0]['slot']],model,effort)
        return job,Path(job['attempt_folder'])
    def start(self,slots,model=None,effort=None,revision=None):
        return self.r.start(slots,model,effort,expected_revision=self.s.preparation_revision() if revision is None else revision)
    def proof(self,job,folder,state='awaiting_manual',**updates):
        row=json.loads((folder/'queue.json').read_text(encoding='utf-8'))['items'][0]
        image=folder/'evidence.png';image.write_bytes(PNG)
        item=dict(asset_id=row['asset_id'],state=state,at=row['at'],platform_at=row['at'],account=self.s.account(),observed_at=engine.now().isoformat(),evidence=str(image),checks={k:True for k in PREPARE_CHECKS},platform_id='0123456789abcdefABCDEF01',match_basis='continuous_frames_and_record')
        return {**item,**updates}
    def ingest(self,job,folder,items):
        (folder/'result.json').write_text(json.dumps({'items':items}),encoding='utf-8')
        self.r.ingest(job,folder,True);self.r.finish(job,job['mode']);self.r.active=None
        return next(j for j in self.s.get('jobs') if j['id']==job['id'])
    def verify_job(self,job):
        with patch('runner.threading.Thread'):job=self.r.verify(job['id'])
        return job,Path(job['attempt_folder'])
    def test_default_schedule_and_conservative_limits(self):
        snap=self.s.snapshot();self.assertEqual(snap['preferences']['count'],1)
        self.assertEqual(times(1),['10:00']);self.assertEqual(times(1,'08:10','20:40'),['08:10'])
        self.assertEqual(snap['limits'],{'title':20,'caption':1000,'tags':10,'title_count_mode':'utf16_conservative'})
        self.assertFalse(snap['schedule_policy']['verified'])
        self.assertEqual(snap['schedule_policy']['lead_minutes'],60)
        self.assertEqual(snap['schedule_policy']['window_days'],14)
        for bad in [0,11]:
            with self.assertRaises(ValueError):times(bad)
    def test_spacing_for_local_planning(self):
        for count in range(2,11):
            for steps in range(count-1,144):
                end=steps*10;values=times(count,'00:00',f'{end//60:02}:{end%60:02}')
                mins=[int(t[:2])*60+int(t[3:]) for t in values];gaps=[b-a for a,b in zip(mins,mins[1:])]
                self.assertEqual((mins[0],mins[-1],len(set(mins))),(0,end,count))
                self.assertTrue(all(m%10==0 for m in mins));self.assertGreaterEqual(min(gaps),10);self.assertLessEqual(max(gaps)-min(gaps),10)
    def test_invalid_window_is_atomic(self):
        rows=self.plan();pref=self.s.preferences()
        for start,end,count in [('08:00','08:00',1),('21:00','08:00',2),('08:05','21:00',3),('24:00','23:50',2),('08:00','08:10',3)]:
            with self.assertRaises(ValueError):self.s.arrange([a['id'] for a in self.s.get('assets')],rows[0]['at'][:10],count,start,end)
            self.assertEqual(self.s.get('plan'),rows);self.assertEqual(self.s.preferences(),pref)
    def test_account_persists_through_arrangement(self):
        self.s.set_account('New synthetic account');self.plan()
        self.assertEqual(Store(self.config).snapshot()['account'],'New synthetic account')
        self.assertEqual(self.config['account'],'Synthetic test account')
    def test_empty_account_can_plan_but_cannot_start(self):
        self.s.set('preferences',{'account':''});rows=self.plan();self.r=Runner(self.s)
        with self.assertRaisesRegex(ValueError,'账号'):self.start([rows[0]['slot']])
        self.assertEqual(self.s.get('jobs'),[])
    def test_title_utf16_boundary_and_atomic_edit(self):
        asset=self.s.get('assets')[0]
        for value in ['中'*20,'A'*20,'中'*18+'😀','😀'*10]:
            result=self.s.edit(asset['id'],{'title':value});self.assertEqual(result['counts']['title'],20)
        previous=self.s.get('assets')
        for value in ['中'*21,'A'*21,'中'*19+'😀','😀'*10+'A']:
            with self.assertRaisesRegex(ValueError,'20'):self.s.edit(asset['id'],{'title':value,'caption':'不得部分保存'})
            self.assertEqual(self.s.get('assets'),previous)
        self.assertEqual(units('😀'),2)
    def test_caption_and_appended_tags_share_budget(self):
        ident=self.s.get('assets')[0]['id'];tags=['AI']
        self.assertEqual(compose_caption('正文',tags),'正文\n\n#AI')
        self.s.edit(ident,{'caption':'中'*995,'tags':tags})
        self.assertEqual(self.s.snapshot()['assets'][0]['counts']['total'],1000)
        for caption in ['中'*996,'😀'*500]:
            with self.assertRaisesRegex(ValueError,'1000'):self.s.edit(ident,{'caption':caption,'tags':tags})
        self.s.edit(ident,{'caption':'😀'*500,'tags':[]})
        self.assertEqual(self.s.snapshot()['assets'][0]['counts']['total'],1000)
    def test_tag_limits_normalization_and_no_forced_five(self):
        ident=self.s.get('assets')[0]['id'];tags=['#话题'+str(i) for i in range(10)]
        saved=self.s.edit(ident,{'tags':tags});self.assertEqual(saved['tags'][0],'话题0');self.assertEqual(len(saved['tags']),10)
        with self.assertRaisesRegex(ValueError,'10'):self.s.edit(ident,{'tags':tags+['十一']})
        self.assertEqual(normalize_tags(['AI','#AI','ai','中文','#中文']),['AI','中文'])
        for tags in [['two words'],['#'],['x\ny']]:
            with self.assertRaises(ValueError):normalize_tags(tags)
        self.s.edit(ident,{'tags':[]})
        self.assertEqual(matching_tags('一段无关内容','',self.config['tag_pool'],'a'),[])
        matched=matching_tags('Codex','',self.config['tag_pool'],'a');self.assertIn('Codex',matched);self.assertLess(len(matched),5)
    def test_platform_defaults_and_unsupported_options(self):
        ident=self.s.get('assets')[0]['id']
        self.assertEqual(DEFAULTS,dict(visibility='公开',allow_download=False,collection='',location=False,activity=False,ai_declaration='unknown'))
        for settings in [{'original':True},{'chapters':True},{'hotspot':True},{'visibility':'好友可见'},{'ai_declaration':'fake'}]:
            with self.assertRaises(ValueError):self.s.edit(ident,{'settings':settings})
    def test_overlong_import_is_visible_but_not_executable(self):
        (self.media/'long.mp4').write_bytes(b'new video')
        source='# '+'长'*21+'\n审查稿不可发布'
        (self.media/'long.md').write_text(source,encoding='utf-8');self.s.scan(str(self.media))
        asset=next(a for a in self.s.snapshot()['assets'] if a['name']=='long.mp4')
        self.assertEqual(asset['title'],'长'*21);self.assertTrue(asset['validation_errors']);self.assertEqual(asset['caption'],'')
        self.assertIn('审查稿不可发布',asset['body'])
    def test_inventory_dedup_and_cover_mapping(self):
        (self.media/'copy.mp4').write_bytes((self.media/'clip0.mp4').read_bytes());self.s.scan(str(self.media));self.s.scan(str(self.media))
        assets=self.s.get('assets');self.assertEqual(len(assets),4);self.assertEqual(sum(a['state']=='excluded' for a in assets),1)
        self.assertTrue(next(a for a in assets if a['name']=='clip0.mp4')['cover'].endswith('clip0-封面.png'))
        self.assertFalse(next(a for a in assets if a['name']=='clip1.mp4')['cover'])
    def test_prepare_manifest_excludes_source_and_keeps_user_caption(self):
        assets=self.s.get('assets')
        for asset in assets:asset.update(body='secret review source',title_source='private manuscript path',caption='用户确认正文',tags=['AI'])
        self.s.set('assets',assets);job,folder=self.job();manifest=json.loads((folder/'queue.json').read_text(encoding='utf-8'))
        asset=manifest['items'][0]['asset'];self.assertNotIn('body',asset);self.assertNotIn('title_source',asset)
        self.assertEqual(asset['composed_caption'],'用户确认正文\n\n#AI');self.assertEqual(manifest['mode'],'prepare')
    def test_single_item_unknown_ai_and_empty_title_start_guards(self):
        rows=self.plan();self.r=Runner(self.s)
        with self.assertRaisesRegex(ValueError,'一条'):self.start([r['slot'] for r in rows])
        ident=rows[0]['asset_id'];self.s.edit(ident,{'settings':{'ai_declaration':'unknown'}})
        with self.assertRaisesRegex(ValueError,'AI'):self.start([rows[0]['slot']])
        self.s.edit(ident,{'settings':{'ai_declaration':'none'},'title':''})
        with self.assertRaisesRegex(ValueError,'标题'):self.start([rows[0]['slot']])
        self.assertEqual(self.s.get('jobs'),[])
    def test_execution_revalidates_external_mutation(self):
        rows=self.plan();assets=self.s.get('assets');next(a for a in assets if a['id']==rows[0]['asset_id'])['tags']=['t'+str(i) for i in range(11)];self.s.set('assets',assets)
        self.r=Runner(self.s)
        with self.assertRaisesRegex(ValueError,'10'):self.start([rows[0]['slot']])
    def test_configurable_window_is_preflight_only(self):
        self.s.config.update(schedule_lead_minutes=90,schedule_window_days=3);self.assertEqual(self.s.schedule_policy()['lead_minutes'],90)
        rows=self.plan();current=dt.datetime(2026,1,10,9,0,tzinfo=TZ);self.r=Runner(self.s)
        for at in ['2026-01-10 10:00','2026-01-14 09:00']:
            rows[0]['at']=at;self.s.set('plan',rows)
            with patch('runner.now',return_value=current):
                with self.assertRaisesRegex(ValueError,'预检'):self.start([rows[0]['slot']])
    def test_models_and_reasoning_reach_frozen_command(self):
        for model in ['gpt-6-astra','gpt-6.1-sol']:
            for effort in ['medium','high','xhigh']:
                selected=execution(model,effort);runner=Runner(self.s);args=runner.command({'executor':selected},self.root)
                self.assertEqual(args[args.index('--model')+1],model);self.assertIn(f'model_reasoning_effort="{effort}"',args)
        self.assertEqual(execution()['model'],'gpt-6-astra')
        with self.assertRaises(ValueError):execution('invalid')
        with self.assertRaises(ValueError):execution(reasoning_effort='ultra')
    def test_awaiting_manual_globally_locks_and_survives_restart(self):
        job,folder=self.job();saved=self.ingest(job,folder,[self.proof(job,folder)])
        self.assertEqual(saved['state'],'awaiting_manual');self.r=Runner(self.s)
        with self.assertRaises(ValueError):self.start([self.s.get('plan')[1]['slot']])
        with self.assertRaises(ValueError):self.s.set_account('Different account')
        with self.assertRaises(ValueError):self.s.edit(job['items'][0],{'title':'不能编辑'})
        with self.assertRaises(ValueError):self.s.update_plan(self.s.get('plan'))
        with self.assertRaises(ValueError):self.r.release(job['id'])
        self.assertEqual(self.s.get('jobs')[0]['state'],'awaiting_manual')
    def test_prepare_cannot_claim_automatic_publication(self):
        job,folder=self.job()
        for state in ['published','scheduled','reviewing']:
            saved=self.ingest(job,folder,[self.proof(job,folder,state)])
            self.assertEqual(saved['state'],'attention');self.assertEqual(saved['results'][0]['state'],'unknown')
            self.assertIn('准备阶段',saved['results'][0]['note'])
    def test_success_requires_fresh_verify_proof_and_unlocks_next(self):
        job,folder=self.job();self.ingest(job,folder,[self.proof(job,folder)])
        verify,attempt=self.verify_job(job);self.assertNotEqual(folder,attempt);self.assertFalse((attempt/'result.json').exists())
        saved=self.ingest(verify,attempt,[self.proof(verify,attempt,'scheduled')]);self.assertEqual(saved['state'],'completed')
        with patch('runner.threading.Thread'):next_job=self.start([self.s.get('plan')[1]['slot']])
        self.assertEqual(next_job['count'],1)
    def test_verify_rejects_wrong_time_account_id_or_old_evidence(self):
        job,folder=self.job();self.ingest(job,folder,[self.proof(job,folder)])
        verify,attempt=self.verify_job(job)
        bad=[{'platform_at':'2000-01-01 00:00'},{'at':'2000-01-01 00:00'},{'account':'wrong'},{'platform_id':'123456'},{'platform_id':''},{'evidence':str(folder/'evidence.png')},{'observed_at':'2000-01-01T00:00:00+08:00'},{'match_basis':'title_only'}]
        for changes in bad:
            saved=self.ingest(verify,attempt,[self.proof(verify,attempt,'published',**changes)]);self.assertEqual(saved['results'][0]['state'],'unknown')
    def test_verified_reviewing_unlocks_without_claiming_publication(self):
        job,folder=self.job();self.ingest(job,folder,[self.proof(job,folder)])
        verify,attempt=self.verify_job(job);saved=self.ingest(verify,attempt,[self.proof(verify,attempt,'reviewing')])
        self.assertEqual(saved['state'],'completed');self.assertIn('尚未确认公开',saved['message'])
        self.assertEqual(next(a for a in self.s.get('assets') if a['id']==job['items'][0])['state'],'reviewing')
        with patch('runner.threading.Thread'):next_job=self.start([self.s.get('plan')[1]['slot']])
        self.assertEqual(next_job['count'],1)
    def test_missing_duplicate_and_incomplete_prepare_are_unknown(self):
        job,folder=self.job()
        for items in [[],[self.proof(job,folder,checks={})],[self.proof(job,folder)]*2]:
            saved=self.ingest(job,folder,items);self.assertEqual(saved['results'][0]['state'],'unknown')
            with self.assertRaises(ValueError):self.r.release(job['id'])
    def test_restart_interrupted_job_is_unknown_and_locked(self):
        job,folder=self.job();self.r=Runner(self.s)
        self.assertEqual(self.s.get('jobs')[0]['state'],'attention')
        self.assertEqual(next(a for a in self.s.get('assets') if a['id']==job['items'][0])['state'],'unknown')
        with self.assertRaises(ValueError):self.start([self.s.get('plan')[1]['slot']])
    def test_release_requires_verified_absence_and_closed_editor(self):
        job,folder=self.job();self.ingest(job,folder,[]);verify,attempt=self.verify_job(job)
        raw=self.proof(verify,attempt,'failed',verified_absent=True,checked_views=list(VERIFY_VIEWS))
        saved=self.ingest(verify,attempt,[raw]);self.assertFalse(saved['results'][0]['verified_absent'])
        with self.assertRaises(ValueError):self.r.release(job['id'])
        saved=self.ingest(verify,attempt,[{**raw,'editor_closed':True}]);self.assertEqual(saved['state'],'verified_absent')
        self.assertEqual(self.r.release(job['id']),{'released':1});self.assertEqual(self.s.get('jobs')[0]['state'],'released')
        self.assertEqual(next(a for a in self.s.get('assets') if a['id']==job['items'][0])['state'],'ready')
    def test_fake_executor_cannot_claim_success_without_result(self):
        job,folder=self.job()
        class FakeProcess:
            def __init__(self,*args,**kw):self.stdin=io.StringIO();self.stdout=io.StringIO('{"type":"item.completed","item":{"type":"agent_message","text":"published"}}\n')
            def wait(self):return 0
        with patch('runner.subprocess.Popen',FakeProcess):self.r.run(job,folder,'prepare')
        self.assertEqual(self.s.get('jobs')[0]['state'],'attention');self.assertIsNone(self.r.active)
    def test_drag_move_replace_revision_and_dedup(self):
        rows=self.plan(count=2);revision=self.s.snapshot()['plan_revision']
        self.s.move_video(rows[0]['slot'],rows[2]['slot'],'after',revision);moved=self.s.get('plan')
        self.assertEqual([r['asset_id'] for r in moved],[rows[i]['asset_id'] for i in [1,2,0]])
        self.assertEqual([r['at'] for r in moved],[r['at'] for r in rows])
        with self.assertRaises(ValueError):self.s.move_video(rows[2]['slot'],rows[0]['slot'],'before',revision)
        assets=self.s.get('assets');alias={**assets[0],'id':'alias'}
        with self.assertRaises(ValueError):self.s.unique_assets([assets[0],alias])
    def test_rearrange_preserves_verified_locked_row_and_occupied_time(self):
        job,folder=self.job();original=self.s.get('plan')[0].copy()
        self.ingest(job,folder,[self.proof(job,folder)]);verify,attempt=self.verify_job(job)
        self.ingest(verify,attempt,[self.proof(verify,attempt,'reviewing')])
        ready=[a['id'] for a in self.s.get('assets') if a['state']=='ready']
        rows=self.s.arrange(ready,original['at'][:10],1)
        self.assertIn(original,rows);self.assertEqual(len(rows),3)
        self.assertEqual(len({r['at'] for r in rows}),3)
        self.assertEqual(next(r for r in rows if r['asset_id']==original['asset_id']),original)
        self.assertTrue(all(r['at']!=original['at'] for r in rows if r['asset_id']!=original['asset_id']))
    def test_empty_inventory_does_not_reseed(self):
        self.s.set('assets',[]);self.s.set('plan',[{'preserved':True}]);self.assertEqual(Store(self.config).get('plan'),[{'preserved':True}])
    def test_database_platform_marker_is_persisted(self):
        self.assertEqual(self.s.get('platform'),'xiaohongshu')
        self.assertEqual(self.s.get('app'),'yl-xiaohongshu-workbench')
        self.assertEqual(Store(self.config).get('assets'),self.s.get('assets'))
    def test_config_platform_required_before_creating_directory(self):
        for platform in [None,'douyin','']:
            target=self.root/('invalid-config-'+str(platform))
            with self.assertRaisesRegex(ValueError,'配置'):Store({**self.config,'platform':platform,'data_dir':str(target)})
            self.assertFalse(target.exists())
    def test_existing_unmarked_or_foreign_database_is_not_changed(self):
        for i,markers in enumerate([{}, {'platform':'douyin'}, {'platform':'xiaohongshu','app':'yl-douyin-workbench'}]):
            target=self.root/f'foreign-{i}';target.mkdir();database=target/'workbench.sqlite3'
            with sqlite3.connect(database) as connection:
                connection.execute('CREATE TABLE kv (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
                connection.executemany('INSERT INTO kv VALUES (?,?)',[(k,json.dumps(v)) for k,v in {'assets':[{'id':'foreign-original'}],**markers}.items()])
            connection.close()
            before=database.read_bytes()
            with self.assertRaisesRegex(ValueError,'数据库'):Store({**self.config,'data_dir':str(target)})
            self.assertEqual(database.read_bytes(),before)
    def test_bad_import_does_not_create_partial_database(self):
        source=self.root/'foreign-plan.json';source.write_text(json.dumps({'platform':'douyin','rows':[]}))
        target=self.root/'bad-import'
        with self.assertRaisesRegex(ValueError,'导入计划'):Store({**self.config,'data_dir':str(target),'import_plan':str(source)})
        self.assertFalse((target/'workbench.sqlite3').exists())
    def test_failed_database_creation_does_not_leave_partial_store(self):
        target=self.root/'failed-create'
        with patch('engine.sqlite3.connect',side_effect=sqlite3.OperationalError('synthetic failure')):
            with self.assertRaises(sqlite3.OperationalError):Store({**self.config,'data_dir':str(target)})
        self.assertFalse((target/'workbench.sqlite3').exists())
        self.assertEqual(Store({**self.config,'data_dir':str(target)}).get('platform'),'xiaohongshu')
    def test_completed_submission_can_refresh_to_published_readonly(self):
        job,folder=self.job();self.ingest(job,folder,[self.proof(job,folder)])
        verify,attempt=self.verify_job(job);self.ingest(verify,attempt,[self.proof(verify,attempt,'reviewing')])
        refreshed,new_attempt=self.verify_job(verify)
        self.assertEqual(refreshed['mode'],'verify');self.assertNotEqual(attempt,new_attempt)
        with self.assertRaises(ValueError):self.start([self.s.get('plan')[1]['slot']])
        saved=self.ingest(refreshed,new_attempt,[self.proof(refreshed,new_attempt,'published')])
        self.assertEqual(saved['state'],'completed');self.assertEqual(saved['results'][0]['state'],'published')
        self.assertEqual(len(self.s.get('jobs')),1)
        self.assertIn('禁止上传、编辑、提交',self.r.prompt(new_attempt,'verify'))
    def test_completed_refresh_without_proof_remains_locked(self):
        job,folder=self.job();self.ingest(job,folder,[self.proof(job,folder)])
        verify,attempt=self.verify_job(job);self.ingest(verify,attempt,[self.proof(verify,attempt,'scheduled')])
        refreshed,new_attempt=self.verify_job(verify);saved=self.ingest(refreshed,new_attempt,[])
        self.assertEqual(saved['state'],'attention');self.assertEqual(saved['results'][0]['state'],'unknown')
        with self.assertRaises(ValueError):self.start([self.s.get('plan')[1]['slot']])
        with self.assertRaises(ValueError):self.r.release(job['id'])
    def test_stale_confirmation_after_caption_edit_rejected_before_job(self):
        rows=self.plan();self.r=Runner(self.s);revision=self.s.preparation_revision()
        self.s.edit(rows[0]['asset_id'],{'caption':'另一标签页修改的正文'})
        with self.assertRaisesRegex(ValueError,'确认'):self.start([rows[0]['slot']],revision=revision)
        self.assertEqual(self.s.get('jobs'),[]);self.assertFalse((self.s.root/'jobs').exists())
    def test_stale_confirmation_after_replacement_rejected_before_job(self):
        rows=self.plan(limit=1);self.r=Runner(self.s);revision=self.s.preparation_revision()
        spare=next(asset for asset in self.s.get('assets') if asset['id']!=rows[0]['asset_id'])
        self.s.replace_video(rows[0]['slot'],spare['id'],self.s.snapshot()['plan_revision'])
        with self.assertRaisesRegex(ValueError,'确认'):self.start([rows[0]['slot']],revision=revision)
        self.assertEqual(self.s.get('jobs'),[]);self.assertFalse((self.s.root/'jobs').exists())
    def test_confirmation_revision_required_and_selection_does_not_stale_it(self):
        rows=self.plan();self.r=Runner(self.s);revision=self.s.snapshot()['preparation_revision']
        with self.assertRaisesRegex(ValueError,'确认'):self.r.start([rows[0]['slot']])
        self.s.select([rows[0]['asset_id']],True)
        self.assertEqual(self.s.preparation_revision(),revision)
        with patch('runner.threading.Thread'):job=self.start([rows[0]['slot']],revision=revision)
        self.assertEqual(job['count'],1)
    def test_http_guard_media_account_and_limits(self):
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        config={**self.config,'port':port};config_file=self.root/'config.json';config_file.write_text(json.dumps(config));base=f'http://127.0.0.1:{port}'
        proc=subprocess.Popen([sys.executable,'-B',str(Path(__file__).with_name('server.py')),'--config',str(config_file)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            for _ in range(50):
                try:
                    with urllib.request.urlopen(base,timeout=.5) as response:html=response.read().decode();break
                except OSError:time.sleep(.05)
            else:self.fail('Local test server did not start')
            token=re.search(r'name="csrf-token" content="([^"]+)"',html)[1]
            headers={'Origin':base,'X-CSRF-Token':token,'Content-Type':'application/json'}
            payload=json.dumps({'account':'must not be saved'}).encode()
            for bad_headers,code in [({**headers,'X-CSRF-Token':'old-service-token'},'csrf_expired'),({**headers,'Origin':'https://foreign.invalid'},'origin_rejected'),({**headers,'Host':'foreign.invalid'},'origin_rejected')]:
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    urllib.request.urlopen(urllib.request.Request(base+'/api/account',data=payload,headers=bad_headers))
                self.assertEqual(denied.exception.code,403)
                self.assertEqual(json.load(denied.exception)['code'],code);denied.exception.close()
                with urllib.request.urlopen(base+'/api/state') as response:self.assertEqual(json.load(response)['account'],self.config['account'])
            with urllib.request.urlopen(base+'/api/session') as response:
                self.assertEqual(json.load(response)['csrf_token'],token)
                self.assertEqual(response.headers['Cache-Control'],'no-store')
                self.assertIsNone(response.headers.get('Access-Control-Allow-Origin'))
            with self.assertRaises(urllib.error.HTTPError) as denied:
                urllib.request.urlopen(urllib.request.Request(base+'/api/session',headers={'Origin':'https://foreign.invalid'}))
            self.assertEqual(denied.exception.code,403);denied.exception.close()
            with urllib.request.urlopen(base+'/api/health') as response:self.assertEqual(json.load(response)['app'],'yl-xiaohongshu-workbench')
            with urllib.request.urlopen(base+'/api/state') as response:self.assertEqual(json.load(response)['limits']['tags'],10)
            asset=self.s.get('assets')[0];request=urllib.request.Request(base+'/media?id='+asset['id'],headers={'Range':'bytes=1-4'})
            with urllib.request.urlopen(request) as response:self.assertEqual(response.status,206);self.assertEqual(response.read(),Path(asset['video']).read_bytes()[1:5])
            payload=json.dumps({'account':'HTTP synthetic account'}).encode()
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(urllib.request.Request(base+'/api/account',data=payload))
            self.assertEqual(error.exception.code,403);error.exception.close()
            with urllib.request.urlopen(urllib.request.Request(base+'/api/account',data=payload,headers=headers)) as response:self.assertEqual(json.load(response)['result']['account'],'HTTP synthetic account')
            with urllib.request.urlopen(base+'/api/times?count=1') as response:self.assertEqual(json.load(response),['10:00'])
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(urllib.request.Request(base+'/api/publish',data=json.dumps({'slots':[]}).encode(),headers=headers))
            self.assertEqual(error.exception.code,400);error.exception.close()
        finally:proc.terminate();proc.communicate(timeout=5)

if __name__=='__main__':unittest.main()
