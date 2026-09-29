"""Portable local knowledge state. Semantic decisions are supplied by the Agent."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

DEFAULT_PATHS = dict(thoughts='01_我的思想体系', works='02_我的作品全集', topics='03_选题库',
                     expressions='04_表达资产', atoms='05_知识原子/条目', private='80_私人档案',
                     system='90_系统资料')

def sha(data):
    return hashlib.sha256(data).hexdigest()

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.yl-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write('\n')
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)

def profile_path(value=None):
    return Path(value or os.environ.get('YL_PROFILE') or
                Path.home()/'.config/yl-toolbox/profile.json').expanduser().absolute()

def load_profile(path):
    cfg = read_json(path)
    if cfg.get('schema_version') != 1 or not cfg.get('knowledge_root'):
        raise ValueError('Profile needs schema_version=1 and knowledge_root')
    if 'ranking' in cfg or 'auto_distill' in cfg:
        raise ValueError('Ranking and full processing are core methods, not profile switches')
    cfg['paths'] = {**DEFAULT_PATHS, **cfg.get('paths', {})}
    root = Path(cfg['knowledge_root']).expanduser().resolve()
    if not root.is_dir():
        raise ValueError('Knowledge root does not exist; initialize first')
    for rel in cfg['paths'].values():
        inside(root, rel)
    return cfg, root

def inside(root, rel):
    rel = str(rel)
    if Path(rel).is_absolute() or re.match(r'^[A-Za-z]:', rel):
        raise ValueError('Artifact paths must be relative')
    path = (root/rel).resolve()
    if path == root or root not in path.parents:
        raise ValueError('Path escapes knowledge root')
    return path

def state_path(cfg, root):
    return inside(root, cfg['paths']['system'])/'YL知识管理/state.json'

def state_load(cfg, root):
    p = state_path(cfg, root)
    return read_json(p) if p.exists() else {'schema_version': 1, 'sources': {}}

@contextmanager
def locked(cfg, root):
    p = state_path(cfg, root).with_suffix('.lock')
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError('Another operation is active; inspect stale lock before recovery')
    try:
        os.close(fd)
        yield
    finally:
        p.unlink()

def allowed_source(cfg, root, value):
    p = Path(value).expanduser().resolve()
    allowed = [root] + [Path(v).expanduser().resolve() for v in cfg.get('source_roots', [])]
    if not any(p != r and r in p.parents for r in allowed):
        raise ValueError('Source is outside configured roots')
    if not p.is_file():
        raise ValueError('Source is not a readable file')
    if p.suffix.lower() not in {'.md', '.txt'}:
        raise ValueError('Register a decoded text artifact, preserving the original separately')
    return p

def register(cfg, root, file, source_id, origin, ownership='unknown'):
    if not source_id or len(source_id) > 300:
        raise ValueError('Stable source ID required')
    p = allowed_source(cfg, root, file)
    raw = p.read_bytes()
    raw.decode('utf-8-sig')
    digest = sha(raw)
    with locked(cfg, root):
        state = state_load(cfg, root)
        previous = state['sources'].get(source_id)
        if previous and previous['sha256'] == digest:
            return {'status': 'unchanged', 'id': source_id, 'processing': previous['status']}
        history = list(previous.get('history', [])) if previous else []
        if previous:
            history.append({k: v for k, v in previous.items() if k != 'history'})
        source_dir = state_path(cfg, root).parent/'source-versions'/sha(source_id.encode())[:24]
        snapshot = source_dir/(digest+'.md')
        source_dir.mkdir(parents=True, exist_ok=True)
        if snapshot.exists() and snapshot.read_bytes() != raw:
            raise ValueError('Immutable source collision')
        if not snapshot.exists():
            snapshot.write_bytes(raw)
        state['sources'][source_id] = {
            'path': str(p), 'snapshot': snapshot.relative_to(root).as_posix(),
            'sha256': digest, 'origin': origin, 'ownership': ownership,
            'status': 'pending', 'history': history,
            'reason': 'New or changed text requires full processing'}
        state['sources'][source_id]['exact_duplicate_candidates'] = [
            sid for sid,item in state['sources'].items() if sid != source_id and item['sha256'] == digest]
        atomic_json(state_path(cfg, root), state)
    return {'status': 'needs_semantic_processing', 'id': source_id,
            'new_version': digest, 'previous_versions': len(history)}

def compact(value):
    return re.sub(r'\s+', ' ', value).strip()

def validate_receipt(root, row, receipt):
    source = inside(root, row['snapshot'])
    raw = source.read_bytes()
    if sha(raw) != row['sha256'] or receipt.get('source_sha256') != row['sha256']:
        raise ValueError('Receipt or original hash mismatch')
    text = raw.decode('utf-8-sig')
    count = len(text.splitlines())
    covered = set()
    for pair in receipt.get('coverage', []):
        if (not isinstance(pair, list) or len(pair) != 2 or
                any(type(n) is not int for n in pair) or not 1 <= pair[0] <= pair[1] <= count):
            raise ValueError('Invalid coverage interval')
        covered.update(range(pair[0], pair[1]+1))
    if covered != set(range(1, count+1)):
        raise ValueError('Full source reading coverage missing')
    disposition = receipt.get('disposition')
    if disposition not in {'distilled', 'no_new_atoms', 'external_reference', 'excluded'}:
        raise ValueError('Unknown completion disposition')
    for key in ('classification_reason', 'dedup_reason', 'expression_reason', 'organization_reason', 'note'):
        if not isinstance(receipt.get(key), str) or not receipt[key].strip():
            raise ValueError('Missing semantic explanation: '+key)
    atoms, expressions = receipt.get('atoms', []), receipt.get('expressions', [])
    if not isinstance(atoms, list) or not isinstance(expressions, list):
        raise ValueError('Artifact lists required')
    ownership = receipt.get('ownership')
    if ownership not in {'user_owned', 'mixed', 'third_party', 'excluded'}:
        raise ValueError('Ownership review missing')
    if disposition in {'external_reference', 'excluded'} and (atoms or expressions):
        raise ValueError('External or excluded source cannot become personal artifacts')
    if (atoms or expressions) and ownership not in {'user_owned', 'mixed'}:
        raise ValueError('Personal artifacts require reviewed authorship')
    if disposition == 'distilled' and not atoms:
        raise ValueError('Distilled disposition needs atoms')
    if disposition == 'no_new_atoms' and atoms:
        raise ValueError('Use distilled for new or merged atoms')
    quoted_source = text
    if ownership == 'mixed' and (atoms or expressions):
        owned_lines = []
        for pair in receipt.get('owned_spans', []):
            if (not isinstance(pair,list) or len(pair)!=2 or any(type(n) is not int for n in pair)
                    or not 1<=pair[0]<=pair[1]<=count):
                raise ValueError('Mixed source needs valid reviewed own-speech spans')
            owned_lines.extend(text.splitlines()[pair[0]-1:pair[1]])
        if not owned_lines: raise ValueError('Mixed source needs reviewed own-speech spans')
        quoted_source='\n'.join(owned_lines)
    evidence = []
    for obj in atoms + expressions:
        if not isinstance(obj, dict) or not obj.get('quotes'):
            raise ValueError('Every artifact needs source quotes')
        p = inside(root, obj['path'])
        body = p.read_text(encoding='utf-8-sig')
        for q in obj['quotes']:
            if not isinstance(q, str) or not compact(q) or compact(q) not in compact(quoted_source):
                raise ValueError('Quote does not occur verbatim in source')
            if compact(q) not in compact(body):
                raise ValueError('Artifact does not preserve its quoted evidence')
        evidence.append({'path': obj['path'], 'sha256': sha(p.read_bytes())})
    if (atoms or expressions) and not receipt.get('links'):
        raise ValueError('Artifacts need a thought/work relationship destination')
    for link in receipt.get('links', []):
        if not inside(root, link).is_file():
            raise ValueError('Relationship target missing')
    return evidence

def record(cfg, root, source_id, receipt):
    with locked(cfg, root):
        state = state_load(cfg, root)
        row = state['sources'][source_id]
        current = Path(row['path'])
        if not current.is_file() or sha(current.read_bytes()) != row['sha256']:
            raise ValueError('Live source changed; register new version before recording')
        evidence = validate_receipt(root, row, receipt)
        old = row.get('receipt')
        if old:
            row.setdefault('receipt_history', []).append(old)
        row.update(receipt=receipt, artifacts=evidence, status='processed',
                   ownership=receipt['ownership'], reason=receipt['disposition'])
        atomic_json(state_path(cfg, root), state)
    return {'status': 'recorded', 'id': source_id, 'semantic_review': 'Agent supplied, not machine inferred'}

def inspect(cfg, root):
    state = state_load(cfg, root)
    pending, errors = [], []
    for sid, row in state['sources'].items():
        try:
            live = Path(row['path'])
            if not live.is_file() or sha(live.read_bytes()) != row['sha256']:
                pending.append({'id': sid, 'reason': 'source_changed_or_missing'})
            elif row['status'] != 'processed':
                pending.append({'id': sid, 'reason': row.get('reason', 'pending')})
            else:
                evidence = validate_receipt(root, row, row['receipt'])
                if evidence != row.get('artifacts'):
                    pending.append({'id': sid, 'reason': 'artifact_changed_recheck_required'})
        except (ValueError, OSError, KeyError) as exc:
            errors.append({'id': sid, 'reason': str(exc)})
    for check in cfg.get('legacy_checks', []):
        try:
            data=read_json(check['path'])
            value=data if not check.get('field') else data.get(check['field'])
            if value != check['expected']:
                pending.append({'id':check['name'],'reason':'legacy_check_not_complete','observed':value})
        except (OSError,ValueError,KeyError) as exc:
            errors.append({'id':check.get('name','legacy'),'reason':str(exc)})
    return {'status': 'PASS' if not pending and not errors else 'INCOMPLETE',
            'registered_sources': len(state['sources']), 'pending': pending, 'errors': errors,
            'scope': 'Registered sources only; Agent must reconcile task inventory and legacy queues'}

def init(profile, root_value, mode):
    if profile.exists():
        raise ValueError('Profile exists; preserve it and explicitly edit selected fields')
    root = Path(root_value).expanduser().resolve()
    if mode == 'new' and root.exists() and any(root.iterdir()):
        raise ValueError('New library target must be empty; use adopt for an existing library')
    if mode == 'adopt' and not root.is_dir():
        raise ValueError('Adopt target must exist')
    root.mkdir(parents=True, exist_ok=True)
    cfg = {'schema_version': 1, 'knowledge_root': str(root), 'paths': dict(DEFAULT_PATHS),
           'source_roots': [], 'personal_instructions': [], 'domains': [],
           'sources': {}, 'excluded_source_ids': [], 'tools': {}, 'local_hooks': {}}
    if root == profile.parent or root in profile.parents:
        raise ValueError('Personal profile must live outside the knowledge library')
    if mode == 'new':
        for key, rel in DEFAULT_PATHS.items():
            p = inside(root, rel)
            p.mkdir(parents=True, exist_ok=True)
            (p/'README.md').write_text('# '+p.name.split('_',1)[-1]+'\n\n'+
                ('原始资料、处理记录与备份集中在这里。' if key == 'system' else
                 '尚未导入内容。此入口不代表已有成果。')+'\n', encoding='utf-8')
        (root/'README.md').write_text('# 我的知识库\n\n'+'\n'.join(
            f'- [{k}]({v}/README.md)' for k,v in DEFAULT_PATHS.items())+'\n', encoding='utf-8')
    atomic_json(profile, cfg)
    return {'status': 'configured', 'mode': mode, 'profile': str(profile),
            'next': 'Review path mappings before importing; no content has been distilled'}

def search(cfg, root, query):
    terms = [t.casefold() for t in query.split() if t]
    result = []
    for role in ('thoughts', 'works', 'topics', 'expressions', 'atoms'):
        folder = inside(root, cfg['paths'][role])
        for p in folder.rglob('*.md') if folder.exists() else []:
            if root not in p.resolve().parents:
                continue
            text = p.read_text(encoding='utf-8-sig')
            score = sum(t in text.casefold() for t in terms)
            if score:
                snippets = [line for line in text.splitlines() if any(t in line.casefold() for t in terms)]
                result.append({'path': p.relative_to(root).as_posix(), 'matched_terms': score,
                               'snippets': snippets[:4]})
    return sorted(result, key=lambda r: -r['matched_terms'])[:30]

def refresh(cfg, root):
    state = state_load(cfg, root)
    lines = ['# 来源与处理索引', '', '此页是工作索引，不是思想体系正文。', '']
    for sid, row in state['sources'].items():
        lines.append(f'- {sid}：{row["status"]}；[[{row["snapshot"]}|原文版本]]')
        for a in row.get('receipt', {}).get('atoms', []) + row.get('receipt', {}).get('expressions', []):
            lines.append('  - [['+a['path']+']]')
    p = state_path(cfg, root).parent/'来源与处理索引.md'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return {'status': 'index_refreshed', 'path': str(p), 'thought_tree_curated': False}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--profile')
    sub = p.add_subparsers(dest='command', required=True)
    b = sub.add_parser('init'); b.add_argument('--root', required=True); b.add_argument('--mode', choices=['new','adopt'], required=True)
    b = sub.add_parser('register'); b.add_argument('--file', required=True); b.add_argument('--id', required=True); b.add_argument('--origin', default='local'); b.add_argument('--ownership', choices=['unknown','user_owned','mixed','third_party'], default='unknown')
    b = sub.add_parser('record'); b.add_argument('--id', required=True); b.add_argument('--receipt', required=True)
    for name in ('queue','check','refresh'):
        sub.add_parser(name)
    b = sub.add_parser('search'); b.add_argument('--query', required=True)
    a = p.parse_args()
    profile = profile_path(a.profile)
    try:
        if a.command == 'init':
            result = init(profile, a.root, a.mode)
        else:
            cfg, root = load_profile(profile)
            if a.command == 'register': result = register(cfg, root, a.file, a.id, a.origin, a.ownership)
            elif a.command == 'record': result = record(cfg, root, a.id, read_json(a.receipt))
            elif a.command == 'search': result = search(cfg, root, a.query)
            elif a.command == 'refresh': result = refresh(cfg, root)
            else: result = inspect(cfg, root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if a.command == 'check' and result['status'] != 'PASS': return 2
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({'status': 'ERROR', 'error': str(exc)}, ensure_ascii=False))
        return 2

if __name__ == '__main__':
    sys.exit(main())
