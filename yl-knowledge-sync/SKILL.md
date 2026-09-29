---
name: yl-knowledge-sync
description: 将配置的 Get 或其他笔记来源同步到本地，并自动衔接归档、蒸馏、去重、表达和思想体系更新；不止于下载，不修改云端笔记。
---

# 来源同步

先读同级 `yl-knowledge/references/contract.md`、`yl-toolbox/references/profile.md`，再读 [连接器](references/connectors.md)。用户请求同步就要走完整知识流程，不要求用户知道“蒸馏”。

Get：`python -B scripts/getnote_sync.py --profile PROFILE`。API 凭证仅从环境变量读取。配置库名必须精确匹配实时列表，分页到尽头，保留字符串 ID。原始逐字稿优先于 AI 摘要；新正文写入不可覆盖的版本目录。库内身份不等于作者归属。

已有库若配置了成熟的 `getnote_sync` 本地 hook，可按其现有镜像和提升台账继续，避免首次重抓和重新建库；hook 只负责已明确的阶段。无论使用哪个连接器，都必须登记本次材料并交回 `yl-knowledge` 完成后续步骤，核对原有未完成队列。

Notion、飞书或其他来源使用宿主已授权连接器或用户导出。列清实际支持的分页、版本、原文与权限；没有验证过的原生接口不得冒称可用。同步无权删除、改写、重新分配云端笔记或开通付费服务。

输出先列同步取得的新增/变更/未变及未完成项，再继续蒸馏。脚本输出 `needs_semantic_processing` 是交接信号，不是最终成功。
