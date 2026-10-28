import unittest
from vision_title import parse_titles


class VisionTitleTests(unittest.TestCase):
    def test_accepts_indexed_titles_and_rejects_explanations(self):
        result=parse_titles('[{"index":1,"title":"没有AI平权只有AI极权"},{"index":2,"title":"无法辨认"}]',2)
        self.assertEqual(result,{1:'没有AI平权只有AI极权'})

    def test_wrong_format_never_becomes_title(self):
        self.assertEqual(parse_titles('一个标题，不是JSON',1),{})
        self.assertEqual(parse_titles('[{"index":3,"title":"猜测"}]',1),{})


if __name__=='__main__': unittest.main()
