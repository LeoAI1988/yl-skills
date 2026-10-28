---
name: yl-knowledge
description: YL 知识管理总入口。构建知识库、同步笔记、导入本人材料或采集本人新文稿时，协调归档、蒸馏、去重、表达、体系和验收；知识检索只读，不启动入库。
---

# YL 知识管理

整套安装，按职责分工，按任务加载。用户说“同步”“导入”“整理进知识库”，默认授权本地完整处理，不要求再说“蒸馏”。外部账号写入、发布、收费服务和后台监控不是此授权的一部分。

先完整读取 [共同规则](references/contract.md) 和 [个人配置约定](../yl-toolbox/references/profile.md)，定位知识库与当前未完成队列。已有库先读其导航和规则；不要为新 Skill 另建平行知识库。初始化需要选择沿用现有结构或新建推荐结构，进入 `yl-knowledge-build`。

## 调度

所有成员位于同级目录，调用前读取其完整 SKILL.md。步骤不受总工具箱“最多两个辅助成员”限制，但不加载本次无关成员。

1. 来源接收：云笔记用 `yl-knowledge-sync`，本地文件用 `yl-knowledge-import`；平台由 `yl-media` 采集后交接。任务包含本地新增文稿时，先运行已核实的 `local_hooks.local_source_discovery`（若已配置），或本地导入成员的发现器；再把无边车新稿、变更稿与原有待处理队列合并检查。
2. `yl-knowledge-ingest`：原文、归属、版本、重复与正式位置。
3. `yl-knowledge-distill` 与 `yl-knowledge-expressions`：读完整原文，先查旧对象再提炼；不能用摘要代替原话。
4. `yl-knowledge-organize`：更新思想树、作品关系和完整论述，保留跨领域关联。
5. 按 `yl-knowledge-search/references/retrieval.md` 更新来源清单和全文/语义索引；无新原子但有新正文也必须覆盖。执行 index、embed、status；没有语义环境明确记录降级，不自动使用收费接口或上传正文。
6. `yl-knowledge-obsidian`：已配置时刷新阅读；未安装不阻断 Markdown 交付。
7. `yl-knowledge-check`：以本次材料清单和未完成旧项验收，不以文件数、空扫描队列或无报错替代完成证明。

只查询用 `yl-knowledge-search`；纯指标更新用 `yl-knowledge-review-sync`。正文哈希未变不重复提炼；新增或修订正文必须完成上述流程。中断保留进度，下次从未完成处继续，不自动创建定时任务。

本版脚本负责确定性的来源登记、变更检测、原句验证、状态和检索；语义判断仍由执行本 Skill 的 Agent 完成。没有调用模型的脚本不能声称自己已经自动做过语义蒸馏。

交付用普通话说明：新增多少份、已处理多少份、合并或新建了什么、还有什么未完成。安装验证不等于实际云端同步或历史全库蒸馏。
