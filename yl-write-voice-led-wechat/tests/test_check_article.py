"""Synthetic regressions for source anchors, length, and configurable CTA."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('article', Path(__file__).resolve().parents[1]/'scripts/check_article.py')
article = importlib.util.module_from_spec(spec)
spec.loader.exec_module(article)

class ArticleChecks(unittest.TestCase):
    def test_default_has_no_personal_cta(self):
        self.assertEqual(article.check('原稿。', '# 标题\n\n原稿。', ['原稿。'])['status'], 'PASS')

    def test_anchor_cannot_be_invented(self):
        result = article.check('原稿。', '原稿。新增经历。', ['新增经历。'])
        self.assertIn('anchor_not_in_original_source', result['errors'])

    def test_deleting_original_anchor_fails(self):
        result = article.check('先修好灯，再看地图。', '灯亮了。', ['先修好灯，再看地图。'])
        self.assertIn('anchor_not_retained_verbatim', result['errors'])

    def test_cta_must_be_final_if_configured(self):
        self.assertEqual(article.check('原稿。', '原稿。\n\n下次继续。', [], cta='下次继续。')['status'], 'PASS')
        result = article.check('原稿。', '下次继续。\n\n原稿。', [], cta='下次继续。')
        self.assertIn('fixed_cta_missing_or_not_final', result['errors'])

    def test_title_not_counted_sections_counted(self):
        result = article.check('甲乙。', '# 标题\n\n## 节\n\n甲乙。', [], max_chars=3)
        self.assertEqual(result['article_chars_including_cta'], 4)
        self.assertIn('article_above_max_chars', result['errors'])

    def test_empty_cta_cannot_auto_pass(self):
        self.assertIn('fixed_cta_missing_or_not_final', article.check('原稿。', '原稿。', [], cta=' ')['errors'])

if __name__ == '__main__':
    unittest.main()
