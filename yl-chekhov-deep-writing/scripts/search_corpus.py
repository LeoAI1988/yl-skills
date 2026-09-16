#!/usr/bin/env python3
"""List or literally search the installed Russian and authorized-local corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from corpus_utils import load_corpus_manifest, locate_corpus, safe_member


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-root")
    parser.add_argument("--list", action="store_true", dest="list_works")
    parser.add_argument("--query")
    parser.add_argument("--language", choices=("ru", "zh", "all"), default="all")
    parser.add_argument("--context", type=int, default=0)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not args.list_works and not args.query:
        parser.error("use --list or --query")
    if args.context < 0 or args.context > 20:
        parser.error("--context must be between 0 and 20")
    if args.limit < 1 or args.limit > 1000:
        parser.error("--limit must be between 1 and 1000")
    return args


def work_rows(manifest: dict, language: str) -> list[dict]:
    rows: list[dict] = []
    if language in {"ru", "all"}:
        rows.extend(manifest.get("works", []))
    if language in {"zh", "all"}:
        rows.extend(manifest.get("translations", {}).get("included", []))
    return rows


def list_payload(manifest: dict, language: str) -> dict:
    rows = work_rows(manifest, language)
    return {
        "status": "ok",
        "language": language,
        "count": len(rows),
        "works": [
            {
                "work_id": item.get("work_id"),
                "source_id": item.get("source_id"),
                "work_title": item.get("work_title"),
                "original_title": item.get("original_title"),
                "language": item.get("language"),
                "text_path": item.get("clean_path") or item.get("text_path"),
                "fixed_revision_url": item.get("fixed_revision_url"),
            }
            for item in rows
        ],
        "translation_status": manifest.get("translations", {}).get("status"),
    }


def search(root: Path, manifest: dict, query: str, language: str, context: int, limit: int) -> dict:
    needle = query.casefold()
    hits: list[dict] = []
    for item in work_rows(manifest, language):
        relative = item.get("clean_path") or item.get("text_path")
        if not relative:
            continue
        path = safe_member(root, str(relative))
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if needle not in line.casefold():
                continue
            start = max(0, index - context)
            end = min(len(lines), index + context + 1)
            hits.append(
                {
                    "work_id": item.get("work_id"),
                    "source_id": item.get("source_id"),
                    "work_title": item.get("work_title"),
                    "language": item.get("language"),
                    "fixed_revision_url": item.get("fixed_revision_url"),
                    "line": index + 1,
                    "context_start": start + 1,
                    "context_end": end,
                    "text": "\n".join(lines[start:end]),
                }
            )
            if len(hits) >= limit:
                return {"status": "ok", "query": query, "hit_count": len(hits), "hits": hits}
    status = "ok"
    note = None
    if language == "zh" and not manifest.get("translations", {}).get("included"):
        note = "当前安装没有获授权的中文全文。"
    return {"status": status, "query": query, "hit_count": len(hits), "hits": hits, "note": note}


def render_text(payload: dict) -> None:
    if "works" in payload:
        print(f"count={payload['count']} language={payload['language']}")
        for item in payload["works"]:
            print(f"{item['work_id']}\t{item['source_id']}\t{item['work_title']}\t{item['language']}")
        if payload.get("translation_status"):
            print(f"translation_status={payload['translation_status']}")
        return
    print(f"query={payload['query']} hit_count={payload['hit_count']}")
    if payload.get("note"):
        print(payload["note"])
    for hit in payload["hits"]:
        print(
            f"--- {hit['work_title']} {hit['work_id']} {hit['source_id']} "
            f"lines {hit['context_start']}-{hit['context_end']} ---"
        )
        print(hit["text"])
        if hit.get("fixed_revision_url"):
            print(f"source={hit['fixed_revision_url']}")


def main() -> int:
    args = parse_args()
    try:
        root = locate_corpus(args.corpus_root)
        manifest = load_corpus_manifest(root)
        if args.list_works:
            payload = list_payload(manifest, args.language)
        else:
            payload = search(root, manifest, args.query, args.language, args.context, args.limit)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        payload = {"status": "error", "error": str(exc)}
        print(json.dumps(payload, ensure_ascii=False) if args.json else payload["error"])
        return 1
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        render_text(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
