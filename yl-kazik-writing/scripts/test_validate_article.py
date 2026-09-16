#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("validate_article.py")
CTA = "感谢阅读。欢迎分享你的实际经验。"


class ValidateArticleTests(unittest.TestCase):
    def run_validator(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-X", "utf8", str(SCRIPT), *args],
            text=True,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )

    def test_valid_text_draft_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            article = Path(temp_dir) / "article.md"
            article.write_text(f"# 标题\n\n这是有具体事实的正文。\n\n{CTA}\n", encoding="utf-8")
            cta = Path(temp_dir) / "cta.txt"
            cta.write_text(CTA, encoding="utf-8")
            result = self.run_validator(
                "--input",
                str(article),
                "--max-chars",
                "500",
                "--cta-file",
                str(cta),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('"passed": true', result.stdout)

    def test_missing_h1_and_placeholder_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            article = Path(temp_dir) / "article.md"
            article.write_text("没有标题。\n\n[配图：待补]\n", encoding="utf-8")
            result = self.run_validator("--input", str(article))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("expected exactly one H1", result.stdout)
            self.assertIn("placeholder patterns found", result.stdout)

    def test_strict_overlap_fails(self) -> None:
        repeated = "这是一个用于检查连续汉字重合的完整示例段落"
        with tempfile.TemporaryDirectory() as temp_dir:
            article = Path(temp_dir) / "article.md"
            reference = Path(temp_dir) / "source.md"
            article.write_text(f"# 新标题\n\n{repeated}\n\n{CTA}\n", encoding="utf-8")
            reference.write_text(f"# 原标题\n\n{repeated}\n", encoding="utf-8")
            result = self.run_validator(
                "--input",
                str(article),
                "--reference",
                str(reference),
                "--strict-overlap",
                "--max-overlap-coverage",
                "0.01",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("source overlap coverage exceeded", result.stdout)


    def test_configured_cta_must_be_the_ending(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            article = Path(temp_dir) / "article.md"
            cta = Path(temp_dir) / "cta.txt"
            cta.write_text(CTA, encoding="utf-8")
            article.write_text(f"# 标题\n\n{CTA}\n\n这段在结尾之后。", encoding="utf-8")
            result = self.run_validator("--input", str(article), "--cta-file", str(cta))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not at the end", result.stdout)
            article.write_text("# 标题\n\n无需固定结尾的正文。", encoding="utf-8")
            self.assertEqual(self.run_validator("--input", str(article)).returncode, 0)


if __name__ == "__main__":
    unittest.main()
