"""Offline acceptance tests. All mutable fixtures stay in temporary directories."""
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'yl-knowledge/scripts'))
sys.path.insert(0,str(ROOT/'yl-media/scripts'))
sys.path.insert(0,str(ROOT/'yl-knowledge-sync/scripts'))
from knowledge import init, load_profile, register, record, inspect, sha, state_load, inside
from ranking import rank
import getnote_sync
spec=importlib.util.spec_from_file_location('installer_test',ROOT/'install.py')
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)

class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='yl-knowledge-test-')
        self.base=Path(self.temp.name);self.profile=self.base/'config/profile.json'
        self.root=self.base/'library';init(self.profile,self.root,'new')
        self.cfg,self.root=load_profile(self.profile)
        self.source=self.root/'source.md';self.source.write_text('我的观点。\n新的表达。\n',encoding='utf-8')
        self.atom=self.root/'05_知识原子/条目/OPI-test.md';self.atom.write_text('我的观点。',encoding='utf-8')
        self.receipt={'source_sha256':sha(self.source.read_bytes()),'ownership':'user_owned','coverage':[[1,2]],
                      'classification_reason':'本人原文','dedup_reason':'已检索现有对象无同义项',
                      'atoms':[{'path':self.atom.relative_to(self.root).as_posix(),'quotes':['我的观点。']}],
                      'expressions':[],'expression_reason':'无独立新表达','links':['01_我的思想体系/README.md'],
                      'organization_reason':'已归入分支','disposition':'distilled','note':'全文已读'}
    def tearDown(self):self.temp.cleanup()
    def test_incremental_resume_and_source_versions(self):
        self.assertEqual(register(self.cfg,self.root,self.source,'s1','local')['status'],'needs_semantic_processing')
        self.assertEqual(inspect(self.cfg,self.root)['status'],'INCOMPLETE')
        register(self.cfg,self.root,self.source,'s1','local')
        self.assertEqual(len(state_load(self.cfg,self.root)['sources']),1)
        record(self.cfg,self.root,'s1',self.receipt)
        self.assertEqual(inspect(self.cfg,self.root)['status'],'PASS')
        original=state_load(self.cfg,self.root)['sources']['s1']['snapshot']
        self.source.write_text('新版本。',encoding='utf-8')
        self.assertEqual(inspect(self.cfg,self.root)['status'],'INCOMPLETE')
        register(self.cfg,self.root,self.source,'s1','local')
        self.assertEqual((self.root/original).read_text(encoding='utf-8'),'我的观点。\n新的表达。\n')
        self.assertEqual(len(state_load(self.cfg,self.root)['sources']['s1']['history']),1)
    def test_quote_and_full_coverage_required(self):
        register(self.cfg,self.root,self.source,'s1','local')
        bad=copy.deepcopy(self.receipt);bad['atoms'][0]['quotes']=['我的观点，不是原话。']
        with self.assertRaises(ValueError):record(self.cfg,self.root,'s1',bad)
        bad=copy.deepcopy(self.receipt);bad['coverage']=[[1,1]]
        with self.assertRaises(ValueError):record(self.cfg,self.root,'s1',bad)
        self.assertEqual(inspect(self.cfg,self.root)['status'],'INCOMPLETE')
    def test_third_party_cannot_become_personal_atom(self):
        register(self.cfg,self.root,self.source,'s1','local')
        bad=copy.deepcopy(self.receipt);bad['ownership']='third_party'
        with self.assertRaises(ValueError):record(self.cfg,self.root,'s1',bad)
    def test_artifact_drift_reopens_review(self):
        register(self.cfg,self.root,self.source,'s1','local');record(self.cfg,self.root,'s1',self.receipt)
        self.atom.write_text('我的观点。\n变化',encoding='utf-8')
        self.assertEqual(inspect(self.cfg,self.root)['status'],'INCOMPLETE')
    def test_mixed_source_only_quotes_reviewed_own_lines(self):
        register(self.cfg,self.root,self.source,'s1','local')
        mixed=copy.deepcopy(self.receipt);mixed['ownership']='mixed'
        with self.assertRaises(ValueError):record(self.cfg,self.root,'s1',mixed)
        mixed['owned_spans']=[[2,2]]
        with self.assertRaises(ValueError):record(self.cfg,self.root,'s1',mixed)
        mixed['owned_spans']=[[1,1]]
        record(self.cfg,self.root,'s1',mixed)
        self.assertEqual(inspect(self.cfg,self.root)['status'],'PASS')
    def test_path_escape_and_profile_overwrite_refused(self):
        before=self.profile.read_bytes()
        with self.assertRaises(ValueError):inside(self.root,'../outside.md')
        with self.assertRaises(ValueError):init(self.profile,self.base/'other','new')
        self.assertEqual(self.profile.read_bytes(),before)
    def test_getnote_mock_pagination_and_primary(self):
        self.cfg['sources']={'getnote':{'libraries':['笔记']}}
        calls=[]
        def request(endpoint,params):
            calls.append((endpoint,params))
            if endpoint.endswith('knowledge/list'):return {'topics':[{'id':7,'name':'笔记'}],'has_more':False}
            if endpoint.endswith('knowledge/notes'):
                if params['page']==1:return {'notes':[{'id':9223372036854775000,'updated_at':'v1'}],'has_more':True}
                return {'notes':[],'has_more':False}
            return {'note':{'audio':{'original':'真正原话'},'content':'不能替代的摘要','title':'标题'}}
        with patch.object(getnote_sync,'request',request):
            result=getnote_sync.sync(self.cfg,self.root)
            self.assertEqual(result['status'],'needs_semantic_processing')
            self.assertEqual(result['changed'],1)
            second=getnote_sync.sync(self.cfg,self.root)
            self.assertEqual(second['changed'],0)
        row=state_load(self.cfg,self.root)['sources']['getnote:9223372036854775000']
        self.assertEqual((self.root/row['snapshot']).read_text(encoding='utf-8'),'真正原话')
        self.assertEqual(inspect(self.cfg,self.root)['status'],'INCOMPLETE')
    def test_rank_uses_adopted_percentile_weights(self):
        rows=[{'完播率':10,'平均播放时长':5,'关注':1000,'播放':1000000,'快速划走率':80}, {'完播率':20,'平均播放时长':10,'关注':2,'播放':10,'快速划走率':20}]
        out=rank(rows)
        self.assertEqual(out[0]['综合评分'],75)
        self.assertEqual(out[1]['综合评分'],25)
        self.assertNotIn('综合评分',rows[0])
    def test_rank_missing_zero_ties_and_units(self):
        out=rank([{'完播率':0,'平均播放时长':0,'关注':0,'播放':0,'快速划走率':100}, {'完播率':0,'平均播放时长':0,'关注':'','播放':0,'快速划走率':100}])
        self.assertEqual(out[0]['综合评分'],0);self.assertIsNone(out[1]['综合评分'])
        with self.assertRaises(ValueError):rank([{'完播率':101}])
        with self.assertRaises(ValueError):rank([{'关注':float('nan')}])

