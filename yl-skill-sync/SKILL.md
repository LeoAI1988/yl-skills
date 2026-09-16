---
name: yl-skill-sync
description: 将公开 Skill 集合下载、安装并同步到本机可用的多个 Agent 入口，支持检查新版本、更新、状态核对和安全卸载。用户要求把一套 Skill 映射到本机所有智能体、从本地目录或 GitHub Release 安装，或检查和更新已安装的 YL Skill 时使用；不覆盖真实目录，不依赖其他工具箱。
---

# YL Skill 同步与安装

## 当前限制（优先于下方旧版命令示例）

URL 安装、下载更新的目录定位与持久化仍有缺口；Grok 薄适配层未可靠检查既有文件所有权，不能据此承诺安全覆盖或卸载。本版暂不执行 URL install、update 或 Grok 适配/卸载命令。下方相关描述保留为旧版接口记录，不代表已验证能力；也没有后台自动检查机制。

安装时由 Agent 从官方 GitHub Releases 下载 ZIP 与 SHA-256 文件，校验并安全解压到长期目录；核实各客户端实际 Skill 路径后，预检冲突并创建共享源链接。不要指向临时下载目录，不删除已有不同版本。无 Grok 冲突且已核实兼容的本地目录映射和只读状态查询可按实际环境使用。


这是一个独立的下载、更新和多 Agent 安装工具。它把同一份 Skill 真源放在公共入口，并根据本机已经存在的 Agent 主目录创建链接；运行时不调用其他工具箱，也不复制用户的凭证、运行数据或私人目录。

## 快速开始

在包含本 Skill 的目录中运行：

```text
python scripts/sync.py install <本地 Skill 目录或 GitHub 仓库/ZIP URL>
python scripts/sync.py update --source <GitHub 仓库或 Release ZIP URL>
python scripts/sync.py status <本地 Skill 目录>
python scripts/sync.py unlink <本地 Skill 目录>
```

第一次安装建议先加 `--dry-run`。`update` 会读取 GitHub 最新 Release 的 ZIP；若没有 Release，则下载仓库默认分支的源码压缩包。传入本地目录时不会联网。

## 安装路由

公共入口始终是：

```text
~/.agents/skills/<skill-name>
```

Codex、GitHub Copilot、Gemini CLI、Cursor、Augment、Roo Code、OpenCode 和 OpenHands 共用这个入口，避免同一 Skill 在多个专属目录重复出现。

只有当对应 Agent 的主目录已经存在时，才创建专属入口：

```text
~/.claude/skills       Claude Code
~/.workbuddy/skills    WorkBuddy
~/.hermes/skills       Hermes Agent
~/.kiro/skills         Kiro
~/.qwen/skills         Qwen Code
~/.cline/skills        Cline
```

本机存在 `~/.grok` 时，脚本会生成 `~/.grok/skills/<skill-name>/SKILL.md` 薄适配层，并在其中标注 `user_invocable: true` 与真源位置。

Windows 使用目录 Junction，Unix-like 系统使用符号链接。目标已有真实目录或文件时只报告冲突，不覆盖；已有指向同一真源的链接可重复执行而不会产生副本。

## 更新和卸载

`update` 下载临时副本，先验证其中存在 `SKILL.md`，再逐项安装。下载目录在操作结束后清理，版本和运行数据不写入 Skill 目录。更新不会删除源目录，也不会触碰目标中指向其他真源的链接。

`status` 显示每个入口是否指向当前真源以及冲突位置。`unlink` 只删除脚本创建的公共入口、专属链接和 Grok 薄适配层，保留源 Skill 与真实目录。

## 安全边界

- 只读取用户明确提供的本地目录，或 GitHub 公共仓库/Release；不读取凭证数据库。
- 不把令牌写入 URL、配置、日志或 Skill 文件；私有仓库应由安装者先在本机完成认证后另行下载。
- 下载内容必须是独立的 Skill 目录或包含多个一级 Skill 目录的集合；不执行下载包中的安装脚本。
- 运行数据、输出文件和宿主账号配置放在 Skill 目录之外。
- 目标是可逆的链接映射；真实目录和不同来源链接需要人工确认后再处理。

## 输出约定

脚本输出 JSON，包含 `source`、发现的 Skill 名称、创建/保留/冲突入口和清理结果，便于其他 Agent 或人工核对。退出码为 0 表示没有阻塞性冲突，1 表示输入或下载失败，2 表示存在未覆盖的真实目录冲突。
