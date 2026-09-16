#!/usr/bin/env python3
"""Exercise portable installation without using an existing user Skill or corpus."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main() -> int:
    source = Path(__file__).resolve().parents[1]
    checks: list[str] = []
    with tempfile.TemporaryDirectory(prefix="yl-chekhov-portable-") as temporary:
        root = Path(temporary).resolve()
        target = root / "skills" / "yl-chekhov-deep-writing"
        shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        env = dict(os.environ)
        env.pop("YL_CHEKHOV_CORPUS_ROOT", None)
        env.pop("CHEKHOV_CORPUS_ROOT", None)
        env["CODEX_HOME"] = str(root / "empty-codex")
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        def run(script: str, *arguments: str, expect: int = 0) -> dict:
            result = subprocess.run(
                [sys.executable, "-B", "-X", "utf8", str(target / "scripts" / script), *arguments],
                cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", check=False,
            )
            if result.returncode != expect:
                raise AssertionError(f"{script}: exit={result.returncode}; {result.stdout}; {result.stderr}")
            return json.loads(result.stdout)

        profile = run("load_runtime_profile.py")
        assert profile["status"] == "available"
        assert len(profile["runtime_payload"]["mechanism_parameters"]) == 3
        assert len(profile["runtime_payload"]["shell_parameters"]) == 3
        checks.append("runtime_profile_portable")

        install = run("verify_install.py")
        assert install["status"] == "passed"
        assert Path(install["corpus_root"]).resolve() == (target / "corpus").resolve()
        assert install["original_work_count"] == 12
        assert install["authorized_chinese_text_count"] == 0
        checks.append("bundled_corpus_hashes_and_zero_chinese")

        listing = run("search_corpus.py", "--list", "--language", "ru", "--json")
        assert listing["count"] == 12
        checks.append("twelve_full_texts_listed")

        hits = run("search_corpus.py", "--language", "ru", "--query", "Червяков", "--limit", "2", "--json")
        assert hits["hit_count"] == 2
        for hit in hits["hits"]:
            assert hit["source_id"] == "SRC-CHE-002" and hit["line"] > 0
            assert hit["fixed_revision_url"].startswith("https://ru.wikisource.org/")
        checks.append("russian_search_with_source_and_line")

        empty = run("search_corpus.py", "--language", "zh", "--query", "关键词", "--json")
        assert empty["hit_count"] == 0 and "没有获授权的中文全文" in empty["note"]
        checks.append("missing_chinese_explained")

        invalid = run("search_corpus.py", "--corpus-root", str(root / "missing"), "--list", "--json", expect=1)
        assert invalid["status"] == "error" and "corpus_manifest_not_found" in invalid["error"]
        checks.append("invalid_override_does_not_fall_back")

        # Mutate only the isolated copy; public verification must detect tampering.
        corpus_manifest = json.loads((target / "corpus" / "corpus-manifest.json").read_text(encoding="utf-8"))
        sample = target / "corpus" / corpus_manifest["works"][0]["clean_path"]
        sample.write_bytes(sample.read_bytes() + b"\nverification mutation\n")
        failed = run("verify_install.py", expect=1)
        assert failed["status"] == "failed" and any("sha256_mismatch:" in item for item in failed["errors"])
        checks.append("tampered_corpus_rejected")

    print(json.dumps({"status": "passed", "checks": checks, "check_count": len(checks)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
