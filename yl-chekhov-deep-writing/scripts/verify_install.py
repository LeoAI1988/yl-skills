#!/usr/bin/env python3
"""Verify the installed skill runtime and public corpus, including payload hashes."""

from __future__ import annotations

import argparse
import json

from corpus_utils import load_corpus_manifest, locate_corpus, safe_member, sha256_file
from load_runtime_profile import load_profile


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-root")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    errors: list[str] = []
    checked = 0
    try:
        profile = load_profile()
        if len(profile["mechanism_parameters"]) != 3 or len(profile["shell_parameters"]) != 3:
            errors.append("runtime_profile_incomplete")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(str(exc))

    try:
        root = locate_corpus(args.corpus_root)
        manifest = load_corpus_manifest(root)
        for member in manifest.get("payload_files", []):
            path = safe_member(root, str(member.get("path") or ""))
            if not path.is_file():
                errors.append(f"missing:{member.get('path')}")
                continue
            checked += 1
            if path.stat().st_size != member.get("bytes"):
                errors.append(f"size_mismatch:{member.get('path')}")
            if sha256_file(path) != member.get("sha256"):
                errors.append(f"sha256_mismatch:{member.get('path')}")
        if len(manifest.get("works", [])) != 12:
            errors.append("original_work_count_not_12")
        if manifest.get("translations", {}).get("included_count") != 0:
            errors.append("public_translation_count_not_zero")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(str(exc))
        root = None

    payload = {
        "status": "passed" if not errors else "failed",
        "runtime_profile": "available" if not errors else "check_errors",
        "corpus_root": str(root) if root else None,
        "checked_payload_files": checked,
        "original_work_count": 12 if not errors else None,
        "authorized_chinese_text_count": 0 if not errors else None,
        "errors": errors,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
