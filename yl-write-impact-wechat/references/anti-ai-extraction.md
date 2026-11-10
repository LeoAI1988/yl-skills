# 公共写作层来源与更新

## 当前文件范围

| 文件或规则 | 来源与许可 |
| --- | --- |
| `writing-foundation.md` 的原稿、知识回源和回改流程 | YL 维护者依据作者材料优先、完整推理、局部回改等功能需求编写，MIT |
| `anti-ai-rules.md` 的 V 项 | YL 原稿与新增句检查，MIT |
| `anti-ai-rules.md` 的 H 项、词表及启发式 | Human Writing Skill contributors 的 MIT 方法与 YL 适配，保留完整 MIT 许可 |
| `anti-ai-rules.md` 的 K 项 | YL 维护者自制的来源、事实及使用结果检查，MIT。卡兹克为此前机制研究的对象，原文章权利另属原作者 |
| `scripts/check_writing.py` | Human Writing 的 MIT 检查器及 YL 修改，读取文本并输出候选 |
| 来源记录与共享校验代码 | YL 维护者编写，MIT |

Copyright (c) 2026 Human Writing Skill contributors。许可见 [Human Writing MIT](../LICENSES/HUMAN-WRITING-MIT.txt)。固定来源文件指纹见 [来源清单](anti-ai-source-inventory.json)。

## 2026-11-10 的变更

旧版公共层包含 dontbesilent DBS 的有序规则编排和摘编说明。本轮移除 D-01—D-22、E-01—E-05 及其来源摘录，将语义复核连接到现有 V、H、K 规则和作者原稿对照。机器检查器的候选算法继续沿用 MIT 实现。

新稿检查仍覆盖材料依据、原话、推理、段落推进、标题、句法、节奏、术语、引语、标点、结尾以及候选逐项裁决。修辞是否有效由原文语境判断。来源不足和事实矛盾保留具体未决项。

历史版本保留 dontbesilent 的署名及 CC BY-NC 4.0，已发版本的许可继续适用。旧文件可通过 GitHub 的 v3.16.1 版本定位。本轮文件范围以本说明及成员许可为准。[历史版本](https://github.com/LeoAI1988/yl-skills/tree/v3.16.1) [DBS 固定版本许可](https://github.com/dontbesilent2025/dbskill/blob/8b8e33f1ecaed8cee606fe950c4426b525ead314/LICENSE)

## 独立调用

各写作成员携带相同公共文件，构建时核对字节。具体风格成员保留各自的工作流和许可，契诃夫的代码、说明与语料仍分别采用 Apache-2.0、CC BY 4.0、CC BY-SA 4.0。用户输入与输出的权利依据对应内容来源判断。
