# 语料检索与权利边界

## 位置

本 Skill 自带 `corpus/`，整目录安装即可使用，无须作者的 Codex、其他 Skill 或研究项目。Python 3.10+ 为可选检索与校验依赖；纯写作可直接读取工作流与运行参数。

脚本按显式 `--corpus-root`、环境变量 `YL_CHEKHOV_CORPUS_ROOT`、本 Skill 内的 `corpus/` 选择位置。显式配置错误时直接报错，不回退读取其他目录；不联网、不下载、不修改语料。

## 俄文原著

本包包含上游稳定研究线 12 部作品的俄文 clean TXT 全文，保持上游字节与行号，另有作品、作者、Wikisource 转录署名、根页面固定修订、版本范围、来源和 SHA-256 清单。它不是契诃夫全集。部分作品尚未完成印本校勘；根页面的修订号不代表所有章节页面具有同一修订号。引用以本地 clean 字节及行号定位，不能夸大为已逐页校勘版本。

为保持单目录安装，未纳入重复 raw EPUB、阅读 Markdown、研究实验记录和研究来源全文。`assets/runtime-profile.json` 的 `source_manifest_sha256` 是上游研究清单的来源指纹，不是本包中的文件路径，也不是运行依赖。普通写作不加载原著全文或研究卡。

引用时给出作品名、`work_id`、`source_id`、语言、`fixed_revision_url` 和 clean 文本行号。研究卡或摘要不能替代全文。语料及派生层采用 CC BY-SA 4.0，再分发须保留署名、来源和许可，见 [NOTICE.md](../NOTICE.md)。

## 中文译本

本包中文出版译本全文数为 0。原著公版不意味着现代中文译文也能分发。使用者只有在拥有合法副本或明确再利用许可时，才可在本地导入；本地导入不会把译文变成可公开再分发内容。用户材料、授权译本与生成稿都放在 Skill 目录外，不进入更新包。

没有授权中文全文时：

- 可以引用并翻译短小俄文片段，但必须标明“自行直译”。
- 可以做内容概述，但不得放进引号冒充原话。
- 不得写成汝龙、朱逸森、焦菊隐等出版译者的原文。

如使用者有权本地检索译本，可先把本包 `corpus/` 复制到自己的外部数据目录，在其 `corpus-manifest.json` 的 `translations.included` 添加记录，每条至少含 `work_id`、`source_id`、`work_title`、`language: "zh"` 与相对于该语料目录的 UTF-8 `text_path`，并同步 `included_count`。通过 `--corpus-root` 指向该目录。此操作不会授予译文再分发权，公共发行包的 `verify_install.py` 仍要求中文全文数为 0。不要在共享 Skill 中保存该目录、译文、账户或授权文件。

## 命令

```powershell
python -B -X utf8 "<Skill>/scripts/verify_install.py"
python -B -X utf8 "<Skill>/scripts/search_corpus.py" --list
python -B -X utf8 "<Skill>/scripts/search_corpus.py" --language ru --query "Червяков" --context 1 --limit 3 --json
python -B -X utf8 "<Skill>/scripts/search_corpus.py" --language zh --query "关键词"
```

检索是逐字、忽略大小写的匹配，不是语义搜索。俄文屈折词形可能不同；无结果时先检查安装、语言和词形，再判断原文确实没有该词。
