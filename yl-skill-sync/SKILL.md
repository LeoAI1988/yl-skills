---
name: yl-skill-sync
description: 整套安装或升级 YL 通用核心，将明确指定的其他 Agent 映射到 Codex 的同一安装；个人配置独立保留，不重复安装多份核心。
---

# 整套安装与更新

先读同级 `yl-toolbox/references/profile.md`。只处理用户指定宿主，不探测后擅自全机铺开。完整集群安装，不挑装模块。

```text
python scripts/sync.py install --source /permanent/yl-toolbox-cluster --target /agent/skills --dry-run
python scripts/sync.py install --source /permanent/yl-toolbox-cluster --target /agent/skills
python scripts/sync.py install --source /new/yl-toolbox-cluster --target /agent/skills --upgrade
python scripts/sync.py map --target /codex/skills --map-target /workbuddy/skills --dry-run
python scripts/sync.py map --target /codex/skills --map-target /workbuddy/skills
python scripts/sync.py status --target /codex/skills --map-target /workbuddy/skills
```

HTTPS 发布包可用 `--source URL --sha256 EXPECTED`，摘要从发布者另行取得；持久缓存、安全解包后预检，不执行下载包附带的任意脚本。本成员使用自身随版审核的安装器。不要把凭据放 URL。

首次存在散装/不同版本/陌生链接会拒绝。先核对能力、备份、分离个人配置、迁移已替代旧入口；不自动吞掉冲突。升级仅替换上次记录且未私改的核心；退出成员归档，不永久删除。用户改过核心先合并审核，不强制覆盖。

链路：唯一长期核心→Codex→WorkBuddy 等。一般安装核心为 Codex 内实体目录；维护者可用根安装器 `--link` 指向长期开发/发行核心。其他宿主只映射 Codex。个人配置、运行资料在核心外，升级不碰。无后台更新，不自动装第三方软件。

文件/链接/哈希通过只证明部署可读；当前对话旧清单可能仍在，刷新或新任务验证真实调用。下载、安装、发布分开报告。
