"""Read-only comparison of recorded daily sources; never copies or updates Skills."""
from pathlib import Path
import argparse
import fnmatch
import json
import os
from library import ROOT, TEXT_SUFFIXES, read_json, digest, relative_file

def compare(base, source):
    before = source['files']
    if any(not relative_file(n) for n in before):
        raise ValueError('Invalid relative path in source snapshot')
    if not base.is_dir():
        return {'status': 'source_missing', 'added': [], 'changed': [], 'removed': []}
    ignored = {'.git', '__pycache__', 'node_modules', '.venv'}
    after = {}
    for p in base.rglob('*'):
        if any(part in ignored for part in p.relative_to(base).parts) or not p.is_file():
            continue
        name = p.relative_to(base).as_posix()
        if any(fnmatch.fnmatch(name, pattern) for pattern in source.get('snapshot_ignored_patterns', [])):
            continue
        if name in before or (source.get('tracking_scope') != 'listed_files'
                              and p.suffix.lower() in TEXT_SUFFIXES
                              and not p.name.startswith('.env')):
            after[name] = digest(p.read_bytes())
    changes = {
        'added': sorted(after.keys() - before.keys()),
        'changed': sorted(n for n in before.keys() & after.keys() if before[n] != after[n]),
        'removed': sorted(before.keys() - after.keys())
    }
    return {'status': 'changed' if any(changes.values()) else 'unchanged', **changes}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default_home = Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex')))
    parser.add_argument('--skills-root', type=Path, default=default_home/'skills')
    parser.add_argument('--source', action='append', default=[], metavar='NAME=PATH')
    args = parser.parse_args()
    overrides = {}
    for item in args.source:
        name, sep, path = item.partition('=')
        if not sep or not name or not path:
            parser.error('--source requires NAME=PATH')
        overrides[name] = Path(path).expanduser()
    results = []
    for snapshot in sorted(ROOT.glob('yl-*/references/source-snapshot.json')):
        value = read_json(snapshot)
        for source in value['sources']:
            name = source['name']
            base = overrides.get(name, args.skills_root.expanduser()/name)
            results.append({'skill': snapshot.parents[1].name, 'source': name,
                            **compare(base, source)})
    print(json.dumps({'read_only': True, 'results': results,
                      'note': 'Source differences require review; no files were copied.'},
                     ensure_ascii=False, indent=2))
    return 2 if any(v['status'] == 'source_missing' for v in results) else (
        1 if any(v['status'] == 'changed' for v in results) else 0)

if __name__ == '__main__':
    raise SystemExit(main())
