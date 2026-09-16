# yl-skill-sync

独立的 YL Skill 下载、更新和多 Agent 安装器。它把一份 Skill 真源映射到公共 `~/.agents/skills`，并按本机已存在的宿主目录补充专属链接。

```text
python scripts/sync.py install <目录或 GitHub URL> --dry-run
python scripts/sync.py install <目录或 GitHub URL>
python scripts/sync.py update --source <仓库或 ZIP URL>
python scripts/sync.py status <目录>
python scripts/sync.py unlink <目录>
```

仅使用 Python 标准库；脚本不会调用其他 Skill，不执行下载包里的脚本，也不会覆盖真实目录。
