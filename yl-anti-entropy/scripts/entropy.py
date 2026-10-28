"""Read-only inventories, exact duplicates, and explicit scoped cleanup; no backups."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import heapq
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import time

CORE = Path(__file__).resolve().parents[1]
GIB = 1024 ** 3


def absolute(value):
    return Path(os.path.abspath(os.path.expanduser(str(value))))


def inside(path, root):
    return path == root or root in path.parents


def linked(path):
    s = os.lstat(path)
    return stat.S_ISLNK(s.st_mode) or bool(getattr(s, 'st_file_attributes', 0) & 0x400)


def no_links(path, allow_leaf=False):
    for p in [path, *path.parents]:
        if os.path.lexists(p) and linked(p) and not (allow_leaf and p == path):
            raise ValueError('Linked path or ancestor: ' + str(p))


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def dump(path, value):
    path = absolute(path)
    no_links(path)
    if inside(path, CORE.parent):
        raise ValueError('Runtime output must be outside the Skill')
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    no_links(temp)
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temp, path)


def fingerprint(path):
    s = os.lstat(path)
    return [s.st_size, s.st_mtime_ns, str(s.st_dev), str(s.st_ino), stat.S_IFMT(s.st_mode)]


def sha(path):
    no_links(path)
    if not path.is_file():
        raise ValueError('Expected regular file: ' + str(path))
    before = fingerprint(path)
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(4 * 1024 ** 2), b''):
            h.update(block)
    if fingerprint(path) != before:
        raise ValueError('File changed while hashing: ' + str(path))
    return h.hexdigest()


def validate_roots(values, deletion=False):
    roots = [absolute(p) for p in values]
    if not roots:
        raise ValueError('Specify at least one root')
    for i, p in enumerate(roots):
        no_links(p)
        if not p.is_dir() or (deletion and p == Path(p.anchor)):
            raise ValueError('Invalid directory scope: ' + str(p))
        if any(inside(p, q) or inside(q, p) for q in roots[:i]):
            raise ValueError('Overlapping roots would double count')
    return roots


def quick_inventory(roots, out, baseline=None):
    """Directory metadata first; acquire real file identities only for candidates later."""
    roots = validate_roots(roots)
    out = absolute(out); no_links(out)
    if inside(out, CORE.parent) or (out / 'scan.json').exists() or (out / 'inventory.sqlite').exists():
        raise ValueError('Use a fresh output folder outside the core')
    excluded = os.path.normcase(str(out)).rstrip(os.sep)
    dirs, errors, skips, largest = {}, [], [], []
    started = time.monotonic()
    def walk(folder):
        size = count = 0
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    p = entry.path; normalized = os.path.normcase(p)
                    if normalized == excluded or normalized.startswith(excluded + os.sep):
                        continue
                    try:
                        s = entry.stat(follow_symlinks=False)
                        if stat.S_ISLNK(s.st_mode) or getattr(s, 'st_file_attributes', 0) & 0x400:
                            skips.append(p); continue
                        if stat.S_ISDIR(s.st_mode):
                            child_size, child_count = walk(p); size += child_size; count += child_count
                        elif stat.S_ISREG(s.st_mode):
                            size += s.st_size; count += 1
                            value = (s.st_size, p)
                            if len(largest) < 50: heapq.heappush(largest, value)
                            elif value > largest[0]: heapq.heapreplace(largest, value)
                    except OSError as e:
                        errors.append({'path': p, 'error': str(e)})
        except OSError as e:
            errors.append({'path': folder, 'error': str(e)})
        dirs[folder] = [size, count]
        return size, count
    totals = [0, 0]
    for root in roots:
        child = walk(str(root)); totals = [a + b for a, b in zip(totals, child)]
    exclusions = [str(out)] if any(inside(out, r) for r in roots) else []
    result = {'schema': 2, 'mode': 'metadata_only', 'time_utc': datetime.now(timezone.utc).isoformat(),
              'roots': list(map(str, roots)), 'exclusions': exclusions, 'logical_bytes': totals[0], 'files': totals[1],
              'unique_identity_bytes': None, 'fields': ['logical_bytes', 'files'], 'dirs': dirs,
              'errors': errors, 'skipped_links': skips, 'largest_files': [{'path': p, 'bytes': z} for z, p in sorted(largest, reverse=True)],
              'elapsed_seconds': time.monotonic() - started,
              'disk_usage': {str(r): dict(zip(['total', 'used', 'free'], shutil.disk_usage(r))) for r in roots},
              'limits': 'Directory metadata only, no SQLite or global identity estimate. Hardlinks may inflate logical bytes. Scan selected candidate folders in full mode and revalidate hashes before cleanup.'}
    if baseline:
        before = read(baseline)
        if before.get('schema') != 2 or before.get('mode') != 'metadata_only' or before.get('roots') != result['roots'] or before.get('exclusions') != exclusions:
            raise ValueError('Baseline mode/roots/exclusions differ')
        result['logical_growth_bytes'] = totals[0] - before['logical_bytes']
    dump(out / 'scan.json', result)
    lines = ['# 磁盘目录排查', '', f'现存文件 {totals[1]:,}；逻辑大小 {totals[0]/GIB:.2f} GiB。', '',
             '未计算全盘文件实体去重；目录逻辑大小不能相加。候选另做真实身份、占用和哈希核验。', '',
             '| 目录 | 逻辑GiB | 文件数 |', '|---|---:|---:|']
    for p, (z, n) in sorted(dirs.items(), key=lambda x: x[1][0], reverse=True)[:50]:
        lines.append(f'| {p} | {z/GIB:.3f} | {n} |')
    (out / '排查报告.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return {'files': totals[1], 'logical_bytes': totals[0], 'errors': len(errors), 'output': str(out), 'mode': 'metadata_only'}


def inventory(roots, out, baseline=None, resume_inventory=None):
    roots = validate_roots(roots)
    out = absolute(out)
    no_links(out)
    if inside(out, CORE.parent):
        raise ValueError('Keep scan output outside Skill')
    resume_files, excluded = {}, [out]
    if resume_inventory:
        source = absolute(resume_inventory)
        no_links(source)
        if any(inside(r, source.parent) for r in roots):
            raise ValueError('Resume inventory needs a dedicated output folder, not a scan root or ancestor')
        previous = sqlite3.connect('file:' + source.as_posix() + '?mode=ro', uri=True)
        try:
            prior_roots = {r[0] for r in previous.execute('select distinct root from files')}
            if prior_roots != {str(r) for r in roots}:
                raise ValueError('Resume inventory roots differ')
            resume_files = {r[0]: r for r in previous.execute('select path,root,size,mtime_ns,created_ns,dev,ino,nlink from files')}
        finally:
            previous.close()
        excluded.append(source.parent)
    out.mkdir(parents=True, exist_ok=True)
    db_path = out / 'inventory.sqlite'
    no_links(db_path)
    if db_path.exists():
        raise ValueError('Use a fresh scan output directory')
    db = sqlite3.connect(db_path)
    db.execute('create table files(path text primary key,root text,size integer,mtime_ns integer,created_ns integer,dev text,ino text,nlink integer)')
    errors, skips, dirs, extensions, pending = [], [], {}, {}, []
    reused = 0
    now = time.time_ns()
    files_count = 0
    unique_ids = set()
    unique_bytes = 0

    def walk(folder, scope):
        nonlocal files_count, unique_bytes, reused
        totals = [0, 0, 0, 0, 0, 0]
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    p = folder / entry.name
                    if any(inside(p, e) for e in excluded):
                        continue
                    try:
                        # Cached enumeration metadata is sufficient for type checks.
                        # Fresh regular files still use lstat for real Windows file IDs.
                        s = entry.stat(follow_symlinks=False)
                        if stat.S_ISLNK(s.st_mode) or getattr(s, 'st_file_attributes', 0) & 0x400:
                            skips.append(str(p))
                            continue
                        if stat.S_ISDIR(s.st_mode):
                            child = walk(p, scope)
                            totals = [a + b for a, b in zip(totals, child)]
                        elif stat.S_ISREG(s.st_mode):
                            prior = resume_files.get(str(p))
                            if prior and s.st_size == prior[2] and s.st_mtime_ns == prior[3]:
                                size, modified, created, dev, ino, nlink = prior[2:]
                                dev, ino = int(dev), int(ino)
                                reused += 1
                            else:
                                s = os.lstat(p)
                                size, modified, dev, ino, nlink = s.st_size, s.st_mtime_ns, s.st_dev, s.st_ino, s.st_nlink
                                created = getattr(s, 'st_birthtime_ns', None)
                                if created is None and os.name == 'nt':
                                    created = s.st_ctime_ns
                            invalid = [name for name, value in [('modified', modified), ('created', created)]
                                       if value is not None and not -(2**63) <= value < 2**63]
                            if invalid:
                                errors.append({'path': str(p), 'error': 'Timestamp outside SQLite range; date recorded as unknown', 'fields': invalid})
                            modified = modified if modified is None or -(2**63) <= modified < 2**63 else None
                            created = created if created is None or -(2**63) <= created < 2**63 else None
                            values = [size, 1,
                                      size if created and now - created <= 7 * 86400 * 10**9 else 0,
                                      size if created and now - created <= 30 * 86400 * 10**9 else 0,
                                      size if modified and now - modified <= 7 * 86400 * 10**9 else 0,
                                      size if modified and now - modified <= 30 * 86400 * 10**9 else 0]
                            totals = [a + b for a, b in zip(totals, values)]
                            identity = (dev, ino) if ino else ('path', str(p))
                            if identity not in unique_ids:
                                unique_ids.add(identity)
                                unique_bytes += size
                            ext = p.suffix.lower() or '(none)'
                            v = extensions.setdefault(ext, [0, 0]); v[0] += size; v[1] += 1
                            pending.append((str(p), str(scope), size, modified, created, str(dev), str(ino), nlink))
                            files_count += 1
                            if len(pending) >= 5000:
                                db.executemany('insert into files values(?,?,?,?,?,?,?,?)', pending)
                                pending.clear(); db.commit()
                    except OSError as e:
                        errors.append({'path': str(p), 'error': str(e)})
        except OSError as e:
            errors.append({'path': str(folder), 'error': str(e)})
        dirs[str(folder)] = totals
        return totals

    totals = [0] * 6
    for root in roots:
        totals = [a + b for a, b in zip(totals, walk(root, root))]
    if pending:
        db.executemany('insert into files values(?,?,?,?,?,?,?,?)', pending)
    db.execute('create index sizes on files(size)'); db.commit()
    largest = [{'path': p, 'bytes': z} for p, z in db.execute('select path,size from files order by size desc limit 50')]
    db.close()
    exclusions = sorted({str(e) for e in excluded if any(inside(e, r) for r in roots)})
    result = {'schema': 1, 'time_utc': datetime.now(timezone.utc).isoformat(), 'roots': list(map(str, roots)), 'exclusions': exclusions,
              'logical_bytes': totals[0], 'unique_identity_bytes': unique_bytes, 'files': files_count,
              'fields': ['logical_bytes', 'files', 'created_7d_bytes', 'created_30d_bytes', 'modified_7d_bytes', 'modified_30d_bytes'],
              'dirs': dirs, 'extensions': extensions, 'largest_files': largest, 'errors': errors, 'skipped_links': skips,
              'resumed_file_records': reused,
              'disk_usage': {str(r): dict(zip(['total', 'used', 'free'], shutil.disk_usage(r))) for r in roots},
              'limits': 'Logical bytes and unique identities are not allocated disk space. Creation dates are unknown on some systems. Recent creation is not net growth.'}
    if baseline:
        before = read(baseline)
        if before.get('schema') != 1 or before.get('roots') != result['roots'] or before.get('exclusions', []) != exclusions:
            raise ValueError('Baseline roots/schema/exclusions differ')
        result['logical_growth_bytes'] = result['logical_bytes'] - before['logical_bytes']
        result['file_count_change'] = result['files'] - before['files']
    dump(out / 'scan.json', result)
    lines = ['# 磁盘排查', '', f"现存文件 {files_count:,}；逻辑大小 {totals[0]/GIB:.2f} GiB。", '',
             '以下目录包含父子层级，不能相加。近期创建不是净增长；没有可比基线不报告净增。', '', '| 目录 | 逻辑GiB | 文件数 |', '|---|---:|---:|']
    for p, v in sorted(dirs.items(), key=lambda x: x[1][0], reverse=True)[:50]:
        lines.append(f'| {p} | {v[0]/GIB:.3f} | {v[1]} |')
    lines += ['', f'跳过链接 {len(skips)}；访问/路径/时间元数据异常 {len(errors)}。完整分布与异常在scan.json；没有删除文件。', '']
    (out / '排查报告.md').write_text('\n'.join(lines), encoding='utf-8')
    return {'files': files_count, 'logical_bytes': totals[0], 'errors': len(errors), 'output': str(out)}


def duplicates(database, output, minimum=64 * 1024**2):
    db = sqlite3.connect('file:' + absolute(database).as_posix() + '?mode=ro', uri=True)
    groups, errors, cache = [], [], {}
    for (size,) in db.execute('select size from files where size>=? group by size having count(*)>1', (minimum,)):
        buckets = defaultdict(list)
        for p, mtime in db.execute('select path,mtime_ns from files where size=?', (size,)).fetchall():
            path = absolute(p)
            try:
                no_links(path); s = os.lstat(path)
                if s.st_size != size or s.st_mtime_ns != mtime:
                    raise ValueError('Changed since scan')
                identity = (s.st_dev, s.st_ino) if s.st_ino else ('path', str(path))
                if identity not in cache:
                    cache[identity] = sha(path)
                buckets[cache[identity]].append({'path': str(path), 'identity': list(identity), 'hardlinks': s.st_nlink})
            except (OSError, ValueError) as e:
                errors.append({'path': p, 'error': str(e)})
        for h, entries in buckets.items():
            if len(entries) > 1:
                count = len({tuple(e['identity']) for e in entries})
                groups.append({'sha256': h, 'bytes_each': size, 'files': entries, 'independent_entities': count,
                               'maximum_redundant_bytes': max(0, count - 1) * size})
    db.close()
    result = {'minimum_bytes': minimum, 'groups': groups, 'errors': errors,
              'maximum_redundant_bytes': sum(g['maximum_redundant_bytes'] for g in groups),
              'limits': 'This is a hash-verified upper bound, not a deletion plan. Canonical paths and references need review.'}
    dump(output, result)
    return {'groups': len(groups), 'maximum_redundant_bytes': result['maximum_redundant_bytes'], 'errors': len(errors)}


def snapshot(path):
    records = []
    def visit(p):
        records.append({'path': str(p), 'stamp': fingerprint(p), 'link': linked(p)})
        if p.is_dir() and not linked(p):
            for child in sorted(p.iterdir()):
                visit(child)
    visit(path)
    return records


def build_plan(manifest, output):
    manifest, output = absolute(manifest), absolute(output)
    data = read(manifest)
    roots = validate_roots(data['scope_roots'], deletion=True)
    preserved = []
    for entry in data.get('preserve', []):
        p = absolute(entry['path']); h = sha(p)
        if entry.get('sha256') and entry['sha256'].lower() != h:
            raise ValueError('Preserved file does not match expected hash')
        preserved.append({'path': str(p), 'role': entry['role'], 'sha256': h})
    actions = []
    for raw in data['actions']:
        action = dict(raw); p = absolute(raw['path']); no_links(p)
        if not any(inside(p, r) for r in roots) or p == Path(p.anchor):
            raise ValueError('Action outside scoped folders or at volume root')
        if inside(CORE.parent, p) or inside(p, CORE.parent):
            raise ValueError('Cleanup tool/core cannot be a target')
        if any(inside(p, absolute(a['path'])) or inside(absolute(a['path']), p) for a in actions):
            raise ValueError('Overlapping actions')
        for record in [manifest, output, *[absolute(x['path']) for x in preserved]]:
            if inside(record, p):
                raise ValueError('Retained asset/record inside cleanup')
        if raw['kind'] == 'duplicate':
            keep = absolute(raw['keep']); no_links(keep)
            if keep == p or not keep.is_file():
                raise ValueError('Duplicate has no identical retained original')
            keep_hash = sha(keep)
            if sha(p) != keep_hash:
                raise ValueError('Duplicate has no identical retained original')
            action.update(keep=str(keep), sha256=keep_hash)
            if raw.get('mode', 'delete') not in ('delete', 'shortcut'):
                raise ValueError('Unknown duplicate mode')
            shortcut = Path(str(p) + '.lnk')
            if raw.get('mode') == 'shortcut' and (os.name != 'nt' or os.path.lexists(shortcut)):
                raise ValueError('Shortcut requires Windows and a new .lnk path')
        elif raw['kind'] == 'process_tree':
            roles = {x['role'] for x in preserved}
            if raw.get('result_confirmed') is not True or not {'original', 'final'} <= roles:
                raise ValueError('Confirmed result, original and final preserve roles required')
            if not p.is_dir():
                raise ValueError('Expected process directory')
        elif raw['kind'] == 'cache_tree':
            if not p.is_dir() or raw.get('inactive') is not True or not raw.get('inactive_evidence'):
                raise ValueError('Cache requires verified inactivity evidence')
            if len(p.parts) < 3 or p.parts[-2:] != ('.cache', 'webpack'):
                raise ValueError('Helper only auto-handles project .cache/webpack; classify other caches separately')
        else:
            raise ValueError('Unsupported action kind')
        action.update(path=str(p), snapshot=snapshot(p))
        actions.append(action)
    # Check keep files against every target, including actions that appeared later.
    targets = [absolute(a['path']) for a in actions]
    for a in actions:
        if a['kind'] == 'duplicate' and any(inside(absolute(a['keep']), p) for p in targets):
            raise ValueError('A retained original is another deletion target')
    result = {'schema': 1, 'scope_roots': list(map(str, roots)), 'preserve': preserved, 'actions': actions,
              'manifest': str(manifest), 'plan_path': str(output)}
    dump(output, result)
    return result


def create_shortcut(shortcut, target):
    if os.name != 'nt':
        raise ValueError('Windows .lnk creation is unavailable')
    command = r'''[Console]::InputEncoding=[Text.UTF8Encoding]::new($false);[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);$ErrorActionPreference='Stop';$d=[Console]::In.ReadToEnd()|ConvertFrom-Json;$w=New-Object -ComObject WScript.Shell;$s=$w.CreateShortcut($d.shortcut);$s.TargetPath=$d.target;$s.Arguments='';$s.WorkingDirectory=Split-Path -Parent $d.target;$s.Save();$r=$w.CreateShortcut($d.shortcut);if($r.TargetPath -ine $d.target -or $r.Arguments -or -not(Test-Path -LiteralPath $r.TargetPath)){throw 'Shortcut verification failed'}'''
    subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                   input=json.dumps({'shortcut': str(shortcut), 'target': str(target)}, ensure_ascii=False),
                   text=True, encoding='utf-8', check=True, capture_output=True)


def purge(path, expected):
    no_links(path, allow_leaf=True)
    current = fingerprint(path)
    if str(path) not in expected or current != expected[str(path)]:
        raise ValueError('Changed during cleanup: ' + str(path))
    if linked(path):
        # Removing a directory reparse point never traverses its external target.
        if os.name == 'nt' and (stat.S_ISDIR(os.lstat(path).st_mode) or getattr(os.lstat(path), 'st_file_attributes', 0) & 0x10):
            os.rmdir(path)
        else:
            path.unlink()
    elif path.is_dir():
        for child in list(path.iterdir()):
            purge(child, expected)
        path.rmdir()
    else:
        path.unlink()


def execute(plan_path, receipt):
    plan_path, receipt = absolute(plan_path), absolute(receipt)
    plan = read(plan_path)
    # Rebuild validation from the original manifest so a modified plan cannot bypass scope/role checks.
    fresh_path = receipt.with_name(receipt.name + '.preflight')
    for action in plan['actions']:
        if inside(receipt, absolute(action['path'])) or inside(fresh_path, absolute(action['path'])):
            raise ValueError('Receipt inside cleanup')
    current = build_plan(plan['manifest'], fresh_path)
    fresh_path.unlink()
    if current['actions'] != plan['actions'] or current['preserve'] != plan['preserve'] or current['scope_roots'] != plan['scope_roots']:
        raise ValueError('Plan or files changed; refresh preflight')
    for a in plan['actions']:
        if a['kind'] == 'duplicate' and a.get('mode') == 'shortcut':
            create_shortcut(Path(a['path'] + '.lnk'), Path(a['keep']))
    disks = {r: shutil.disk_usage(r).free for r in plan['scope_roots']}
    done, failures = [], []
    for action in plan['actions']:
        try:
            p = absolute(action['path'])
            purge(p, {r['path']: r['stamp'] for r in action['snapshot']})
            done.append({'path': str(p), 'files': sum(not stat.S_ISDIR(r['stamp'][4]) and not r['link'] for r in action['snapshot']),
                         'logical_bytes': sum(r['stamp'][0] for r in action['snapshot'] if stat.S_ISREG(r['stamp'][4]) and not r['link'])})
        except (OSError, ValueError) as e:
            failures.append({'path': action['path'], 'error': str(e)})
        dump(receipt, {'state': 'PARTIAL', 'completed': done, 'failures': failures})
        if failures:
            break
    for keep in plan['preserve']:
        if sha(absolute(keep['path'])) != keep['sha256']:
            failures.append({'path': keep['path'], 'error': 'Preserved asset changed'})
    for a in plan['actions']:
        if a['kind'] == 'duplicate' and sha(absolute(a['keep'])) != a['sha256']:
            failures.append({'path': a['keep'], 'error': 'Retained original changed'})
    result = {'state': 'PARTIAL' if failures else 'COMPLETED', 'completed': done, 'failures': failures,
              'free_before': disks, 'free_after': {r: shutil.disk_usage(r).free for r in plan['scope_roots']},
              'backup_created': False, 'disposal': 'Permanent removal; no Recycle Bin copy. Logical bytes are not guaranteed allocated bytes.'}
    dump(receipt, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('scan'); p.add_argument('--root', action='append', required=True); p.add_argument('--out', required=True); p.add_argument('--baseline'); p.add_argument('--resume-inventory'); p.add_argument('--metadata-only', action='store_true')
    p = sub.add_parser('duplicates'); p.add_argument('--inventory', required=True); p.add_argument('--out', required=True); p.add_argument('--minimum-mib', type=float, default=64)
    p = sub.add_parser('plan'); p.add_argument('--manifest', required=True); p.add_argument('--out', required=True)
    p = sub.add_parser('apply'); p.add_argument('--plan', required=True); p.add_argument('--receipt', required=True); p.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.command == 'scan':
        if args.metadata_only and args.resume_inventory:
            raise ValueError('Metadata mode does not consume an identity inventory')
        result = quick_inventory(args.root, args.out, args.baseline) if args.metadata_only else inventory(args.root, args.out, args.baseline, args.resume_inventory)
    elif args.command == 'duplicates':
        if args.minimum_mib < 0:
            raise ValueError('Minimum size cannot be negative')
        result = duplicates(args.inventory, args.out, int(args.minimum_mib * 1024**2))
    elif args.command == 'plan':
        p = build_plan(args.manifest, args.out); result = {'state': 'PLANNED', 'actions': len(p['actions']), 'media_changed': False}
    elif not args.execute:
        result = {'state': 'NOT_EXECUTED', 'reason': 'Inspect plan; use --execute only within current user authorization'}
    else:
        result = execute(args.plan, args.receipt)
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result.get('state') == 'PARTIAL' else 0


if __name__ == '__main__':
    raise SystemExit(main())
