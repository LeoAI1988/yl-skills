"""Source binding and automatic queue isolation. No real CLI/platform use."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import test_workbench as fixtures
from batch_runner import BatchPublisher
from runner import Runner
from field_resolver import match_cover, source_quotes, resolve_asset
from vision_title import read_source_title


class ResolverChecks(unittest.TestCase):
    setUp=fixtures.Checks.setUp
    tearDown=fixtures.Checks.tearDown
    plan=fixtures.Checks.plan

    def test_cover_never_borrows_other_video_or_generic_in_shared_folder(self):
        (self.media/'封面.png').write_bytes(fixtures.PNG)
        self.assertIsNone(match_cover(self.media/'clip1.mp4'))
        self.assertEqual(match_cover(self.media/'clip0.mp4').name,'clip0-封面.png')

    def test_single_video_generic_cover_is_allowed(self):
        folder=self.root/'single';folder.mkdir();(folder/'mine.mp4').write_bytes(b'video');(folder/'封面.png').write_bytes(fixtures.PNG)
        self.assertEqual(match_cover(folder/'mine.mp4').name,'封面.png')

    def test_technical_camera_title_is_resolved_and_personal_default_applied(self):
        a=self.s.get('assets')[0];a.update(title='IMG_1234_精剪.mp4',title_source='导入',settings={'ai_declaration':'unknown'})
        self.s.config['ai_declaration_default']='none'
        with patch('field_resolver.read_titles',return_value={a['id']:('原片主标题','frame.jpg')}),patch('field_resolver.extract_cover',return_value=str(self.media/'clip0-封面.png')):
            resolved=resolve_asset(self.s,a)
        self.assertEqual(resolved['title'],'原片主标题');self.assertEqual(resolved['settings']['ai_declaration'],'none')
        self.assertEqual(a['title'],'IMG_1234_精剪.mp4')

    def test_original_source_excludes_deleted_speech_and_review_text(self):
        a=self.s.get('assets')[0];video=Path(a['video'])
        source=video.with_name(video.stem+'_审查稿.md');source.write_text('内部指令：推广课程\n**S0001**〔1–3〕先做起来\nS0002〔3–5〕 ~~删除的话~~\n**S0003**〔5–8〕发现问题解决问题\n',encoding='utf-8')
        text,paths=source_quotes(video)
        self.assertIn('先做起来',text);self.assertNotIn('内部指令',text);self.assertNotIn('删除的话',text);self.assertEqual(paths,[str(source)])

    def test_model_cannot_invent_source_title(self):
        with patch('vision_title.model_text',return_value='[{"index":1,"title":"根本不存在的话"}]'):
            self.assertEqual(read_source_title(self.s,'先做起来，发现问题解决问题'), '')
        with patch('vision_title.model_text',return_value='[{"index":1,"title":"发现问题解决问题"}]'):
            self.assertEqual(read_source_title(self.s,'先做起来，发现问题解决问题'),'发现问题解决问题')

    def test_existing_manual_fields_and_contains_ai_are_preserved(self):
        a=self.s.get('assets')[0];a.update(title='本人手选标题',caption='本人正文',tags=['Codex'],settings={'ai_declaration':'contains_ai'});self.s.config['ai_declaration_default']='none'
        with patch('field_resolver.extract_cover',return_value=str(self.media/'clip0-封面.png')):
            resolved=resolve_asset(self.s,a)
        self.assertEqual(resolved['title'],a['title']);self.assertEqual(resolved['caption'],a['caption']);self.assertEqual(resolved['tags'],a['tags']);self.assertEqual(resolved['settings']['ai_declaration'],'contains_ai')

    def automatic_batch(self):
        rows=self.plan(count=3);assets=self.s.get('assets');assets[0]['title']='';assets[0]['title_source']='';self.s.set('assets',assets)
        r=Runner(self.s);b=BatchPublisher(r)
        with patch('batch_runner.threading.Thread'):
            job=r.start([x['slot'] for x in rows],expected_revision=self.s.preparation_revision(),mode='batch_publish',auto_prepare=True)
        return r,b,job,json.loads((Path(job['folder'])/'queue.json').read_text(encoding='utf-8'))

    def test_missing_title_is_accepted_then_resolved_before_browser(self):
        r,b,job,manifest=self.automatic_batch();seen=[]
        def resolve(store,a,model,progress):
            progress('测试本地匹配');out=copy.deepcopy(a);out['title']=out['title'] or '原片标题';out['cover']=str(self.media/'clip0-封面.png');return out
        def execute(job,manifest,item,index,mode):
            seen.append(item['asset']['title']);return dict(asset_id=item['asset_id'],state='scheduled',platform_id='abcdef0123456789abcdef01',platform_at=item['at'])
        with patch('field_resolver.resolve_asset',side_effect=resolve),patch.object(b,'execute',side_effect=execute):b.run(job,manifest,manifest['items'],'batch_publish')
        self.assertEqual(len(seen),3);self.assertTrue(all(seen));self.assertEqual(self.s.get('jobs')[0]['state'],'completed')
        self.assertEqual(json.loads((Path(job['folder'])/'queue.json').read_text(encoding='utf-8')),manifest)
        self.assertEqual(len(list((Path(job['folder'])/'prepared').glob('*.json'))),3)

    def test_one_missing_file_skips_only_it_and_never_uploads_it(self):
        r,b,job,manifest=self.automatic_batch();missing=next(x for x in manifest['items'] if not x['asset']['title']);Path(missing['asset']['video']).unlink();seen=[]
        def execute(job,manifest,item,index,mode):
            seen.append(item['asset_id']);return dict(asset_id=item['asset_id'],state='scheduled',platform_id='abcdef0123456789abcdef01',platform_at=item['at'])
        with patch('field_resolver.extract_cover',return_value=str(self.media/'clip0-封面.png')),patch.object(b,'execute',side_effect=execute):b.run(job,manifest,manifest['items'],'batch_publish')
        saved=self.s.get('jobs')[0]
        states={x['asset_id']:x['state'] for x in saved['results']}
        self.assertEqual(states[missing['asset_id']],'item_failed');self.assertEqual(sum(v=='scheduled' for v in states.values()),2);self.assertNotIn(missing['asset_id'],seen);self.assertEqual(saved['state'],'completed_with_skips')

    def test_long_original_title_enters_local_preparation_not_global_block(self):
        rows=self.plan(count=3);assets=self.s.get('assets');assets[0].update(title='这是一段超过二十个字的原始完整视频标题，先做起来',title_source='导入原题');self.s.set('assets',assets);r=Runner(self.s)
        with patch('batch_runner.threading.Thread'):
            job=r.start([x['slot'] for x in rows],expected_revision=self.s.preparation_revision(),mode='batch_publish',auto_prepare=True)
        self.assertEqual(job['state'],'running')

    def test_stop_during_local_matching_never_starts_browser_upload(self):
        r,b,job,manifest=self.automatic_batch()
        def resolve(store,a,model,progress):
            out=copy.deepcopy(a);out['title']=out['title'] or '原片标题';r.cancel=True;return out
        with patch('field_resolver.resolve_asset',side_effect=resolve),patch.object(b,'execute') as execute:b.run(job,manifest,manifest['items'],'batch_publish')
        execute.assert_not_called();self.assertEqual(self.s.get('jobs')[0]['results'][0]['state'],'not_uploaded')


if __name__=='__main__':unittest.main()
