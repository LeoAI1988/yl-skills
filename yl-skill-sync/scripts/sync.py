#!/usr/bin/env python3
"""Download, update and map a Skill collection to local Agent entry points."""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

PUBLIC_COMPATIBLE = {
    "codex", "github-copilot", "gemini", "cursor", "augment",
    "roo-code", "opencode", "openhands",
}
SPECIALIZED = {
    ".claude": "Claude Code", ".workbuddy": "WorkBuddy",
    ".hermes": "Hermes Agent", ".kiro": "Kiro", ".qwen": "Qwen Code",
    ".cline": "Cline",
}


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def skill_dirs(root: Path) -> list[Path]:
    root = root.expanduser().resolve()
    if (root / "SKILL.md").is_file():
        return [root]
    found = sorted(p for p in root.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())
    if not found:
        raise ValueError(f"没有找到 SKILL.md：{root}")
    return found


def frontmatter(skill: Path) -> tuple[str, str]:
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"缺少 frontmatter：{skill}")
    block = text.split("---", 2)[1]
    values: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip().strip('"\'')
    name = values.get("name") or skill.name
    description = values.get("description", "")
    if not name or any(c in name for c in "/\\"):
        raise ValueError(f"Skill 名称无效：{skill}")
    return name, description


def resolve_source(value: str) -> tuple[Path, tempfile.TemporaryDirectory | None]:
    candidate = Path(value).expanduser()
    if candidate.exists():
        return candidate, None
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"本地路径不存在或 URL 无效：{value}")
    temp = tempfile.TemporaryDirectory(prefix="yl-skill-sync-")
    destination = Path(temp.name)
    request = urllib.request.Request(value, headers={"User-Agent": "yl-skill-sync"})
    if value.lower().endswith(".zip"):
        archive = destination / "source.zip"
        with urllib.request.urlopen(request, timeout=60) as response:
            archive.write_bytes(response.read())
    else:
        path = parsed.path.strip("/").split("/")
        if len(path) < 2 or parsed.netloc.lower() != "github.com":
            raise ValueError("仓库 URL 必须是 GitHub 仓库或 ZIP URL")
        owner, repo = path[:2]
        repo = repo.removesuffix(".git")
        api = urllib.request.Request(
            f"https://api.github.com/repos/{owner}/{repo}/releases/latest",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "yl-skill-sync"},
        )
        try:
            with urllib.request.urlopen(api, timeout=30) as response:
                release = json.load(response)
            assets = [a for a in release.get("assets", []) if a.get("name", "").endswith(".zip")]
            download_url = assets[0]["browser_download_url"] if assets else f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/main"
        except Exception:
            download_url = f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/main"
        archive = destination / "source.zip"
        with urllib.request.urlopen(urllib.request.Request(download_url, headers={"User-Agent": "yl-skill-sync"}), timeout=120) as response:
            archive.write_bytes(response.read())
    with zipfile.ZipFile(archive) as package:
        package.extractall(destination / "extracted")
    extracted = destination / "extracted"
    if list(extracted.rglob("SKILL.md")):
        return extracted, temp
    raise ValueError("下载包中没有可安装的 Skill")


def link(target: Path, source: Path, dry_run: bool, created: list[str], conflicts: list[str], kept: list[str]) -> None:
    target = target.expanduser()
    source = source.resolve()
    if target.is_symlink() or getattr(target, "is_junction", lambda: False)() or target.exists():
        try:
            if target.resolve() == source:
                kept.append(str(target))
                return
        except OSError:
            pass
        conflicts.append(str(target))
        return
    if dry_run:
        created.append(str(target))
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.symlink_to(source, target_is_directory=True)
    except (OSError, NotImplementedError):
        if os.name != "nt":
            raise
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(target), str(source)], capture_output=True, text=True)
        if result.returncode:
            raise OSError(result.stderr.strip() or result.stdout.strip() or "无法创建 Windows Junction")
    created.append(str(target))


def grok_adapter(target: Path, source: Path, name: str, description: str, dry_run: bool, created: list[str], conflicts: list[str]) -> None:
    if target.exists() and not target.is_file():
        conflicts.append(str(target))
        return
    content = f"---\nname: {name}\ndescription: {description}\nuser_invocable: true\n---\n\n真源 Skill 位于：{source / 'SKILL.md'}\n请读取真源并按其规则执行。此文件是 Grok 适配层，不是另一份副本。\n"
    if dry_run:
        created.append(str(target))
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_text(encoding="utf-8") == content:
        return
    target.write_text(content, encoding="utf-8")
    created.append(str(target))


