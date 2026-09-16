"""Install the yl cluster into an explicitly chosen Agent skills directory."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shutil


def linked(path):
    return path.is_symlink() or (path.exists() and bool(getattr(path.stat(), 'st_file_attributes', 0) & 0x400))


def contents(root):
    if linked(root) or any(linked(p) for p in root.rglob('*')):
        raise ValueError('Linked paths are not supported')
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True, type=Path,
                        help='The Agent skills directory; all yl skills are installed as children')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    target = args.target.expanduser().resolve()
    if target == source or source in target.parents or target in source.parents:
        parser.error('Target must be separate from the distribution directory')
    catalog = json.loads((source/'cluster.json').read_text(encoding='utf-8'))
    plans = []
    names = set()
    for item in catalog['skills']:
        name = item['name']
        if not re.fullmatch(r'yl-[a-z0-9]+(?:-[a-z0-9]+)*', name) or name in names:
            parser.error('Invalid skill name')
        names.add(name)
        src, dst = source/name, target/name
        if linked(src) or not (src/'SKILL.md').is_file():
            parser.error('Invalid skill source')
        for rel in item['files']:
            if not rel or '\\' in rel or ':' in rel or any(part in ('', '.', '..') for part in rel.split('/')):
                parser.error('Invalid manifest member')
        for path in src.rglob('*'):
            if path.is_symlink() or getattr(path.stat(), 'st_file_attributes', 0) & 0x400:
                parser.error('Linked files are not supported')
        expected = contents(src)
        if expected != item['files']:
            parser.error('Package integrity check failed: '+name)
        if linked(dst):
            parser.error('Linked installation destination is not supported: '+name)
        if dst.exists() and (not dst.is_dir() or contents(dst) != expected):
            parser.error('Different version already exists; back it up or choose another target: '+name)
        plans.append((src,dst,expected))
    if args.dry_run:
        print(json.dumps({'status':'dry_run','skills':[d.name for _,d,_ in plans]},ensure_ascii=False))
        return
    target.mkdir(parents=True, exist_ok=True)
    for src,dst,expected in plans:
        if not dst.exists():
            shutil.copytree(src,dst)
        if contents(dst) != expected:
            raise RuntimeError('Installed bytes differ: '+dst.name)
    print(json.dumps({'status':'installed','skills':[d.name for _,d,_ in plans],
                      'next':'Reload the Agent skills list'},ensure_ascii=False))


if __name__ == '__main__':
    main()
