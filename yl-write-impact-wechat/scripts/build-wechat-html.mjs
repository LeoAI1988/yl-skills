#!/usr/bin/env node

import {
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { dirname, extname, isAbsolute, resolve } from "node:path";

function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    if (!key.startsWith("--")) {
      throw new Error(`Unexpected argument: ${key}`);
    }
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) {
      throw new Error(`Missing value for ${key}`);
    }
    args[key.slice(2)] = value;
    index += 1;
  }
  if (!args.input || !args.output) {
    throw new Error(
      "Usage: build-wechat-html.mjs --input ARTICLE.md --output ARTICLE.html",
    );
  }
  return args;
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function inlineMarkdown(value) {
  const escaped = escapeHtml(value);
  return escaped
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`\n]+)`/g, "<code>$1</code>");
}

const MIME_BY_EXTENSION = {
  ".gif": "image/gif",
  ".jpeg": "image/jpeg",
  ".jpg": "image/jpeg",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
};

function resolveLocalImage(imageReference, inputDir) {
  const source = imageReference.trim();
  if (
    /^(?:https?:|data:|file:|ftp:)/i.test(source) ||
    source.startsWith("//")
  ) {
    throw new Error(`Local image paths only: ${source}`);
  }

  const imagePath = isAbsolute(source)
    ? resolve(source)
    : resolve(inputDir, source);
  if (!existsSync(imagePath)) {
    throw new Error(`Image not found: ${imagePath}`);
  }

  const extension = extname(imagePath).toLowerCase();
  const mime = MIME_BY_EXTENSION[extension];
  if (!mime) {
    throw new Error(`Unsupported image type: ${extension || "(none)"}`);
  }

  return {
    imagePath,
    dataUri: `data:${mime};base64,${readFileSync(imagePath).toString("base64")}`,
  };
}

function embeddedImageHtml(alt, reference, inputDir) {
  const { dataUri } = resolveLocalImage(reference, inputDir);
  return `<p style="margin:24px 0;text-align:center"><img src="${dataUri}" alt="${escapeHtml(alt)}" style="display:block;width:100%;height:auto;margin:0 auto;border:0" /></p>`;
}

function renderList(lines, ordered) {
  const tag = ordered ? "ol" : "ul";
  const listStyle = ordered ? "decimal" : "disc";
  const items = lines
    .map((line) => {
      const content = line.replace(ordered ? /^\d+\.\s+/ : /^[-*+]\s+/, "");
      return `<li style="margin:0 0 10px">${inlineMarkdown(content)}</li>`;
    })
    .join("");
  return `<${tag} style="margin:0 0 20px;padding-left:1.6em;font-size:17px;line-height:2.05;list-style:${listStyle}">${items}</${tag}>`;
}

function blockToHtml(block, inputDir, forceCta = false) {
  const trimmed = block.trim();
  const image = trimmed.match(/^!\[([^\]]*)\]\(([^)]+)\)$/);
  if (image) {
    return embeddedImageHtml(image[1], image[2], inputDir);
  }

  const lines = trimmed.split(/\r?\n/);
  if (lines.every((line) => /^[-*+]\s+/.test(line))) {
    return renderList(lines, false);
  }
  if (lines.every((line) => /^\d+\.\s+/.test(line))) {
    return renderList(lines, true);
  }

  const h1Style =
    "margin:0 0 20px;text-align:center;font-size:30px;line-height:1.45;font-weight:800;color:#111";
  const h2Style =
    "margin:42px 0 14px;font-size:22px;line-height:1.6;font-weight:900;color:#c9272c";
  const h3Style =
    "margin:30px 0 14px;font-size:20px;line-height:1.65;font-weight:900;color:#111";
  const pStyle =
    "margin:0 0 20px;font-size:17px;line-height:2.05;text-align:justify;color:#242424";
  const ctaStyle =
    "margin:44px 0 20px;font-size:17px;line-height:2.05;text-align:justify;color:#d92121;font-weight:900";

  if (/^# /.test(trimmed)) {
    return `<h1 style="${h1Style}">${inlineMarkdown(trimmed.slice(2))}</h1>`;
  }
  if (/^## /.test(trimmed)) {
    return `<h2 style="${h2Style}">${inlineMarkdown(trimmed.slice(3))}</h2>`;
  }
  if (/^### /.test(trimmed)) {
    return `<h3 style="${h3Style}">${inlineMarkdown(trimmed.slice(4))}</h3>`;
  }
  if (lines.every((line) => /^>\s?/.test(line))) {
    const quote = lines
      .map((line) => line.replace(/^>\s?/, ""))
      .map((line) => inlineMarkdown(line))
      .join("<br />");
    return `<blockquote style="margin:0 0 20px;padding:10px 16px;border-left:4px solid #c9272c;background:#f7f7f7;font-size:17px;line-height:2;color:#333">${quote}</blockquote>`;
  }

  const paragraph = lines.map((line) => line.trim()).join(" ");
  const paragraphStyle = forceCta
    ? ctaStyle
    : pStyle;
  return `<p style="${paragraphStyle}">${inlineMarkdown(paragraph)}</p>`;
}