def install(root: Path, dry_run: bool) -> dict:
    skills = skill_dirs(root)
    home = Path.home()
    created: list[str] = []
    conflicts: list[str] = []
    kept: list[str] = []
    names: list[str] = []
    for skill in skills:
        name, description = frontmatter(skill)
        names.append(name)
        link(home / ".agents" / "skills" / name, skill, dry_run, created, conflicts, kept)
        for host_dir in SPECIALIZED:
            if (home / host_dir).exists():
                link(home / host_dir / "skills" / name, skill, dry_run, created, conflicts, kept)
        if (home / ".grok").exists():
            grok_adapter(home / ".grok" / "skills" / name / "SKILL.md", skill, name, description, dry_run, created, conflicts)
    return {"source": str(root.resolve()), "skills": names, "created": created, "kept": kept, "conflicts": conflicts, "dry_run": dry_run}


def status(root: Path) -> dict:
    skills = skill_dirs(root)
    home = Path.home()
    entries = []
    for skill in skills:
        name, _ = frontmatter(skill)
        targets = [home / ".agents" / "skills" / name]
        targets += [home / d / "skills" / name for d in SPECIALIZED if (home / d).exists()]
        targets += [home / ".grok" / "skills" / name / "SKILL.md"] if (home / ".grok").exists() else []
        for target in targets:
            if not target.exists() and not target.is_symlink():
                state = "missing"
            elif target.is_file():
                state = "adapter" if ".grok" in str(target) else "conflict"
            else:
                state = "linked" if target.resolve() == skill.resolve() else "conflict"
            entries.append({"skill": name, "target": str(target), "state": state})
    return {"source": str(root.resolve()), "entries": entries}


def unlink(root: Path, dry_run: bool) -> dict:
    skills = skill_dirs(root)
    home = Path.home()
    removed: list[str] = []
    kept: list[str] = []
    for skill in skills:
        name, _ = frontmatter(skill)
        targets = [home / ".agents" / "skills" / name]
        targets += [home / d / "skills" / name for d in SPECIALIZED if (home / d).exists()]
        targets += [home / ".grok" / "skills" / name / "SKILL.md"] if (home / ".grok").exists() else []
        for target in targets:
            if not target.exists() and not target.is_symlink():
                continue
            if target.is_file() and ".grok" in str(target):
                if dry_run:
                    removed.append(str(target))
                else:
                    target.unlink(); removed.append(str(target))
            elif (target.is_symlink() or getattr(target, "is_junction", lambda: False)()) and target.resolve() == skill.resolve():
                if dry_run:
                    removed.append(str(target))
                else:
                    target.unlink(); removed.append(str(target))
            else:
                kept.append(str(target))
    return {"source": str(root.resolve()), "removed": removed, "kept": kept, "dry_run": dry_run}


def main() -> int:
    parser = argparse.ArgumentParser(description="YL Skill 下载、更新和多 Agent 同步")
    sub = parser.add_subparsers(dest="command", required=True)
    install_parser = sub.add_parser("install")
    install_parser.add_argument("source")
    install_parser.add_argument("--dry-run", action="store_true")
    update_parser = sub.add_parser("update")
    update_parser.add_argument("--source", required=True)
    update_parser.add_argument("--dry-run", action="store_true")
    status_parser = sub.add_parser("status")
    status_parser.add_argument("source")
    unlink_parser = sub.add_parser("unlink")
    unlink_parser.add_argument("source")
    unlink_parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    temp = None
    try:
        if args.command == "update":
            root, temp = resolve_source(args.source)
            result = install(root, args.dry_run)
        else:
            root = Path(args.source).expanduser()
            if args.command == "install":
                result = install(root, args.dry_run)
            elif args.command == "status":
                result = status(root)
            else:
                result = unlink(root, args.dry_run)
        emit(result)
        return 2 if result.get("conflicts") else 0
    except (OSError, ValueError, urllib.error.URLError, zipfile.BadZipFile) as error:
        emit({"error": str(error)})
        return 1
    finally:
        if temp is not None:
            temp.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
