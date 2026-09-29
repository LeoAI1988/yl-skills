---
name: yl-knowledge-build
description: 新建本地知识库及阅读文件夹体系，或接入用户现有知识库；首次设置时提供沿用现有结构与创建推荐结构两个选择。
---

# 构建知识库

先读同级 `yl-knowledge/references/contract.md` 和 `yl-toolbox/references/profile.md`。已有配置直接复用；新用户在“接入现有结构”和“新建推荐结构”中选择，明确目标位置，不默认迁移现有资料。

通用工具（Python 3.10+，标准库）：
`python -B ../yl-knowledge/scripts/knowledge.py --profile PROFILE init --root ROOT --mode new`
或 `--mode adopt`。`new` 要求目标为空；`adopt` 不搬动、不覆盖既有文件，先按角色填好个人 `paths`。个人配置已经存在时拒绝覆盖。

推荐入口：我的思想体系、我的作品全集、选题库、表达资产、知识原子、私人档案、系统资料。思想树使用用户自己的领域与措辞；不把示例领域固定给所有人。不建空的业务子仓库。

迁移是独立的受控步骤：先列原位置→新位置、依赖、冲突、恢复方式；有明确迁移授权后执行，核对哈希与数量。同一正文不复制为多个正式对象。新建结果必须能打开原文，不只是空目录。
