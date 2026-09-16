#!/usr/bin/env python3
"""Locate the bundled corpus or an explicitly configured external corpus."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def candidate_roots(explicit: str | None = None) -> list[Path]:
    candidates: list[Path] = []
    env_root = os.environ.get("YL_CHEKHOV_CORPUS_ROOT")
    if explicit:
        candidates.append(Path(explicit))
    elif env_root:
        candidates.append(Path(env_root))
    else:
        candidates.append(Path(__file__).resolve().parents[1] / "corpus")

    result: list[Path] = []
    seen: set[str] = set()
    for item in candidates:
        resolved = item.expanduser().resolve()
        key = str(resolved).casefold()
        if key not in seen:
            seen.add(key)
            result.append(resolved)
    return result


def locate_corpus(explicit: str | None = None) -> Path:
    for root in candidate_roots(explicit):
        if (root / "corpus-manifest.json").is_file():
            return root
    checked = "; ".join(str(item) for item in candidate_roots(explicit))
    raise FileNotFoundError(f"corpus_manifest_not_found; checked={checked}")


def load_corpus_manifest(root: Path) -> dict:
    manifest_path = root / "corpus-manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if data.get("schema_version") != "chekhov-corpus-manifest-v1":
        raise ValueError("corpus_manifest_schema_invalid")
    if data.get("scope", {}).get("current_project_original_work_count") != 12:
        raise ValueError("corpus_work_count_invalid")
    return data


def safe_member(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    path.relative_to(root.resolve())
    return path
