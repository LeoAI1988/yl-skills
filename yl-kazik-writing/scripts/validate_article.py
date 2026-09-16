#!/usr/bin/env python3
"""Validate a Chinese WeChat Markdown draft and optionally audit source overlap."""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path


AI_RESIDUE = (
    "在当今AI快速发展的时代",
    "随着人工智能技术的不断发展",
    "综上所述",
    "总的来说",
    "不可否认",
    "值得注意的是",
    "让我们来看看",
    "接下来让我们",
)

PLACEHOLDER_PATTERNS = (
    r"\bTODO\b",
    r"\bTBD\b",
    r"待补",
    r"待完善",
    r"\[配图",
    r"\[图片",
    r"<[^>\n]{1,30}占位[^>\n]*>",
)

AUTHOR_RESIDUE_PATTERNS = (
    r"(?m)^\s*>\s*/\s*作者[：:]\s*卡兹克\s*$",
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate WeChat Markdown length, structure, CTA, placeholders, and overlap."
    )
    parser.add_argument("--input", required=True, type=Path, help="Article Markdown path")
    parser.add_argument("--max-chars", type=int, default=1800)
    parser.add_argument("--phase", choices=("text", "package"), default="text")
    parser.add_argument("--cta-file", type=Path, help="Optional file containing the installer-approved ending")
    parser.add_argument("--reference", type=Path, help="Optional source article for overlap audit")
    parser.add_argument("--min-overlap", type=int, default=13)
    parser.add_argument("--max-overlap-coverage", type=float, default=0.05)
    parser.add_argument("--strict-overlap", action="store_true")
    return parser.parse_args()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def article_char_count(markdown: str) -> int:
    text = re.sub(r"(?m)^#{1,6}\s*", "", markdown)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[`*_>#\s]", "", text)
    return len(text)


def han_only(text: str) -> str:
    return "".join(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))


def overlap_audit(article: str, reference: str, min_overlap: int) -> dict:
    article_han = han_only(article)
    reference_han = han_only(reference)
    matcher = difflib.SequenceMatcher(
        None, article_han, reference_han, autojunk=False
    )
    blocks = [block for block in matcher.get_matching_blocks() if block.size >= min_overlap]
    matches = [
        {
            "length": block.size,
            "text": article_han[block.a : block.a + block.size],
            "article_offset": block.a,
            "reference_offset": block.b,
        }
        for block in blocks
    ]
    covered = sum(item["length"] for item in matches)
    coverage = covered / len(article_han) if article_han else 0.0
    longest = max((item["length"] for item in matches), default=0)
    return {
        "article_han_chars": len(article_han),
        "reference_han_chars": len(reference_han),
        "match_count": len(matches),
        "covered_chars": covered,
        "coverage": round(coverage, 6),
        "longest": longest,
        "matches": matches[:50],
    }


def main() -> int:
    args = parse_args()
    failures: list[str] = []
    warnings: list[str] = []

    if not args.input.is_file():
        print(json.dumps({"failures": [f"input not found: {args.input}"]}, ensure_ascii=False))
        return 1

    article = read_text(args.input)
    chars = article_char_count(article)
    h1_count = len(re.findall(r"(?m)^#\s+\S", article))

    if h1_count != 1:
        failures.append(f"expected exactly one H1, found {h1_count}")
    if chars > args.max_chars:
        failures.append(f"character limit exceeded: {chars} > {args.max_chars}")

    placeholder_hits = [
        pattern for pattern in PLACEHOLDER_PATTERNS if re.search(pattern, article, re.I)
    ]
    if placeholder_hits:
        failures.append(f"placeholder patterns found: {placeholder_hits}")

    author_residue_hits = [
        pattern for pattern in AUTHOR_RESIDUE_PATTERNS if re.search(pattern, article, re.I)
    ]
    if author_residue_hits:
        failures.append("reference-author footer or contact residue found")

    if args.phase == "text" and re.search(r"!\[[^\]]*\]\([^)]+\)", article):
        failures.append("text phase must not contain Markdown images")

    cta_present = None
    if args.cta_file:
        if not args.cta_file.is_file():
            failures.append("CTA file not found")
        else:
            cta = re.sub(r"\s+", "", read_text(args.cta_file))
            cta_present = bool(cta) and re.sub(r"\s+", "", article).endswith(cta)
            if not cta_present:
                failures.append("configured CTA missing, changed, or not at the end")

    residue_hits = [phrase for phrase in AI_RESIDUE if phrase in article]
    if residue_hits:
        warnings.append(f"generic AI prose phrases found: {residue_hits}")

    if re.search(r"首先.{0,80}其次.{0,80}最后", article, re.S):
        warnings.append("mechanical 首先/其次/最后 sequence found")

    overlap = None
    if args.reference:
        if not args.reference.is_file():
            failures.append(f"reference not found: {args.reference}")
        else:
            overlap = overlap_audit(
                article, read_text(args.reference), args.min_overlap
            )
            if (
                args.strict_overlap
                and overlap["coverage"] > args.max_overlap_coverage
            ):
                failures.append(
                    "source overlap coverage exceeded: "
                    f"{overlap['coverage']:.2%} > {args.max_overlap_coverage:.2%}"
                )

    result = {
        "input": str(args.input.resolve()),
        "phase": args.phase,
        "checks": {
            "characters": chars,
            "max_characters": args.max_chars,
            "h1_count": h1_count,
            "cta_required": bool(args.cta_file),
            "cta_present": cta_present,
            "placeholder_hits": placeholder_hits,
            "author_residue_hits": len(author_residue_hits),
        },
        "overlap": overlap,
        "warnings": warnings,
        "failures": failures,
        "passed": not failures,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
