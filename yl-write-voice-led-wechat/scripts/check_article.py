"""Read-only length, CTA and explicit-source-anchor checks; no semantic scoring."""
import argparse
import json
import re
from pathlib import Path


def compact(value):
    return re.sub(r"\s+", "", value)


def visible_text(value):
    value = re.sub(r"\A---\s*\n.*?\n---\s*\n", "", value, count=1, flags=re.S)
    value = re.sub(r"^\s{0,3}#\s+.*$", "", value, count=1, flags=re.M)
    value = re.sub(r"^\s{0,3}#{1,6}\s+", "", value, flags=re.M)
    value = re.sub(r"<!--.*?-->", "", value, flags=re.S)
    value = re.sub(r"!\[[^\]]*\]\([^\n]*?\)", "", value)
    value = re.sub(r"\[([^\]]+)\]\([^\n]*?\)", r"\1", value)
    value = re.sub(r"^\s{0,3}(?:>\s?|[-+*]\s+|\d+\.\s+)", "", value, flags=re.M)
    for marker in ("**", "__", "`"):
        value = value.replace(marker, "")
    # Paired strikethrough only: literal ~~ in an installer-provided CTA must survive.
    value = re.sub(r"~~([^\n]+?)~~", r"\1", value)
    return value.strip()


def check(source, article, anchors, min_chars=None, max_chars=None, cta=None):
    rendered = visible_text(article)
    flat = compact(rendered)
    source_flat = compact(source)
    cta_flat = compact(visible_text(cta)) if cta is not None else ""
    cta_at_end = bool(cta_flat) and flat.endswith(cta_flat)
    body_count = len(flat) - (len(cta_flat) if cta_at_end else 0)
    checks = [
        {"text": item, "in_source": compact(item) in source_flat,
         "in_article": compact(item) in flat}
        for item in anchors
    ]
    errors = []
    if min_chars is not None and len(flat) < min_chars:
        errors.append("article_below_min_chars")
    if max_chars is not None and len(flat) > max_chars:
        errors.append("article_above_max_chars")
    if cta is not None and not cta_at_end:
        errors.append("fixed_cta_missing_or_not_final")
    if any(not item["in_source"] for item in checks):
        errors.append("anchor_not_in_original_source")
    if any(not item["in_article"] for item in checks):
        errors.append("anchor_not_retained_verbatim")
    if not flat:
        errors.append("article_empty")
    return {
        "status": "PASS" if not errors else "REVIEW_NEEDED",
        "measurement": "Unicode non-whitespace characters, punctuation included; first H1 title excluded, section headings included",
        "article_chars_including_cta": len(flat),
        "body_chars_excluding_fixed_cta": body_count,
        "source_non_whitespace_chars": len(compact(visible_text(source))),
        "min_chars": min_chars, "max_chars": max_chars,
        "fixed_cta_at_end": cta_at_end,
        "anchors": checks, "errors": errors,
        "limitations": "Only explicit anchors are checked. No semantic, factual, style or 80-percent fidelity score."
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--article", type=Path, required=True)
    parser.add_argument("--anchors", type=Path)
    parser.add_argument("--min-chars", type=int)
    parser.add_argument("--max-chars", type=int)
    parser.add_argument("--cta-file", type=Path, help="Optional installer-provided final CTA")
    args = parser.parse_args()
    if ((args.min_chars is not None and args.min_chars < 0)
            or (args.max_chars is not None and args.max_chars < 0)
            or (args.min_chars is not None and args.max_chars is not None
                and args.min_chars > args.max_chars)):
        parser.error("Character range must be nonnegative and min <= max.")
    anchors = json.loads(args.anchors.read_text(encoding="utf-8-sig")) if args.anchors else []
    if (not isinstance(anchors, list)
            or any(not isinstance(item, str) or not compact(item) for item in anchors)):
        parser.error("Anchors must be a JSON array of nonempty strings.")
    result = check(args.source.read_text(encoding="utf-8-sig"),
                   args.article.read_text(encoding="utf-8-sig"), anchors,
                   args.min_chars, args.max_chars,
                   args.cta_file.read_text(encoding="utf-8-sig") if args.cta_file else None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
