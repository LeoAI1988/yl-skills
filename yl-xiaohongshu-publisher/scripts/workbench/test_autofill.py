import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from engine import Store
from dedup import signature
from autofill import prepare


class AutoFillTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.s=Store(dict(platform='xiaohongshu',data_dir=str(self.root/'data'),tag_pool=['AI','知识库'],ffprobe='missing'))
        p=self.root/'01_AI知识库_1.15倍.mp4';p.write_bytes(b'clip')
        self.a=dict(id='a',video=str(p),name=p.name,title='',caption='',tags=[],settings={},state='ready',cover='')
        self.s.set('assets',[self.a]);self.s.set('plan',[dict(asset_id='a',slot='one',at='2030-01-01 12:00')])

    def tearDown(self): self.tmp.cleanup()
    def run_prepare(self,**kw):return prepare(self.s,['a'],self.s.preparation_revision(),**kw)

    def test_filename_title_defaults_tags_but_no_ai_guess(self):
        result=self.run_prepare();a=self.s.get('assets')[0]
        self.assertEqual(a['title'],'AI知识库');self.assertEqual(set(a['tags']),{'知识库','AI'})
        self.assertEqual(a['settings']['visibility'],'公开');self.assertEqual(result['need_ai'],['a'])
        self.assertEqual(self.s.get('jobs'),[]);self.assertEqual(self.s.get('plan')[0]['at'],'2030-01-01 12:00')

    def test_verified_source_and_batch_confirmation_remembered(self):
        self.s.set('preparation_sources',{'a':dict(signature=signature(self.a['video']),title='原话标题',title_source='已核对成片顶部')})
        self.run_prepare(ai='none');a=self.s.get('assets')[0]
        self.assertEqual(a['title'],'原话标题');self.assertEqual(a['settings']['ai_declaration'],'none')
        self.assertEqual(self.run_prepare()['need_ai'],[])

    def test_existing_user_fields_preserved(self):
        self.a.update(title='用户标题',caption='用户正文',tags=['手选'],settings=dict(visibility='仅自己可见',ai_declaration='contains_ai'))
        self.s.set('assets',[self.a]);self.run_prepare(ai='none');a=self.s.get('assets')[0]
        self.assertEqual(a['title'],'用户标题');self.assertEqual(a['caption'],'用户正文');self.assertEqual(a['tags'],['手选'])
        self.assertEqual(a['settings']['ai_declaration'],'contains_ai');self.assertEqual(a['settings']['visibility'],'仅自己可见')

    def test_stale_and_locked_rejected(self):
        with self.assertRaises(ValueError):prepare(self.s,['a'],'old')
        self.a['state']='scheduled';self.s.set('assets',[self.a])
        with self.assertRaises(ValueError):self.run_prepare()

    def test_changed_source_not_reused(self):
        self.s.set('preparation_sources',{'a':dict(signature=['old'],title='旧标题',ai_declaration='none')})
        self.run_prepare();self.assertEqual(self.s.get('assets')[0]['title'],'AI知识库')
        self.assertEqual(self.s.get('assets')[0]['settings']['ai_declaration'],'unknown')

    def test_unknown_camera_name_not_title_and_no_audit_caption(self):
        p=self.root/'IMG_1234_重剪.mp4';p.write_bytes(b'clip')
        self.a['video']=str(p);self.a['body']='内部审查报告';self.s.set('assets',[self.a])
        result=self.run_prepare();self.assertEqual(len(result['unresolved']),1)
        self.assertEqual(self.s.get('assets')[0]['caption'],'')

    def test_file_change_aborts_commit(self):
        with patch('autofill.signature',side_effect=[['before'],['before'],['after']]):
            with self.assertRaisesRegex(ValueError,'变化'):self.run_prepare()
        self.assertEqual(self.s.get('assets')[0]['title'],'')

    def test_long_title_complete_clause_respects_limit(self):
        self.a['title']='这是一段非常非常长的原始视频标题说明并且还在继续超过二十个字，知识库怎么用'
        self.s.set('assets',[self.a]);self.run_prepare()
        self.assertEqual(self.s.get('assets')[0]['title'],'知识库怎么用')

    def test_model_reads_video_title_without_manual_fields(self):
        p=self.root/'IMG_1234_精剪.mp4';p.write_bytes(b'clip')
        self.a['video']=str(p);self.a['name']=p.name;self.s.set('assets',[self.a])
        self.s.config['ai_declaration_default']='none'
        with patch('autofill.read_titles',return_value={'a':('从画面读取的真实标题','frame.png')}) as vision:
            result=self.run_prepare()
        a=self.s.get('assets')[0]
        self.assertEqual(a['title'],'从画面读取的真实标题')
        self.assertEqual(a['settings']['ai_declaration'],'none')
        self.assertEqual(result['unresolved'],[])
        self.assertEqual(result['need_ai'],[])
        self.assertEqual(vision.call_count,1)


if __name__=='__main__': unittest.main()
