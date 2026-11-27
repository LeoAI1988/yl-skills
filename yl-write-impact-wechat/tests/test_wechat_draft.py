"""Exercise recovery and readback without a WeChat account or network."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import wechat_draft as draft


class DraftTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        cover = root / "cover.png"
        cover.write_bytes(b"local cover")
        self.article = ("定稿", '<p>第一段。</p><img src="0"/><p>结尾。</p>',
                        [("image/png", b"local figure")], cover)
        self.receipt = root / "receipt.json"
        self.url = "https://mmbiz.qpic.cn/mmbiz_png/test-figure/0"
        self.drafts = []
        self.endpoints = []
        self.interrupt = False
        self.api = patch.object(draft, "call", side_effect=self.reply)
        self.api.start()
        self.addCleanup(self.api.stop)

    def reply(self, session, endpoint, token, **kwargs):
        self.endpoints.append(endpoint)
        if endpoint == "draft/batchget":
            return {"total_count": len(self.drafts), "item": [
                {"media_id": "sample-draft", "content": {"news_item": [item]}} for item in self.drafts]}
        if endpoint == "media/uploadimg":
            return {"url": self.url}
        if endpoint == "material/add_material":
            return {"media_id": "sample-cover"}
        if endpoint == "draft/add":
            self.drafts.extend(kwargs["json"]["articles"])
            if self.interrupt:
                raise ValueError("connection lost after write")
            return {"media_id": "sample-draft"}
        if endpoint == "draft/get":
            return {"news_item": self.drafts}
        self.fail(f"unexpected endpoint: {endpoint}")

    def save(self):
        draft.save(Mock(), "test", "sample", self.article, self.receipt)

    def test_repeat_only_gets_saved_draft(self):
        self.save()
        self.endpoints.clear()
        self.save()
        self.assertEqual(self.endpoints, ["draft/get"])
        self.assertTrue(json.loads(self.receipt.read_text())["verified"])

    def test_interrupted_add_is_recovered_by_readback(self):
        self.interrupt = True
        with self.assertRaisesRegex(ValueError, "connection lost"):
            self.save()
        self.assertTrue(json.loads(self.receipt.read_text())["pending"])
        self.save()
        self.assertEqual(self.endpoints.count("draft/add"), 1)
        self.assertTrue(json.loads(self.receipt.read_text())["verified"])

    def test_preexisting_title_needs_reconciliation(self):
        self.drafts.append({"title": "定稿"})
        with self.assertRaisesRegex(ValueError, "核对"):
            self.save()
        self.assertNotIn("draft/add", self.endpoints)

    def test_moved_image_and_changed_footer_fail_readback(self):
        self.save()
        for body in (f'<img src="{self.url}"/><p>第一段。</p><p>结尾。</p>',
                     f'<p>第一段。</p><img src="{self.url}"/><p>另一个结尾。</p>'):
            self.drafts[0]["content"] = body
            with self.assertRaisesRegex(ValueError, "差异"):
                self.save()

    def test_renamed_cdn_path_and_formatting_wrappers(self):
        self.save()
        item = self.drafts[0]
        item["content"] = "<section>" + item["content"].replace("/mmbiz_png/", "/sz_mmbiz_png/").replace("/0", "/640") + "</section>"
        self.save()
        self.assertEqual(len(self.drafts), 1)


class ConnectionTest(unittest.TestCase):
    def test_whitelist_uses_error_response_ip(self):
        session = Mock()
        session.post.return_value = Mock(status_code=200, content=json.dumps(
            {"errcode": 40164, "errmsg": "invalid ip ::ffff:192.0.2.19, not in whitelist"}
        ).encode())
        with self.assertRaisesRegex(draft.ApiError, "192.0.2.19"):
            draft.call(session, "stable_token", json={})


if __name__ == "__main__":
    unittest.main()
