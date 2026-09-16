import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

function decodeEntities(text) {
  return text.replace(/&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos);/gi, (entity, value) => {
    const named = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'" };
    const lower = value.toLowerCase();
    if (named[lower] !== undefined) return named[lower];
    const codePoint = lower.startsWith("#x")
      ? Number.parseInt(lower.slice(2), 16)
      : Number.parseInt(lower.slice(1), 10);
    return Number.isInteger(codePoint) && codePoint >= 0 && codePoint <= 0x10ffff ? String.fromCodePoint(codePoint) : entity;
  });
}

function normalizeMarkdown(markdown) {
  return markdown
    .split(/\r?\n/)
    .filter((line) => !/^!\[/.test(line))
    .map((line) =>
      line
        .replace(/^#{1,6}\s*/, "")
        .replace(/^>\s?/, "")
        .replace(/^[-*+]\s+/, "")
        .replace(/^\d+\.\s+/, "")
        .replaceAll("**", "")
        .replace(/`([^`\n]+)`/g, "$1")
        .trim(),
    )
    .filter(Boolean)
    .join("\n");
}

function normalizeHtml(html) {
  const article = html.match(/<article\b[^>]*>([\s\S]*?)<\/article>/i)?.[1] ?? "";
  return decodeEntities(
    article
      .replace(/<img\b[^>]*>/gi, "")
      .replace(/<br\s*\/?>/gi, "\n")
      .replace(/<\/(?:h1|h2|h3|p|section|div|blockquote|li)>/gi, "\n")
      .replace(/<[^>]+>/g, ""),
  )
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .join("\n");
}

function parseArguments(argv) {
  const options = { maxChars: 2500 };
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    const value = argv[index + 1];
    if (flag === "--phase") options.phase = value;
    if (flag === "--md") options.md = value;
    if (flag === "--html") options.html = value;
    if (flag === "--cta-file") options.ctaFile = value;
    if (flag === "--max-chars") options.maxChars = Number(value);
    if (flag.startsWith("--")) index += 1;
  }
  return options;
}

function markdownImages(markdown) {
  return [...markdown.matchAll(/!\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)/g)].map((match) => match[1]);
}

function embeddedImages(html) {
  const article = html.match(/<article\b[^>]*>([\s\S]*?)<\/article>/i)?.[1] ?? "";
  return [...article.matchAll(/<img\b[^>]*\bsrc\s*=\s*(["'])data:[^;,]+;base64,([^"']+)\1[^>]*>/gi)]
    .map((match) => match[2].replace(/\s/g, ""));
}

function endsWithFixedCta(markdown, cta) {
  const compact = normalizeMarkdown(markdown).replace(/\s/g, "");
  return compact.endsWith(normalizeMarkdown(cta).replace(/\s/g, ""));
}

function hash(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

function validate(options) {
  const failures = [];
  let checksTotal = 0;
  let checksPassed = 0;
  const check = (condition, failure) => {
    checksTotal += 1;
    if (condition) checksPassed += 1;
    else failures.push(failure);
  };

  if (!["text", "package"].includes(options.phase)) {
    check(false, "invalid_phase");
    return { phase: options.phase ?? null, checksPassed, checksTotal, failures };
  }
  if (!options.md) {
    check(false, "missing_markdown_path");
    return { phase: options.phase, checksPassed, checksTotal, failures };
  }
  if (!Number.isFinite(options.maxChars) || options.maxChars < 0) {
    check(false, "invalid_max_chars");
    return { phase: options.phase, checksPassed, checksTotal, failures };
  }

  let markdown;
  try {
    markdown = readFileSync(options.md, "utf8").replace(/^\uFEFF/, "");
  } catch {
    check(false, "markdown_file_not_readable");
    return { phase: options.phase, checksPassed, checksTotal, failures };
  }

  const h1Count = markdown.split(/\r?\n/).filter((line) => /^#\s+\S/.test(line)).length;
  const textLength = normalizeMarkdown(markdown).replace(/\s/g, "").length;
  const images = markdownImages(markdown);
  check(h1Count === 1, "exactly_one_h1_title");
  check(textLength <= options.maxChars, "text_exceeds_max_chars");
  if (options.phase === "text") check(images.length === 0, "text_phase_must_not_contain_images");
  if (options.ctaFile) {
    try {
      const cta = readFileSync(options.ctaFile, "utf8").replace(/^\uFEFF/, "").trim();
      check(Boolean(cta) && endsWithFixedCta(markdown, cta), "fixed_cta_must_be_final_paragraphs");
    } catch {
      check(false, "cta_file_not_readable");
    }
  }
  check(!/\b(?:TODO|TBD|FIXME)\b/i.test(markdown), "text_must_not_contain_placeholders");

  if (options.phase === "text") {
    return { phase: options.phase, checksPassed, checksTotal, failures };
  }

  if (!options.html) {
    check(false, "missing_html_path");
    return { phase: options.phase, checksPassed, checksTotal, failures };
  }

  let html;
  try {
    html = readFileSync(options.html, "utf8");
  } catch {
    check(false, "html_file_not_readable");
    return { phase: options.phase, checksPassed, checksTotal, failures };
  }

  const embedded = embeddedImages(html);
  check(images.length > 0, "package_phase_must_contain_markdown_images");
  check(embedded.length === images.length, "embedded_image_count_mismatch");

  let imageHashesMatch = embedded.length === images.length;
  if (imageHashesMatch) {
    try {
      const sourceHashes = images.map((imagePath) => hash(readFileSync(resolve(dirname(options.md), imagePath))));
      const embeddedHashes = embedded.map((encoded) => hash(Buffer.from(encoded, "base64")));
      imageHashesMatch = sourceHashes.every((sourceHash, index) => sourceHash === embeddedHashes[index]);
    } catch {
      imageHashesMatch = false;
    }
  }
  check(imageHashesMatch, "embedded_image_sha256_mismatch");
  check(normalizeMarkdown(markdown) === normalizeHtml(html), "markdown_html_text_mismatch");
  check(html.includes("ClipboardItem") && html.includes("article.innerHTML"), "html_missing_rich_copy_logic");

  return { phase: options.phase, checksPassed, checksTotal, failures };
}

const result = validate(parseArguments(process.argv.slice(2)));
process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
process.exit(result.failures.length ? 1 : 0);