class InstallerTests(unittest.TestCase):
    def test_overlapping_host_mapping_rejected_without_writes(self):
        sys.path.insert(0,str(ROOT/'yl-skill-sync/scripts'))
        import sync
        with tempfile.TemporaryDirectory(prefix='yl-map-scope-') as tmp:
            base=Path(tmp);target=base/'codex/skills';target.mkdir(parents=True)
            (target/'.yl-cluster-install.json').write_text(json.dumps({'skills':{}}),encoding='utf-8')
            destination=target/'nested'
            with self.assertRaises(ValueError):sync.map_hosts(target,[destination])
            self.assertFalse(destination.exists())
    def test_upgrade_profile_and_local_edits(self):
        with tempfile.TemporaryDirectory(prefix='yl-install-upgrade-') as tmp:
            base=Path(tmp);source=base/'release';target=base/'codex/skills';member=source/'yl-demo'
            member.mkdir(parents=True);(member/'SKILL.md').write_text('version1',encoding='utf-8')
            def manifest(version):
                (source/'cluster.json').write_text(json.dumps({'version':version,'skills':[{'name':'yl-demo','files':installer.contents(member)}]}),encoding='utf-8')
            manifest('1.0.0')
            profile=base/'personal/profile.json';profile.parent.mkdir();profile.write_text('{"user":"retained"}',encoding='utf-8');before=profile.read_bytes()
            installer.install(source,target,dry_run=True);self.assertFalse(target.exists())
            installer.install(source,target)
            (member/'SKILL.md').write_text('version2',encoding='utf-8');manifest('2.0.0')
            with self.assertRaises(ValueError):installer.install(source,target)
            installer.install(source,target,upgrade=True)
            self.assertEqual((target/'yl-demo/SKILL.md').read_text(encoding='utf-8'),'version2')
            self.assertEqual(profile.read_bytes(),before)
            (target/'yl-demo/SKILL.md').write_text('local-edit',encoding='utf-8')
            (member/'SKILL.md').write_text('version3',encoding='utf-8');manifest('3.0.0')
            with self.assertRaises(ValueError):installer.install(source,target,upgrade=True)
            self.assertEqual((target/'yl-demo/SKILL.md').read_text(encoding='utf-8'),'local-edit')

if __name__=='__main__':unittest.main(verbosity=2)
