# 数据接入与生成记录

## 个人配置

个人 profile 的 `writing.data_driven.config_file` 指向外置 JSON。未设置时读取 profile 同目录的 `writing/data-driven.json`。以下为结构示意，各值由安装者的实际材料填写。

```json
{
  "accounts": [
    {"account": "账号标识", "review_glob": "本地复盘目录/*/review.json"}
  ],
  "sales_glob": "本地成交目录/*/成交索引_20260101.json",
  "catalog_glob": "本地复盘目录/*/merged_data.json",
  "links_file": "个人目录/verified-links.json",
  "work_root": "个人文案项目目录"
}
```

目录 glob 只在安装者明确配置的范围内读取。每次调用选择采集时间最新的复盘文件，成交索引用路径里的 `YYYYMMDD` 日期，正文候选目录用 `generated_at`。同一最新时点有不同内容时明确选定源。全部候选输入先读成功才更新 `latest.json`，写入通过临时文件替换。源文件保持只读。

## 支持的输入

- 复盘 JSON 包含 `meta.captured_at`、`meta.from`、`meta.to`、`posts`。作品字段包含 `publication_id`、`date`、`published_at`、`title`、`public`、`mature`、`content_type`、`views`、`completion_pct`、`follows`、`three_sec_pct` 或 `fast_flip_pct`、`duration_seconds`、`watch_seconds`。百分数使用 0–100 尺度，缺失使用 null。
- 成交索引为数组，包含 `title`、`account`、`published`、`amount`、`window`、`manuscript`、`evidence`。金额是该证据展示值。可用 `sales_period_type` 明确其成交窗口含义，缺省保留未知或发布筛选的边界。
- 可选的正文候选目录含 `posts` 与按发布 ID 索引的 `transcripts`。读取 `source_path`、`source_sha256`、`match_evidence`，全部先作为关联候选。每篇需继续回读原文。正文引用路径、哈希和数据归属冲突优先修正。
- 正文支持成交汇总稿中首个分隔线前的段落，以及 `## 主文本` 章节。正文结构不同的材料先读原文，确认正确范围后通过关联文件或直接引用位置使用。短稿也完整保留。

其他数据格式先读取字段定义，形成同等含义的本地派生输入，并保存原始文件路径和映射依据。新增表列不可静默充当同名指标。脚本读取失败时报告具体源，修正该输入映射后继续。

## 核实关联

`verified-links.json` 是数组，每条包含下列字段。

```json
{
  "account": "账号标识",
  "publication_id": "真实平台发布ID",
  "path": "已核对正文路径",
  "source_sha256": "正文文件SHA256",
  "status": "verified",
  "evidence": "明确的对应依据和原始证据位置",
  "sales_id": "可选，来自证据包的成交记录ID"
}
```

核实记录可以来自稳定 ID、平台原稿、可核对的发布记录、逐帧或原声对照、用户确认，以及已有可追溯人工核对记录。标题和时间帮助定位。仅有自动标题匹配的记录继续保持候选。确认误配时使用 `status=rejected` 并记录实际差异。

原稿哈希变化后该关联重新进入核对。关联缺口按条处理，其他可用母稿继续写作。成交稿的具体版本待定时，其销售证据继续保留，在版本确定前使用已核定的其他母稿作为结构依据。

## 命令

在技能目录运行，Python 仅使用标准库，并调用整套安装中的现有排名脚本。

```text
python -B scripts/evidence.py prepare --profile PROFILE
python -B scripts/evidence.py novelty --profile PROFILE --draft DRAFT.md --plan PLAN.json
python -B scripts/evidence.py register --profile PROFILE --draft DRAFT.md --plan PLAN.json
python -B scripts/evidence.py feedback --profile PROFILE --event EVENT.json
```

也可显式使用 `--config CONFIG.json`。脚本产物位于 `work_root` 的 `evidence`、`history/drafts`、`history/feedback` 和 `latest.json`。模型的模式卡、待发表稿与依据保存在同一项目的清晰子目录中。

## 结果解释

证据包保留所有账号的完整播放候选、成交索引、正文关联候选、已核实关联、来源哈希与历史稿。传播评分按账号 × 发布月 × 时长区间生成，满 48 小时等成熟条件由已核复盘输入给出。每组带样本数，Agent 继续检查观察窗和具体受众，必要时重选可比组。

`snapshot_fingerprint` 标识实际输入字节集合。来源变动会改变指纹，生成历史的增加则更新当前证据包。正文不会因刷新数据被自动改写。订单明细、买家身份和联系方式无需进入写作证据包。

`novelty` 比对成交源稿、生成历史，以及 `--plan` 中引用的原文段落，给出连续 12 字片段重合率与定位示例。该数值只能定位沿用语句。用原话组装的稿件出现重合很正常，需要结合新问题、新信息、论述关系判断。它无法自动证明原创性、声音相似度或去 AI 味。

每个 `source_spans` 条目包含 `path`、`sha256`、`lines`，行号为原文件的一基起止行号，另可保存采用的原句及编辑说明。`register` 核对文件哈希与范围，源稿变动后先更新真实依据。草稿正文哈希相同的重复登记复用已有记录。数据准备、草稿登记与反馈登记使用操作系统文件锁保护本地状态，并发占用时可在当前操作结束后重试。

发布回流事件包含 `draft_id`、`account`、`publication_id`、`published_draft_sha256` 和 `evidence`。发布时改过正文就记录实际发布稿哈希，并在证据里注明改动及来源。一次发布对应一个已核定版本，冲突先核对。后续准备证据时按账号和发布 ID 读取结果，视频成交只接入有对应依据的记录。
