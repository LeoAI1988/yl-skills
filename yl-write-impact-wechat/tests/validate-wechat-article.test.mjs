import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const CTA = "感谢阅读，欢迎分享你的实际经验。\n\n后续内容以作者主页为准。\n\n下次再见。";
const ONE_PIXEL_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL1WAAAAABJRU5ErkJggg==",
  "base64",
);
const cli = new URL("../scripts/validate-wechat-article.mjs", import.meta.url);
const builderCli = new URL("../scripts/build-wechat-html.mjs", import.meta.url);

function run(args) {
  return spawnSync(process.execPath, [fileURLToPath(cli), ...args], { encoding: "utf8" });
}

function runBuilder(args) {
  return spawnSync(process.execPath, [fileURLToPath(builderCli), ...args], {
    encoding: "utf8",
  });
}

test("text phase accepts Markdown-only approved shape", () => {
  const dir = mkdtempSync(join(tmpdir(), "impact-text-"));
  const md = join(dir, "article.md");
  writeFileSync(md, `# 标题\n\n**炸裂开头。**\n\n正文。\n\n${CTA}\n`, "utf8");
  const result = run(["--phase", "text", "--md", md, "--max-chars", "2500"]);
  assert.equal(result.status, 0, result.stdout + result.stderr);
});

test("text phase accepts UTF-8 Markdown with a BOM", () => {
  const dir = mkdtempSync(join(tmpdir(), "impact-text-bom-"));
  const md = join(dir, "article.md");
  writeFileSync(
    md,
    `\uFEFF# 标题\n\n**炸裂开头。**\n\n正文。\n\n${CTA}\n`,
    "utf8",
  );
  const result = run(["--phase", "text", "--md", md, "--max-chars", "2500"]);
  assert.equal(result.status, 0, result.stdout + result.stderr);
});

test("text phase rejects premature images", () => {
  const dir = mkdtempSync(join(tmpdir(), "impact-image-"));
  const md = join(dir, "article.md");
  writeFileSync(md, `# 标题\n\n![图](assets/a.png)\n\n${CTA}\n`, "utf8");
  const result = run(["--phase", "text", "--md", md]);
  assert.equal(result.status, 1);
  assert.match(result.stdout, /text_phase_must_not_contain_images/);
});

test("package phase rejects Markdown and HTML drift", () => {
  const dir = mkdtempSync(join(tmpdir(), "impact-drift-"));
  const md = join(dir, "article.md");
  const html = join(dir, "article.html");
  writeFileSync(md, `# 标题\n\n正文A。\n\n${CTA}\n`, "utf8");
  writeFileSync(html, `<article id="article"><h1>标题</h1><p>正文B。</p><p>${CTA}</p></article>`, "utf8");
  const result = run(["--phase", "package", "--md", md, "--html", html]);
  assert.equal(result.status, 1);
  assert.match(result.stdout, /markdown_html_text_mismatch/);
});

test("text phase reports title, length, CTA, and placeholder violations", () => {
  const dir = mkdtempSync(join(tmpdir(), "impact-text-rules-"));
  const md = join(dir, "article.md");
  writeFileSync(md, "# 标题一\n# 标题二\n\nTODO 内容\n\n收尾不正确。\n", "utf8");
  const cta = join(dir, "cta.txt");
  writeFileSync(cta, CTA, "utf8");
  const result = run(["--phase", "text", "--md", md, "--max-chars", "5", "--cta-file", cta]);
  assert.equal(result.status, 1);
  assert.match(result.stdout, /exactly_one_h1_title/);
  assert.match(result.stdout, /text_exceeds_max_chars/);
  assert.match(result.stdout, /fixed_cta_must_be_final_paragraphs/);
  assert.match(result.stdout, /text_must_not_contain_placeholders/);
});

