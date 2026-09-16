import test from "node:test";
import assert from "node:assert/strict";
import {
  existsSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const CTA = "感谢阅读，欢迎分享你的实际经验。\n\n后续内容以作者主页为准。\n\n下次再见。";

const cli = fileURLToPath(
  new URL("../scripts/build-wechat-html.mjs", import.meta.url),
);

function run(args) {
  return spawnSync(process.execPath, [cli, ...args], { encoding: "utf8" });
}

function makeArticle() {
  const dir = mkdtempSync(join(tmpdir(), "impact-build-"));
  const assets = join(dir, "assets");
  mkdirSync(assets);
  writeFileSync(
    join(assets, "cover.png"),
    Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nWQAAAAASUVORK5CYII=",
      "base64",
    ),
  );
  writeFileSync(
    join(dir, "article.md"),
    [
      "# 格式校验示例",
      "",
      "![格式示例](assets/cover.png)",
      "",
      "**今天测试一份排版文件。**",
      "",
      "## 01",
      "",
      "### 三级标题",
      "",
      "正文中的**重点。**",
      "",
      "> 这是一句引用。",
      "> 这是第二句引用。",
      "",
      "- 今天交出真实资料",
      "- 明天验收真实结果",
      "",
      CTA,
      "",
    ].join("\n"),
    "utf8",
  );
  return {
    dir,
    input: join(dir, "article.md"),
    output: join(dir, "article.html"),
  };
}

test("builds portable rich-copy HTML from approved Markdown", () => {
  const article = makeArticle();
  const cta = join(article.dir, "cta.txt");
  writeFileSync(cta, CTA, "utf8");
  const result = run(["--input", article.input, "--output", article.output, "--cta-file", cta]);

  assert.equal(result.status, 0, result.stdout + result.stderr);
  assert.equal(existsSync(article.output), true);

  const html = readFileSync(article.output, "utf8");
  assert.match(html, /<!doctype html>/i);
  assert.match(html, /charset="utf-8"/i);
  assert.match(html, /data:image\/png;base64,/);
  assert.match(html, /<article id="article"/);
  assert.match(html, /new ClipboardItem/);
  assert.match(html, /article\.innerHTML/);
  assert.match(html, /article\.innerText/);
  assert.match(html, /document\.execCommand\(["']copy["']\)/);
  assert.match(html, /alt="格式示例"/);
  assert.match(html, /<strong>重点。<\/strong>/);
  assert.match(html, /<blockquote/);
  assert.match(html, /这是一句引用。<br \/>这是第二句引用。/);
  assert.doesNotMatch(html, /&lt;br \/&gt;/);
  assert.match(html, /<ul/);
  assert.match(
    html,
    /<h2 style="[^"]*font-size:22px;[^"]*font-weight:900[^"]*">01<\/h2>/,
  );
  assert.match(
    html,
    /<p style="[^"]*margin:44px 0 20px;[^"]*color:#d92121;[^"]*font-weight:900[^"]*">感谢阅读/,
  );
  assert.match(
    html,
    /<p style="[^"]*color:#d92121;[^"]*font-weight:900[^"]*">后续内容以作者主页为准/,
  );
  assert.match(
    html,
    /<p style="[^"]*color:#d92121;[^"]*font-weight:900[^"]*">下次再见/,
  );
  assert.doesNotMatch(html, /assets\/cover\.png/);
});

test("does not create output when a referenced image is missing", () => {
  const dir = mkdtempSync(join(tmpdir(), "impact-build-missing-"));
  const input = join(dir, "article.md");
  const output = join(dir, "article.html");
  writeFileSync(input, "# 标题\n\n![缺图](assets/missing.png)\n", "utf8");

  const result = run(["--input", input, "--output", output]);

  assert.equal(result.status, 1);
  assert.match(result.stderr, /Image not found/i);
  assert.equal(existsSync(output), false);
});

test("rejects unsupported remote image URLs to keep the package offline", () => {
  const dir = mkdtempSync(join(tmpdir(), "impact-build-remote-"));
  const input = join(dir, "article.md");
  const output = join(dir, "article.html");
  writeFileSync(
    input,
    "# 标题\n\n![远程图](https://example.com/cover.png)\n",
    "utf8",
  );

  const result = run(["--input", input, "--output", output]);

  assert.equal(result.status, 1);
  assert.match(result.stderr, /Local image paths only/i);
  assert.equal(existsSync(output), false);
});


test("builder checks the configured CTA instead of injecting a personal footer", () => {
  const dir = mkdtempSync(join(tmpdir(), "impact-build-custom-cta-"));
  const input = join(dir, "article.md");
  const output = join(dir, "article.html");
  const cta = join(dir, "cta.txt");
  writeFileSync(input, "# 标题\n\n正文。\n", "utf8");
  writeFileSync(cta, "欢迎交流。", "utf8");
  const mismatch = run(["--input", input, "--output", output, "--cta-file", cta]);
  assert.equal(mismatch.status, 1);
  assert.equal(existsSync(output), false);
  const plain = run(["--input", input, "--output", output]);
  assert.equal(plain.status, 0);
  assert.doesNotMatch(readFileSync(output, "utf8"), /欢迎交流/);
});