function renderArticle(markdown, inputDir, cta = "") {
  const ctaBlocks = cta.trim().split(/\r?\n\s*\r?\n/).filter(Boolean);
  const blocks = markdown
    .replace(/^\uFEFF/, "")
    .trim()
    .split(/\r?\n\s*\r?\n/)
    .filter((block) => block.trim())
    ;
  if (ctaBlocks.length) {
    const tail = blocks.slice(-ctaBlocks.length);
    if (tail.length !== ctaBlocks.length || tail.some((block, index) => block.trim() !== ctaBlocks[index].trim())) {
      throw new Error("Article must end with the provided CTA paragraphs");
    }
  }
  return blocks.map((block, index) => blockToHtml(block, inputDir, ctaBlocks.length > 0 && index >= blocks.length - ctaBlocks.length)).join("\n");
}

function documentTemplate(articleHtml, title) {
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>${escapeHtml(title)}｜公众号一键复制版</title>
  <style>
    *{box-sizing:border-box}
    body{margin:0;background:#eef0f3;color:#242424;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}
    .toolbar{position:sticky;top:0;z-index:10;display:flex;align-items:center;justify-content:center;gap:14px;padding:14px;background:rgba(17,17,17,.94)}
    .toolbar button{border:0;border-radius:8px;padding:11px 24px;background:#e63737;color:#fff;font-size:16px;font-weight:700;cursor:pointer}
    .toolbar button:hover{background:#c9272c}
    #copy-status{min-width:150px;color:#fff;font-size:14px}
    .page{width:min(100%,760px);margin:28px auto;padding:0 16px}
    #article{padding:38px 34px;background:#fff;box-shadow:0 8px 32px rgba(0,0,0,.08)}
    @media(max-width:640px){.page{margin:0;padding:0}.toolbar{justify-content:flex-start}.toolbar button{padding:10px 16px}#article{padding:28px 20px;box-shadow:none}}
  </style>
</head>
<body>
  <div class="toolbar">
    <button id="copy-button" type="button">复制公众号全文</button>
    <span id="copy-status" role="status" aria-live="polite">图片已内嵌，可离线复制</span>
  </div>
  <main class="page">
    <article id="article">${articleHtml}</article>
  </main>
  <script>
    const button = document.getElementById("copy-button");
    const status = document.getElementById("copy-status");
    const article = document.getElementById("article");

    async function richCopy() {
      const html = article.innerHTML;
      const plain = article.innerText;
      if (navigator.clipboard && window.ClipboardItem) {
        await navigator.clipboard.write([
          new ClipboardItem({
            "text/html": new Blob([html], { type: "text/html" }),
            "text/plain": new Blob([plain], { type: "text/plain" })
          })
        ]);
        return;
      }

      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(article);
      selection.removeAllRanges();
      selection.addRange(range);
      const copied = document.execCommand("copy");
      selection.removeAllRanges();
      if (!copied) throw new Error("浏览器拒绝复制");
    }

    button.addEventListener("click", async () => {
      button.disabled = true;
      status.textContent = "正在复制……";
      try {
        await richCopy();
        status.textContent = "复制成功，可直接粘贴到公众号";
      } catch (error) {
        status.textContent = "复制失败，请手动全选正文复制";
      } finally {
        button.disabled = false;
      }
    });
  </script>
</body>
</html>
`;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const inputPath = resolve(args.input);
  const outputPath = resolve(args.output);
  if (!existsSync(inputPath)) {
    throw new Error(`Input Markdown not found: ${inputPath}`);
  }

  const markdown = readFileSync(inputPath, "utf8");
  const title =
    markdown.match(/^#\s+(.+)$/m)?.[1]?.replace(/\*\*/g, "").trim() ??
    "微信公众号文章";
  const cta = args["cta-file"] ? readFileSync(resolve(args["cta-file"]), "utf8").replace(/^\uFEFF/, "").trim() : "";
  if (args["cta-file"] && !cta) throw new Error("CTA file must not be empty");
  const articleHtml = renderArticle(markdown, dirname(inputPath), cta);
  const html = documentTemplate(articleHtml, title);

  mkdirSync(dirname(outputPath), { recursive: true });
  writeFileSync(outputPath, html, "utf8");
  process.stdout.write(
    `${JSON.stringify({ input: inputPath, output: outputPath, status: "ok" }, null, 2)}\n`,
  );
}

try {
  main();
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.exit(1);
}
