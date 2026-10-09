"""Behavioral source-fidelity tests; fixtures are synthetic and outside the core."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('retrieval', Path(__file__).resolve().parents[1]/'yl-knowledge-search/scripts/retrieval.py')
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='yl-retrieval-test-')
        self.root = Path(self.temp.name)
        self.path = self.root/'source.md'
        self.text = '---\nauthor: user_owned\n---\n# 测试\n\n## 原始内容\n\n我把经验比作一座工厂，而不是只买一把锤子。\n\n只有这种比较的前因和后果一起保留，表达才完整。\n\n## AI总结\n\n不应冒充原话的摘要哨兵。\n'
        self.path.write_text(self.text, encoding='utf-8')
        self.row = {'source_id':'s1','path':str(self.path),'title':'测试',
                    'kind':'source','include_sections':['原始内容'],'authorship':'user_owned',
                    'review_status':'raw_needs_cleanup'}
        self.manifest = self.root/'sources.json'
        self.cfg = {'manifest':str(self.manifest),'index_dir':str(self.root/'index')}
        self.profile = {'knowledge_root':str(self.root),'source_roots':[], 'excluded_source_ids':[]}
        self.out = self.root/'index'
        self.write_manifest()

    def tearDown(self):
        self.temp.cleanup()

    def write_manifest(self):
        self.manifest.write_text(json.dumps({'sources':[self.row]},ensure_ascii=False),encoding='utf-8')

    def build(self):
        return r.index(self.profile,self.cfg,self.root,self.out)

    def search(self, q):
        return r.search(self.profile,self.cfg,self.root,self.out,q,mode='text')

    def test_original_not_metadata_or_summary(self):
        self.build()
        hit = self.search('一座工厂')['results'][0]
        self.assertEqual(hit['lines'],[8,8])
        self.assertEqual(hit['passage'],self.text.splitlines()[7])
        self.assertFalse(hit['quote_ready'])
        self.assertEqual(self.search('摘要哨兵')['results'],[])
        self.assertEqual(self.search('user_owned')['results'],[])

    def test_unatomized_full_text_and_incremental(self):
        self.assertEqual(self.build()['changed'],1)
        self.assertEqual(self.build()['unchanged'],1)
        self.assertTrue(self.search('前因和后果')['results'])
        self.path.write_text(self.text.replace('一座工厂','一个港口'),encoding='utf-8')
        self.assertEqual(self.build()['changed'],1)
        self.assertTrue(self.search('一个港口')['results'])
        self.assertEqual(self.search('一座工厂')['results'],[])

    def test_stale_index_never_returns_old_words(self):
        self.build()
        self.path.write_text('源稿已修改。',encoding='utf-8')
        result=self.search('一座工厂')
        self.assertEqual(result['results'],[])
        self.assertTrue(any('stale_source' in w for w in result['warnings']))

    def test_exclusions_apply_before_rebuild(self):
        self.build()
        self.profile['excluded_source_ids']=['s1']
        self.assertEqual(self.search('一座工厂')['results'],[])
        self.assertEqual(self.build()['documents'],0)

    def test_long_paragraph_windows_preserve_all_characters(self):
        text=('上文提出条件，再展开具体的比喻和论述。'*100)+'最后的独特结论。'
        windows=list(r.windows(text))
        positions=set()
        for a,b,fragment in windows:
            positions.update(range(a,b));self.assertEqual(fragment,text[a:b])
        self.assertEqual(positions,set(range(len(text))))
        self.assertIn('最后的独特结论', windows[-1][2])

    def test_no_cross_source_context_or_derived_quote(self):
        self.build()
        self.assertNotIn('摘要',self.search('一座工厂')['results'][0]['passage'])
        self.assertEqual(self.search('一座工厂')['results'][0]['content_kind'],'source')

    def test_selected_spans_keep_physical_lines(self):
        self.row['allowed_spans']=[[10,10]];self.write_manifest();self.build()
        self.assertEqual(self.search('一座工厂')['results'],[])
        self.assertEqual(self.search('前因和后果')['results'][0]['lines'],[10,10])

    def test_no_scope_escape(self):
        self.row['path']=str(self.root.parent/'outside-original.md')
        ok,reason=r.source_allowed(self.row,self.profile,self.root)
        self.assertFalse(ok);self.assertEqual(reason,'outside_configured_roots')

    def test_context_is_same_approved_section(self):
        self.build()
        hit=self.search('一座工厂')['results'][0]
        self.assertEqual(hit['context']['before'],[])
        self.assertEqual(hit['context']['after'][0]['lines'],[10,10])
        self.assertNotIn('摘要',str(hit['context']))

    def test_document_ownership_not_enough_for_quote(self):
        self.row['review_status']='final_confirmed';self.write_manifest();self.build()
        self.assertFalse(self.search('一座工厂')['results'][0]['quote_ready'])
        self.row['passage_reviews']=[{'lines':[8,8],'authorship':'user_owned','review_status':'clean_verified'}]
        self.write_manifest();self.build()
        self.assertTrue(self.search('一座工厂')['results'][0]['quote_ready'])
        self.assertFalse(self.search('前因和后果')['results'][0]['quote_ready'])

    def test_external_and_agent_reference_not_personal_default(self):
        self.row['kind']='agent_reference';self.write_manifest();self.build()
        self.assertEqual(self.search('一座工厂')['results'],[])
        result=r.search(self.profile,self.cfg,self.root,self.out,'一座工厂','text',8,True)
        self.assertEqual(result['results'][0]['content_kind'],'agent_reference')

    def test_model_failure_is_explicit_degradation(self):
        self.build()
        with patch.object(r,'model',side_effect=ValueError('test unavailable')):
            result=r.search(self.profile,self.cfg,self.root,self.out,'一座工厂','hybrid')
        self.assertEqual(result['semantic'],'unavailable')
        self.assertTrue(result['results'])
        self.assertTrue(result['warnings'])

    def test_opposite_wording_not_rewritten(self):
        self.path.write_text(self.text.replace('我把经验','我不把经验'),encoding='utf-8')
        self.build()
        hit=self.search('一座工厂')['results'][0]
        self.assertTrue(hit['passage'].startswith('我不把经验'))
        self.assertEqual(hit['relevance'],'candidate_requires_context_review')

    def test_selected_excerpt_does_not_index_editor_preamble(self):
        self.path.write_text('# 标题\n\n这段是Agent的说明。\n\n### 原始L2\n\n这是我自己的完整原文。\n',encoding='utf-8')
        self.row['include_sections']=['原始L2'];self.write_manifest();self.build()
        self.assertEqual(self.search('Agent')['results'],[])
        self.assertEqual(self.search('完整原文')['results'][0]['lines'],[7,7])

    def test_manifest_withdrawal_applies_before_rebuild(self):
        self.build()
        self.row['index']=False;self.write_manifest()
        result=self.search('一座工厂')
        self.assertFalse(result['results'])
        self.assertIn('manifest_changed_reindex_required',result['warnings'])

    def test_multi_query_deduplicates_same_original_paragraph(self):
        self.build()
        result=r.search_many(self.profile,self.cfg,self.root,self.out,['一座工厂','经验 工厂'],'text',8)
        bodies=[h['passage'] for h in result['results']]
        self.assertEqual(len(bodies),len(set(bodies)))
        self.assertEqual(len(result['results'][0]['query_variants']),2)

    def test_multi_query_has_bounded_scope(self):
        with self.assertRaises(ValueError):
            r.search_many(self.profile,self.cfg,self.root,self.out,['a','b','c','d','e'])


@unittest.skipUnless(os.environ.get('YL_RETRIEVAL_REAL_MODEL_PROFILE'),'Optional real offline model test')
class RealOfflineModelTests(unittest.TestCase):
    setUp=RetrievalTests.setUp
    tearDown=RetrievalTests.tearDown
    write_manifest=RetrievalTests.write_manifest
    build=RetrievalTests.build
    def test_real_model_without_network(self):
        import socket
        _,real_cfg,_,_=r.config(os.environ['YL_RETRIEVAL_REAL_MODEL_PROFILE'])
        for name in ('model','model_revision','model_path','model_cache','model_files','threads'):
            self.cfg[name]=real_cfg[name]
        self.path.write_text('# 原始内容\n\n我把重复工作整理成流程，让每次积累都能继续使用。\n\n今天的晚饭是白菜和豆腐。\n',encoding='utf-8')
        self.build()
        with patch.object(socket.socket,'connect',side_effect=AssertionError('Network forbidden')):
            r.embed(self.cfg,self.out)
            value=r.search(self.profile,self.cfg,self.root,self.out,'如何重复利用过去工作的经验','semantic',1)
        self.assertEqual(value['semantic'],'ready')
        self.assertIn('重复工作',value['results'][0]['passage'])
        self.assertEqual(r.status(self.profile,self.cfg,self.root,self.out)['semantic_pending'],0)


if __name__=='__main__':
    unittest.main(verbosity=2)
