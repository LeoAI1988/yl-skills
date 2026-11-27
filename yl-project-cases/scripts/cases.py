"""Archive and search local Markdown project cases."""
import argparse
from dataclasses import dataclass
from datetime import date
import json
import ntpath
import os
from pathlib import Path, PureWindowsPath
import re
import sys
import tempfile
from urllib.parse import quote
from uuid import UUID


ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
INVALID_FOLDER = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
SCALARS = ("id", "title", "category", "status", "updated")
LISTS = ("tags", "uses", "threads", "sources")


def reserved_name(name):
    if hasattr(ntpath, "isreserved"):
        return ntpath.isreserved(name)
    return PureWindowsPath(name).is_reserved()


@dataclass
class Card:
    path: Path
    fields: dict
    body: str


def read_card(path):
    raw = path.read_bytes()
    lines = raw.decode("utf-8-sig").splitlines()
    if not lines or lines[0] != "---" or "---" not in lines[1:]:
        raise ValueError("缺少 frontmatter")
    boundary = lines.index("---", 1)
    fields = {}
    for line in lines[1:boundary]:
        if not line.strip():
            continue
        field, separator, value = line.partition(":")
        if not separator or not re.fullmatch(r"[a-z][a-z0-9_-]*", field) or field in fields:
            raise ValueError(f"无效或重复字段 {field!r}")
        fields[field] = json.loads(value)
    for name in SCALARS:
        value = fields.get(name)
        if not isinstance(value, str) or not value.strip() or value != value.strip() or not value.isprintable():
            raise ValueError(f"{name} 必须是非空的单行字符串")
    for name in LISTS:
        values = fields.get(name)
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value.strip() or not value.isprintable()
            for value in values
        ):
            raise ValueError(f"{name} 必须是字符串数组")
    if not ID.fullmatch(fields["id"]) or reserved_name(fields["id"]):
        raise ValueError("id 必须为可作文件名的英文小写 kebab-case")
    category = fields["category"]
    if INVALID_FOLDER.search(category) or category.endswith(".") or reserved_name(category):
        raise ValueError("category 必须为可作普通分类目录名的单个名称")
    if date.fromisoformat(fields["updated"]).isoformat() != fields["updated"]:
        raise ValueError("updated 必须是 YYYY-MM-DD")
    for thread in fields["threads"]:
        if str(UUID(thread)) != thread.lower():
            raise ValueError(f"非标准聊天 UUID {thread!r}")
    for source in fields["sources"]:
        if "\\" in source or not (Path(source).is_absolute() or PureWindowsPath(source).is_absolute()):
            raise ValueError(f"证据须为正斜杠绝对本地路径 {source!r}")
    body = "\n".join(lines[boundary + 1:]).strip()
    if not body:
        raise ValueError("缺少案例正文")
    return Card(path, fields, body), raw


def locate_root(args):
    if args.root:
        return args.root.expanduser().resolve()
    profile = args.profile or os.environ.get("YL_PROFILE") or Path.home() / ".config/yl-toolbox/profile.json"
    config = json.loads(Path(profile).expanduser().read_text(encoding="utf-8-sig"))
    knowledge = Path(config["knowledge_root"]).expanduser()
    projects = Path(config["paths"]["projects"])
    if not knowledge.is_absolute() or projects.anchor or ".." in projects.parts or projects == Path("."):
        raise ValueError("knowledge_root 须为绝对路径，paths.projects 须为库内相对目录")
    root = (knowledge / projects / "案例").resolve()
    if not root.is_relative_to(knowledge.resolve()):
        raise ValueError("案例目录在知识库之外")
    return root


def scan(root, check_evidence=False):
    cards = {}
    errors = []
    for path in sorted(root.glob("*/*.md")):
        if not path.is_file():
            continue
        try:
            if not path.resolve().is_relative_to(root):
                raise ValueError("案例链接指向案例目录之外")
            card, _ = read_card(path)
            identity = card.fields["id"]
            if identity in cards:
                raise ValueError(f"重复案例 ID {identity}，另一个位置为 {cards[identity].path}")
            cards[identity] = card
            if path.name != identity + ".md" or path.parent.name != card.fields["category"]:
                errors.append(f"{path}：文件名或分类目录与卡片字段不一致")
            if check_evidence:
                errors.extend(f"{path}：证据不存在 {source}" for source in missing_evidence(card))
        except (OSError, ValueError) as error:
            errors.append(f"{path}：{error}")
    return cards, errors


