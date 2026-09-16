# yl-skill-sync

## 当前限制（优先于下方旧版命令示例）

URL 安装、下载更新的目录定位与持久化仍有缺口；Grok 薄适配层未可靠检查既有文件所有权，不能据此承诺安全覆盖或卸载。本版暂不执行 URL install、update 或 Grok 适配/卸载命令。下方相关描述保留为旧版接口记录，不代表已验证能力；也没有后台自动检查机制。

安装时由 Agent 从官方 GitHub Releases 下载 ZIP 与 SHA-256 文件，校验并安全解压到长期目录；核实各客户端实际 Skill 路径后，预检冲突并创建共享源链接。不要指向临时下载目录，不删除已有不同版本。无 Grok 冲突且已核实兼容的本地目录映射和只读状态查询可按实际环境使用。


独立的 YL Skill 下载、更新和多 Agent 安装器。它把一份 Skill 真源映射到公共 `~/.agents/skills`，并按本机已存在的宿主目录补充专属链接。

```text
python scripts/sync.py install <目录或 GitHub URL> --dry-run
python scripts/sync.py install <目录或 GitHub URL>
python scripts/sync.py update --source <仓库或 ZIP URL>
python scripts/sync.py status <目录>
python scripts/sync.py unlink <目录>
```

仅使用 Python 标准库；脚本不会调用其他 Skill，不执行下载包里的脚本，也不会覆盖真实目录。