test("package phase accepts matching image assets and rich-copy HTML", () => {
  const dir = mkdtempSync(join(tmpdir(), "impact-package-ok-"));
  const md = join(dir, "article.md");
  const html = join(dir, "article.html");
  const png = join(dir, "cover.png");
  writeFileSync(png, ONE_PIXEL_PNG);
  writeFileSync(md, `# 标题\n\n正文。\n\n![封面](cover.png)\n\n${CTA}\n`, "utf8");
  writeFileSync(
    html,
    `<article id="article"><h1>标题</h1><p>正文。</p><img src="data:image/png;base64,${ONE_PIXEL_PNG.toString("base64")}"><p>${CTA}</p></article><script>const rich = new ClipboardItem({"text/html": new Blob([article.innerHTML])});</script>`,
    "utf8",
  );
  const result = run(["--phase", "package", "--md", md, "--html", html]);
  assert.equal(result.status, 0, result.stdout + result.stderr);
});

test("package phase accepts builder output containing quotes and lists", () => {
  const dir = mkdtempSync(join(tmpdir(), "impact-package-builder-"));
  const md = join(dir, "article.md");
  const html = join(dir, "article.html");
  const png = join(dir, "cover.png");
  writeFileSync(png, ONE_PIXEL_PNG);
  writeFileSync(
    md,
    [
      "# 标题",
      "",
      "![封面](cover.png)",
      "",
      "> 判断一。",
      "> 判断二。",
      "",
      "- 动作一",
      "- 动作二",
      "",
      CTA,
      "",
    ].join("\n"),
    "utf8",
  );
  const build = runBuilder(["--input", md, "--output", html]);
  assert.equal(build.status, 0, build.stdout + build.stderr);

  const result = run(["--phase", "package", "--md", md, "--html", html]);
  assert.equal(result.status, 0, result.stdout + result.stderr);
});

test("package phase rejects missing Markdown images and plain-copy HTML", () => {
  const dir = mkdtempSync(join(tmpdir(), "impact-package-rules-"));
  const md = join(dir, "article.md");
  const html = join(dir, "article.html");
  writeFileSync(md, `# 标题\n\n正文。\n\n${CTA}\n`, "utf8");
  writeFileSync(html, `<article id="article"><h1>标题</h1><p>正文。</p><p>${CTA}</p></article>`, "utf8");
  const result = run(["--phase", "package", "--md", md, "--html", html]);
  assert.equal(result.status, 1);
  assert.match(result.stdout, /package_phase_must_contain_markdown_images/);
  assert.match(result.stdout, /html_missing_rich_copy_logic/);
});

test("package phase rejects missing or mismatched embedded image data", () => {
  const dir = mkdtempSync(join(tmpdir(), "impact-package-images-"));
  const md = join(dir, "article.md");
  const html = join(dir, "article.html");
  const png = join(dir, "cover.png");
  writeFileSync(png, ONE_PIXEL_PNG);
  writeFileSync(md, `# 标题\n\n正文。\n\n![封面](cover.png)\n\n${CTA}\n`, "utf8");
  writeFileSync(
    html,
    `<article id="article"><h1>标题</h1><p>正文。</p><img src="data:image/png;base64,AA=="><p>${CTA}</p></article><script>new ClipboardItem({"text/html": article.innerHTML});</script>`,
    "utf8",
  );
  const result = run(["--phase", "package", "--md", md, "--html", html]);
  assert.equal(result.status, 1);
  assert.match(result.stdout, /embedded_image_sha256_mismatch/);
});


test("custom CTA is optional and checked at the end when configured", () => {
  const dir = mkdtempSync(join(tmpdir(), "impact-custom-cta-"));
  const md = join(dir, "article.md");
  const cta = join(dir, "cta.txt");
  writeFileSync(md, "# 标题\n\n一篇自然结束的正文。\n", "utf8");
  assert.equal(run(["--phase", "text", "--md", md]).status, 0);
  writeFileSync(cta, "欢迎交流。", "utf8");
  assert.equal(run(["--phase", "text", "--md", md, "--cta-file", cta]).status, 1);
  writeFileSync(md, "# 标题\n\n正文。\n\n欢迎交流。\n", "utf8");
  assert.equal(run(["--phase", "text", "--md", md, "--cta-file", cta]).status, 0);
});
