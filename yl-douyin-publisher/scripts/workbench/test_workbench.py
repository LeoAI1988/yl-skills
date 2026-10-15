"""Behavior checks use temporary synthetic files and never contact Douyin."""
import datetime as dt
import io
import json
import tempfile
import unittest
import socket
import subprocess
import time
import urllib.request
import urllib.error
import re
from pathlib import Path
from unittest.mock import patch
import engine
from engine import Store, times, matching_tags, TZ
from runner import Runner, execution

class Checks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.config={'data_dir':str(self.root/'data'),'tag_pool':['AI','人工智能','Codex','OpenAI','智能体','知识库','短视频'],'codex':__import__('sys').executable,'ffprobe':'missing'}
        self.s=Store(self.config);self.media=self.root/'videos';self.media.mkdir()
        for i in range(3):(self.media/f'clip{i}.mp4').write_bytes((str(i)*30).encode())
        (self.media/'clip0-封面.png').write_bytes(b'cover');self.s.scan(str(self.media))
    def tearDown(self):self.tmp.cleanup()
    def test_spacing(self):
        for n in range(2,14):
            values=times(n);mins=[int(x[:2])*60+int(x[3:]) for x in values]
            self.assertEqual((values[0],values[-1],len(set(values))),('07:30','21:00',n))
            self.assertTrue(all(m%10==0 for m in mins))
            gaps=[b-a for a,b in zip(mins,mins[1:])];self.assertLessEqual(max(gaps)-min(gaps),10)
        self.assertEqual(times(7),['07:30','09:50','12:00','14:20','16:30','18:50','21:00'])
        self.assertEqual(times(6,'08:00','20:30'),['08:00','10:30','13:00','15:30','18:00','20:30'])
        for invalid in (1,14):
            with self.assertRaises(ValueError):times(invalid)
    def test_custom_windows_use_ten_minute_grid_without_collisions(self):
        for n in range(2,14):
            for steps in range(n-1,144):
                end=steps*10;values=times(n,'00:00',f'{end//60:02}:{end%60:02}')
                mins=[int(x[:2])*60+int(x[3:]) for x in values];gaps=[b-a for a,b in zip(mins,mins[1:])]
                self.assertEqual((mins[0],mins[-1],len(set(mins))),(0,end,n))
                self.assertTrue(all(m%10==0 for m in mins));self.assertGreaterEqual(min(gaps),10)
                self.assertLessEqual(max(gaps)-min(gaps),10)
                self.assertTrue(all(abs(m-end*i/(n-1))<=5.001 for i,m in enumerate(mins)))
    def test_invalid_custom_window_does_not_change_plan(self):
        original=self.plan();preferences=self.s.get('preferences')
        for start,end,count in [('08:00','08:00',2),('21:00','08:00',2),('08:05','21:00',3),('24:00','23:50',2),('08:00','08:10',3),('bad','21:00',2)]:
            with self.subTest(start=start,end=end,count=count):
                with self.assertRaises(ValueError):self.s.arrange([a['id'] for a in self.s.get('assets')],original[0]['at'][:10],count,start,end)
                self.assertEqual(self.s.get('plan'),original);self.assertEqual(self.s.get('preferences'),preferences)
    def test_custom_window_persists_and_is_independent_of_count(self):
        ids=[a['id'] for a in self.s.get('assets')];day=(engine.now().date()+dt.timedelta(days=1)).isoformat()
        rows=self.s.arrange(ids,day,3,'08:10','20:40')
        self.assertEqual([r['at'][11:] for r in rows],['08:10','14:30','20:40'])
        reloaded=Store(self.config);pref=reloaded.snapshot()['preferences']
        self.assertEqual((pref['start_time'],pref['end_time']),('08:10','20:40'))
        rows=reloaded.arrange(ids,day,2)
        self.assertEqual([r['at'][11:] for r in rows],['08:10','20:40','08:10'])
    def test_legacy_preferences_read_without_changing_existing_plan(self):
        original=self.plan();legacy={'count':6,'start_date':original[0]['at'][:10]};self.s.set('preferences',legacy)
        snap=self.s.snapshot();self.assertEqual((snap['preferences']['start_time'],snap['preferences']['end_time']),('08:00','20:30'))
        self.assertEqual(snap['plan'],original);self.assertEqual(self.s.get('preferences'),legacy)
    def test_inventory_duplicates_and_recordings(self):
        self.assertEqual(len(self.s.get('assets')),3)
        (self.media/'copy.mp4').write_bytes((self.media/'clip0.mp4').read_bytes())
        self.s.scan(str(self.media));self.s.scan(str(self.media))
        a=self.s.get('assets');self.assertEqual(len(a),4);self.assertEqual(sum(x['state']=='excluded' for x in a),1)
        self.assertEqual(sum(x['state']=='ready' for x in a),3)
        self.assertTrue(next(x for x in a if x['name']=='clip0.mp4')['cover'].endswith('clip0-封面.png'))
        self.assertFalse(next(x for x in a if x['name']=='clip1.mp4')['cover'])
    def test_persistence_and_empty_inventory(self):
        a=self.s.get('assets')[0];self.s.edit(a['id'],{'title':'Changed','selected':True})
        self.assertEqual(Store(self.config).get('assets')[0]['title'],'Changed')
        self.s.set('assets',[]);self.s.set('plan',[{'preserved':True}]);self.assertEqual(Store(self.config).get('plan'),[{'preserved':True}])
    def test_schedule_skips_past_orders_swaps(self):
        assets=self.s.get('assets')
        for i,a in enumerate(assets):a['date']=f'2026-01-{3-i:02}'
        self.s.set('assets',assets)
        with patch.object(engine,'now',return_value=dt.datetime(2026,1,10,9,30,tzinfo=TZ)):
            rows=self.s.arrange([a['id'] for a in assets],'2026-01-10',7)
        self.assertEqual(rows[0]['at'],'2026-01-10 12:00');self.assertEqual(rows[0]['asset_id'],assets[-1]['id'])
        rows[0]['asset_id'],rows[1]['asset_id']=rows[1]['asset_id'],rows[0]['asset_id'];self.s.update_plan(rows)
        invalid=[dict(r) for r in rows];invalid[1]['asset_id']=invalid[0]['asset_id']
        with self.assertRaises(ValueError):self.s.update_plan(invalid)
    def job(self,model=None,reasoning_effort=None):
        ids=[a['id'] for a in self.s.get('assets')];rows=self.s.arrange(ids,(engine.now().date()+dt.timedelta(days=1)).isoformat(),8)
        self.r=Runner(self.s)
        with patch('runner.threading.Thread'):
            j=self.r.start([r['slot'] for r in rows],model,reasoning_effort)
        return j,Path(j['folder'])
    def test_model_selection_reaches_cli_and_frozen_manifest(self):
        self.assertEqual(execution(),{'driver':'Codex','model':'gpt-6-astra','reasoning_effort':'high'})
        j,f=self.job('gpt-6.1-sol')
        self.assertEqual(json.loads((f/'queue.json').read_text())['executor']['model'],'gpt-6.1-sol')
        args=self.r.command(j,f)
        self.assertEqual(args[args.index('--model')+1],'gpt-6.1-sol')
        self.assertEqual(args[args.index('-c')+1],'model_reasoning_effort="high"')
        default_args=self.r.command({},f)
        self.assertEqual(default_args[default_args.index('--model')+1],'gpt-6-astra')
        with self.assertRaises(ValueError):execution('unknown-model')
    def test_reasoning_levels_reach_cli_and_manifest(self):
        for model in ['gpt-6-astra','gpt-6.1-sol']:
            for effort in ['medium','high','xhigh']:
                with self.subTest(model=model,effort=effort):
                    j,f=self.job(model,effort)
                    self.assertEqual(json.loads((f/'queue.json').read_text())['executor'],execution(model,effort))
                    args=self.r.command(j,f)
                    self.assertEqual(args[args.index('-c')+1],f'model_reasoning_effort="{effort}"')
                    assets=self.s.get('assets')
                    for a in assets:a['state']='ready'
                    self.s.set('assets',assets);self.s.set('jobs',[])
        with self.assertRaises(ValueError):execution(reasoning_effort='ultra')
    def plan(self,count=2,limit=None):
        ids=[a['id'] for a in self.s.get('assets')][:limit]
        return self.s.arrange(ids,(engine.now().date()+dt.timedelta(days=1)).isoformat(),count)
    def test_drag_inserts_and_preserves_times_across_days(self):
        original=self.plan();rev=self.s.snapshot()['plan_revision']
        self.s.move_video(original[0]['slot'],original[2]['slot'],'after',rev)
        moved=self.s.get('plan')
        self.assertEqual([r['asset_id'] for r in moved],[original[i]['asset_id'] for i in [1,2,0]])
        self.assertEqual([(r['slot'],r['at']) for r in moved],[(r['slot'],r['at']) for r in original])
        self.assertEqual(len({r['asset_id'] for r in moved}),3)
        self.s.move_video(moved[2]['slot'],moved[0]['slot'],'before',self.s.snapshot()['plan_revision'])
        self.assertEqual(self.s.get('plan'),original)
        self.assertEqual(Store(self.config).get('plan'),original)
    def test_move_keeps_locked_video_fixed(self):
        original=self.plan();assets=self.s.get('assets')
        next(a for a in assets if a['id']==original[1]['asset_id'])['state']='scheduled'
        self.s.set('assets',assets);rev=self.s.snapshot()['plan_revision']
        with self.assertRaises(ValueError):self.s.move_video(original[1]['slot'],original[0]['slot'],'before',rev)
        self.s.move_video(original[0]['slot'],original[2]['slot'],'after',rev)
        self.assertEqual(self.s.get('plan')[1],original[1])
    def test_replace_rejects_used_and_accepts_unused(self):
        original=self.plan(limit=2);rev=self.s.snapshot()['plan_revision']
        with self.assertRaises(ValueError):self.s.replace_video(original[0]['slot'],original[1]['asset_id'],rev)
        self.assertEqual(self.s.get('plan'),original)
        spare=next(a for a in self.s.get('assets') if a['id'] not in {r['asset_id'] for r in original})
        self.s.replace_video(original[0]['slot'],spare['id'],rev)
        self.assertEqual(self.s.get('plan')[0],{**original[0],'asset_id':spare['id']})
    def test_stale_revision_rejects_move_and_replace(self):
        original=self.plan();rev=self.s.snapshot()['plan_revision']
        self.s.move_video(original[0]['slot'],original[2]['slot'],'after',rev)
        saved=self.s.get('plan')
        with self.assertRaises(ValueError):self.s.move_video(original[2]['slot'],original[0]['slot'],'before',rev)
        with self.assertRaises(ValueError):self.s.replace_video(original[0]['slot'],saved[0]['asset_id'],rev)
        self.assertEqual(self.s.get('plan'),saved)
    def test_duplicate_paths_and_hashes_are_rejected(self):
        assets=self.s.get('assets');alias={**assets[0],'id':'other-id'}
        self.s.set('assets',assets+[alias])
        with self.assertRaises(ValueError):self.s.arrange([assets[0]['id'],alias['id']],(engine.now().date()+dt.timedelta(days=1)).isoformat(),2)
        for a in assets:a['title']='同一文案的不同录制'
        self.s.unique_assets(assets)
        assets[0]['sha256']=assets[1]['sha256']='same-content'
        with self.assertRaises(ValueError):self.s.unique_assets(assets)
    def test_locked_and_evidence_time_validation(self):
        j,f=self.job()
        with self.assertRaises(ValueError):self.r.start([r['slot'] for r in self.s.get('plan')])
        with self.assertRaises(ValueError):self.s.edit(j['items'][0],{'title':'no'})
        m=json.loads((f/'queue.json').read_text());e=f/'e.png';e.write_bytes(b'image')
        items=[dict(asset_id=x['asset_id'],state='scheduled',at=x['at'],evidence=str(e),platform_id='123456') for x in m['items']]
        items[0]['at']='2000-01-01 12:00';items[1]['evidence']=str(self.media/'clip0-封面.png')
        (f/'result.json').write_text(json.dumps({'items':items}));self.r.ingest(j,f,True)
        states={a['id']:a['state'] for a in self.s.get('assets')}
        self.assertEqual([states[x['asset_id']] for x in m['items']],['unknown','unknown','scheduled'])
    def test_duplicate_result_is_unknown(self):
        j,f=self.job();x=json.loads((f/'queue.json').read_text())['items'][0];e=f/'e.png';e.write_bytes(b'x')
        item=dict(asset_id=x['asset_id'],at=x['at'],state='scheduled',evidence=str(e))
        (f/'result.json').write_text(json.dumps({'items':[item,item]}));self.r.ingest(j,f,True)
        self.assertTrue(all(a['state']=='unknown' for a in self.s.get('assets')))
    def test_restart_requires_verification(self):
        j,f=self.job();Runner(self.s)
        self.assertEqual(self.s.get('jobs')[0]['state'],'attention');self.assertTrue(all(a['state']=='unknown' for a in self.s.get('assets')))
    def test_executor_completion_requires_backend_results(self):
        j,f=self.job();manifest=json.loads((f/'queue.json').read_text());proof=f/'proof.png';proof.write_bytes(b'image')
        class FakeProcess:
            def __init__(self,*args,**kw):self.stdin=io.StringIO();self.stdout=io.StringIO('{"type":"item.completed","item":{"type":"agent_message","text":"fixture"}}\n')
            def wait(self):
                (f/'result.json').write_text(json.dumps({'items':[dict(asset_id=r['asset_id'],state='scheduled',at=r['at'],evidence=str(proof)) for r in manifest['items']]}));return 0
        with patch('runner.subprocess.Popen',FakeProcess):self.r.run(j,f)
        self.assertEqual(self.s.get('jobs')[0]['state'],'completed');self.assertEqual(len(self.s.get('jobs')[0]['results']),3)
    def test_missing_results_never_success(self):
        j,f=self.job();self.r.ingest(j,f,True)
        self.assertTrue(all(a['state']=='unknown' for a in self.s.get('assets')))
        self.r.active=None
        with self.assertRaises(ValueError):self.r.release(j['id'])
    def test_tags(self):
        tags=matching_tags('Codex自动化','',self.config['tag_pool'],'x');self.assertEqual(len(set(tags)),5);self.assertIn('Codex',tags)
    def test_http_media_and_csrf(self):
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        config={**self.config,'port':port};path=self.root/'config.json';path.write_text(json.dumps(config));base=f'http://127.0.0.1:{port}'
        proc=subprocess.Popen([__import__('sys').executable,'-B',str(Path(__file__).with_name('server.py')),'--config',str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            for _ in range(50):
                try:
                    with urllib.request.urlopen(base,timeout=.5) as r:html=r.read().decode();break
                except OSError:time.sleep(.05)
            else:self.fail('Local server did not start')
            token=re.search(r'name="csrf-token" content="([^"]+)"',html)[1];a=self.s.get('assets')[0]
            req=urllib.request.Request(base+'/media?id='+a['id'],headers={'Range':'bytes=1-4'})
            with urllib.request.urlopen(req) as r:self.assertEqual(r.status,206);self.assertEqual(r.read(),Path(a['video']).read_bytes()[1:5])
            payload=json.dumps({'ids':[a['id']],'selected':True}).encode()
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(urllib.request.Request(base+'/api/select',data=payload))
            self.assertEqual(error.exception.code,403)
            error.exception.close()
            req=urllib.request.Request(base+'/api/select',data=payload,headers={'Origin':base,'X-CSRF-Token':token,'Content-Type':'application/json'})
            with urllib.request.urlopen(req) as r:self.assertEqual(r.status,200)
            self.assertTrue(self.s.get('assets')[0]['selected'])
            before=self.s.get('plan')
            with urllib.request.urlopen(base+'/api/times?count=3&start_time=08:10&end_time=10:50') as r:self.assertEqual(json.load(r),['08:10','09:30','10:50'])
            self.assertEqual(self.s.get('plan'),before)
            payload=json.dumps({'ids':[a['id'] for a in self.s.get('assets')],'date':(engine.now().date()+dt.timedelta(days=1)).isoformat(),'count':3,'start_time':'08:10','end_time':'10:50'}).encode()
            req=urllib.request.Request(base+'/api/arrange',data=payload,headers={'Origin':base,'X-CSRF-Token':token,'Content-Type':'application/json'})
            with urllib.request.urlopen(req) as r:rows=json.load(r)['result']
            self.assertEqual([r['at'][11:] for r in rows],['08:10','09:30','10:50'])
            self.assertEqual(self.s.get('preferences')['start_time'],'08:10')
        finally:proc.terminate();proc.communicate(timeout=5)

if __name__=='__main__':unittest.main()
