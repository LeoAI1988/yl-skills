"""Read-only discovery of unregistered or changed local source files.

No ownership, semantic completion or quotation approval is inferred here.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path

EXTENSIONS = {'.md', '.txt', '.docx', '.pdf', '.srt', '.vtt'}
SKIP_DIRS = {'.git', '.svn', 'node_modules', '__pycache__', '.venv'}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def path_key(path):
    return os.path.normcase(str(Path(path).expanduser().resolve()))


def linked(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def contained(path, roots):
    return any(path == root or root in path.parents for root in roots)


def discover(profile, roots=None, registries=None):
    config = profile.get('local_discovery', {})
    allowed = [Path(profile['knowledge_root']).expanduser().resolve()]
    allowed += [Path(p).expanduser().resolve() for p in profile.get('source_roots', [])]
    requested = roots if roots is not None else config.get('roots', profile.get('source_roots', []))
    known = {}
    for registry in registries if registries is not None else config.get('registries', []):
        payload = read_json(registry)
        rows = payload.get('sources', [])
        if not isinstance(rows, list):
            raise ValueError('Discovery registry needs a sources array of path/sha256 records')
        for row in rows:
            key = path_key(row['path'])
            digest = row['sha256']
            if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                raise ValueError('Registry must contain a lowercase SHA-256')
            if key in known and known[key]['sha256'] != digest:
                raise ValueError('Conflicting current hashes for the same registered path')
            known[key] = row
    candidates, unchanged, skipped, errors = [], [], [], []
    seen = set()
    exclude = SKIP_DIRS | set(config.get('exclude_directory_names', []))
    extensions = set(config.get('extensions', sorted(EXTENSIONS)))
    for value in requested:
        supplied = Path(value).expanduser().absolute()
        root = supplied.resolve()
        if not contained(root, allowed):
            raise ValueError('Discovery root is outside configured source roots')
        if linked(supplied):
            skipped.append({'path': str(supplied), 'reason': 'linked_root'}); continue
        if not root.is_dir():
            errors.append({'path': str(root), 'reason': 'missing_source_root'}); continue
        def on_error(error):
            errors.append({'path': str(error.filename), 'reason': type(error).__name__})
        for directory, dirs, files in os.walk(root, followlinks=False, onerror=on_error):
            for name in list(dirs):
                child = Path(directory)/name
                if name in exclude or linked(child):
                    dirs.remove(name)
                    skipped.append({'path': str(child), 'reason': 'configured_directory' if name in exclude else 'linked_directory'})
            for name in sorted(files):
                p = Path(directory)/name
                if p.suffix.lower() not in extensions:
                    continue
                if linked(p) or not contained(p.resolve(), [root]):
                    skipped.append({'path': str(p), 'reason': 'linked_file'}); continue
                key = path_key(p)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    before = p.stat()
                    with p.open('rb') as stream:
                        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                    after = p.stat()
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        raise RuntimeError('source_changed_during_read')
                except (OSError, RuntimeError) as error:
                    errors.append({'path': str(p), 'reason': str(error)}); continue
                previous = known.get(key)
                row = {'path': str(p), 'sha256': digest, 'bytes': after.st_size,
                       'modified_ns': after.st_mtime_ns,
                       'state': 'changed' if previous else 'unregistered',
                       'source_id': previous.get('source_id') if previous else None}
                if previous and previous['sha256'] == digest:
                    row['state'] = 'registered_unchanged'
                    row['processing_status'] = previous.get('processing_status', 'unknown')
                    unchanged.append(row)
                else:
                    if previous:
                        row['previous_sha256'] = previous['sha256']
                    candidates.append(row)
    return {'schema_version': 1, 'roots': list(map(str, requested)),
            'candidates': sorted(candidates, key=lambda r: path_key(r['path'])),
            'unchanged': unchanged, 'skipped': skipped, 'errors': errors,
            'note': 'Discovery only. Unchanged registration is not semantic completion. Read and classify every candidate; retain unresolved historical sources.'}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--profile', default=os.environ.get('YL_PROFILE') or str(Path.home()/'.config/yl-toolbox/profile.json'))
    ap.add_argument('--root', action='append')
    ap.add_argument('--registry', action='append')
    ap.add_argument('--output', type=Path)
    a = ap.parse_args()
    result = discover(read_json(a.profile), a.root, a.registry)
    encoded = json.dumps(result, ensure_ascii=False, indent=2)+'\n'
    if a.output:
        # The supplied output must never replace a source candidate or registry.
        protected = [r['path'] for r in result['candidates']+result['unchanged']]
        protected += a.registry or read_json(a.profile).get('local_discovery', {}).get('registries', [])
        protected += [a.profile]
        if path_key(a.output) in {path_key(p) for p in protected}:
            raise ValueError('Output would overwrite a source, registry or profile')
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(encoded, encoding='utf-8')
        print(json.dumps({k: len(result[k]) for k in ('candidates', 'unchanged', 'skipped', 'errors')}, ensure_ascii=False))
    else:
        print(encoded)
    return 1 if result['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