def missing_evidence(card):
    return [source for source in card.fields["sources"] if not Path(source).exists()]


def archive(root, source):
    card, raw = read_card(source)
    missing = missing_evidence(card)
    if missing:
        raise ValueError("证据不存在 " + "、".join(missing))
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".case-write.lock"
    try:
        lock.mkdir()
    except FileExistsError:
        raise ValueError(f"另一次归档持有锁 {lock}。如上次异常退出，核实无写入进程后移除此空目录再试。") from None
    try:
        cards, errors = scan(root)
        if errors:
            raise ValueError("\n".join(errors))
        fields = card.fields
        target = root / fields["category"] / (fields["id"] + ".md")
        existing = cards.get(fields["id"])
        if existing and existing.path != target:
            raise ValueError(f"ID 已归在 {existing.path}，请核对分类迁移及旧引用")
        if not target.resolve().is_relative_to(root):
            raise ValueError("目标路径位于案例目录之外")
        if target.exists():
            if raw == target.read_bytes():
                return "unchanged", target
            if fields["updated"] < existing.fields["updated"]:
                raise ValueError("输入卡片早于现有版本")
        target.parent.mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".tmp", delete=False) as stream:
            temp_path = Path(stream.name)
        try:
            temp_path.write_bytes(raw)
            temp_path.replace(target)
        finally:
            temp_path.unlink(missing_ok=True)
        return ("updated" if existing else "created"), target
    finally:
        lock.rmdir()


def search_score(card, words):
    fields = card.fields
    primary = f"{fields['id']} {fields['title']}".casefold()
    metadata = json.dumps(fields, ensure_ascii=False).casefold()
    body = card.body.casefold()
    weights = [5 if word in primary else 3 if word in metadata else 1 if word in body else 0
               for word in words]
    return sum(weights) if all(weights) else -1


def print_index(cards):
    print("# 项目案例索引")
    category = None
    for card in sorted(cards, key=lambda item: (item.fields["category"], item.fields["id"])):
        fields = card.fields
        if category != fields["category"]:
            category = fields["category"]
            print(f"\n## {category}\n")
        title = fields["title"].replace("[", r"\[").replace("]", r"\]")
        path = quote(card.path.as_posix(), safe="/:")
        print(f"- [{title}]({path}) · {fields['status']} · {fields['updated']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="案例目录")
    parser.add_argument("--profile", type=Path, help="YL 个人配置")
    commands = parser.add_subparsers(dest="command", required=True)
    search = commands.add_parser("search")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--category")
    search.add_argument("--limit", type=int, default=10)
    commands.add_parser("index")
    commands.add_parser("verify")
    commands.add_parser("archive").add_argument("input", type=Path)
    args = parser.parse_args()
    try:
        root = locate_root(args)
        if args.command == "archive":
            outcome, path = archive(root, args.input)
            print(json.dumps({"outcome": outcome, "path": path.as_posix()}, ensure_ascii=False))
            return 0
        if not root.is_dir():
            raise ValueError(f"案例目录不存在 {root}")
        cards, errors = scan(root, check_evidence=args.command == "verify")
        if args.command == "verify":
            print(json.dumps({"cases": len(cards), "errors": errors}, ensure_ascii=False, indent=2))
        elif errors:
            raise ValueError("\n".join(errors))
        elif args.command == "index":
            print_index(cards.values())
        elif args.command == "search":
            if args.limit < 1:
                raise ValueError("--limit 须为正整数")
            words = args.query.casefold().split()
            matches = []
            for card in cards.values():
                if args.category and card.fields["category"] != args.category:
                    continue
                score = search_score(card, words)
                if score >= 0:
                    matches.append((score, card))
            matches.sort(key=lambda pair: (pair[0], pair[1].fields["updated"], pair[1].fields["id"]), reverse=True)
            print(json.dumps([{"path": card.path.as_posix(), **card.fields}
                              for _, card in matches[:args.limit]], ensure_ascii=False, indent=2))
        return int(bool(errors))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

