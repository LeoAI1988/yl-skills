# 来源、许可与改动声明

本项改编自 **Chekhov Deep Writing v1.0.0**。方法、运行参数与研究解释由上游项目作者提供；`yl-` 是本工具箱的安装命名，不构成对上游方法或文学作品的重新署名。

- 原始及改编代码：Apache-2.0，见 [许可证全文](LICENSES/Apache-2.0.txt)。
- 上游项目作者的工作流、机制卡和解释材料，以及本版新增说明：CC BY 4.0，见 [许可证全文](LICENSES/CC-BY-4.0.txt)。
- 俄文原作作者：Антон Павлович Чехов / Anton Chekhov（1860–1904）。底层文学作品为公版。
- 转录贡献者：Russian Wikisource contributors。转录及 clean 派生层按上游许可声明以 CC BY-SA 4.0 分发，见 [许可证全文](LICENSES/CC-BY-SA-4.0.txt)、[逐作品署名和来源](corpus/source-registry.csv) 以及 [Wikimedia 内容许可条款](https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use#7._Licensing_of_Content)。保留同方式共享要求。

上游的多许可声明全文保存在 [LICENSE](LICENSE)。其中第 4 项讨论 Project Gutenberg 研究快照；本版不包含此研究快照或这些研究来源全文，不将其算作本版载荷。

## 本版修改

1. 安装名称与调用提示改为 `yl-chekhov-deep-writing`。
2. 语料由发行包的外置同级目录改为 Skill 内 `corpus/`；取消对作者已有 Codex 语料目录的发现依赖。
3. 12 部俄文 clean 正文原字节保留；来源表仅提取公开书目信息、权利信息和定位信息，删除项目流程、旧项目相对路径与实验记录字段。
4. 不携带上游研究树、实验结果、重复阅读版和 raw EPUB；本包清单明确这些排除项，不声称包含完整上游研究工程。
5. 检索结果增加固定根修订 URL；新增独立安装说明和便携验证脚本。
6. 强调使用者原稿、表达和思想链优先于写作机制。

`references/source-snapshot.json` 只记录上游通用来源名称、相对文件名和原文件 SHA-256。`chekhov-deep-writing` 对应上游可安装 Skill 根，`chekhov-deep-writing-release` 对应上游 v1.0.0 发行包根。本版新增和修改文件可结合上述改动声明审查；快照不包含作者机器地址。

更新比对范围：主来源 `chekhov-deep-writing` 跟踪完整可安装 Skill；发行包来源 `chekhov-deep-writing-release` 使用 `tracking_scope: listed_files`，只比对快照中列出的 42 个公开必要来源文件。不递归扫描发行包的其他文件，尤其不检查未纳入本包的研究实验树新增内容。
