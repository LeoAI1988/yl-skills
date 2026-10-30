"""Local incremental inventory and three-deliverable checks. No network access."""
from pathlib import Path
import argparse, hashlib, json, re, zipfile
from datetime import datetime, timezone
from decimal import Decimal
import xml.etree.ElementTree as ET


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def inventory(config):
    paths = set()
    for root in config['source_roots']:
        root = Path(root).resolve()
        if not root.is_dir():
            raise ValueError('Source directory missing: ' + str(root))
        paths.update(p.resolve() for p in root.rglob('*') if p.is_file())
    return [{'path': str(p), 'sha256': sha(p)} for p in sorted(paths)]


def scan(config):
    bp = Path(config['baseline_file'])
    previous = read(bp).get('inventory', []) if bp.exists() else []
    old = {x['path']: x['sha256'] for x in previous}
    hashes = {x['sha256']: x['path'] for x in previous}
    rows = inventory(config)
    for r in rows:
        prior = old.get(r['path'])
        r['status'] = 'new' if prior is None else 'unchanged' if prior == r['sha256'] else 'changed'
        if r['status'] != 'unchanged' and r['sha256'] in hashes:
            r['duplicate_of'] = hashes[r['sha256']]
        hashes.setdefault(r['sha256'], r['path'])
    current = {r['path'] for r in rows}
    return {'scanned_at': datetime.now(timezone.utc).isoformat(), 'inventory': rows,
            'counts': {s: sum(r['status'] == s for r in rows) for s in ['new', 'changed', 'unchanged']},
            'removed': [p for p in old if p not in current]}


def norm(text):
    return re.sub(r'\s+', '', text)


def body_norm(text):
    return ''.join(c for c in text if c.isalnum())


def docx_text(path):
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    texts = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name == 'word/document.xml' or re.fullmatch(r'word/(header|footer)\d+\.xml', name):
                root = ET.fromstring(z.read(name))
                texts.append('\n'.join(''.join(p.itertext()) for p in root.findall('.//w:p', ns)))
    return '\n'.join(texts)


def verify(manifest_path):
    m = read(manifest_path)
    errors = []
    items = m.get('items', [])
    ids = [r['identity'] for r in items]
    if not ids or len(ids) != len(set(ids)):
        errors.append('Empty or duplicate identities')
    for name in ['cover_order', 'distributor_order']:
        if len(m.get(name, [])) != len(ids) or set(m.get(name, [])) != set(ids):
            errors.append(name + ' differs from full sales inventory')
    by_id = {r['identity']: r for r in items}
    amounts = []
    for identity in m.get('cover_order', []):
        if identity in by_id:
            a = by_id[identity].get('amount')
            amounts.append(Decimal(str(a)) if a is not None else Decimal('-1'))
    if amounts != sorted(amounts, reverse=True):
        errors.append('Cover amounts are not descending')
    files = {}
    for field in ['cover_image', 'distributor_docx']:
        p = Path(m[field])
        if not p.is_file() or p.stat().st_size == 0:
            errors.append('Missing output: ' + field)
        else:
            files[str(p)] = sha(p)
    image = Path(m['cover_image'])
    if image.exists() and image.read_bytes()[:8] != b'\x89PNG\r\n\x1a\n':
        errors.append('Cover output must be a PNG')
    word = Path(m['distributor_docx'])
    public = docx_text(word) if word.exists() else ''
    flat = norm(public)
    chapter_titles = [norm(re.sub(r'^\d{2,}\s+', '', line)) for line in public.splitlines() if re.match(r'^\d{2,}\s+\S', line)]
    expected_titles = [norm(by_id[x]['title']) for x in m.get('distributor_order', []) if x in by_id]
    if chapter_titles != expected_titles:
        errors.append('Word chapter count/order differs from manifest')
    for text in ['成交金额', '千次观看成交', '小店播放量', '成交产品：', '来源：[', '¥', '￥']:
        if text in public:
            errors.append('Review distributor private-field hit: ' + text)
    if re.search(r'[A-Za-z]:[/\\]|file://', public):
        errors.append('Local path present in distributor document')
    for r in items:
        for field in ['manuscript', 'source', 'sales_evidence']:
            p = Path(r[field])
            if not p.is_file():
                errors.append('Missing ' + field + ': ' + r['title'])
            else:
                files[str(p)] = sha(p)
        if not r.get('body'):
            errors.append('Empty body: ' + r['title'])
        if norm(r['title']) not in flat or body_norm(r['body']) not in body_norm(public):
            errors.append('Distributor missing title or complete body: ' + r['title'])
        p = Path(r['manuscript'])
        if p.exists() and body_norm(r['body']) not in body_norm(p.read_text(encoding='utf-8-sig')):
            errors.append('Manuscript body mismatch: ' + r['title'])
        if r.get('amount') is not None and Decimal(str(r['amount'])) <= 0:
            errors.append('Non-positive sales amount needs separate evidence: ' + r['title'])
        if not r.get('window'):
            errors.append('Missing amount window or explicit unknown: ' + r['title'])
    if m.get('unresolved'):
        errors.append('Unresolved review items remain')
    if not all(m.get('visual_review', {}).get(k) is True for k in ['cover', 'docx_all_pages']):
        errors.append('Visual review is incomplete')
    return {'status': 'PASS' if not errors else 'FAIL', 'count': len(ids), 'errors': errors,
            'manifest_sha256': sha(manifest_path), 'files': files,
            'limitations': 'Text/hash consistency only; visual and semantic review are recorded by the reviewing agent.'}


def commit(config, scan_path, manifest_path, verification_path):
    oldcheck = read(verification_path)
    currentcheck = verify(manifest_path)
    if currentcheck['status'] != 'PASS' or currentcheck != oldcheck:
        raise ValueError('Deliverables changed or verification failed; verify again')
    s, m = read(scan_path), read(manifest_path)
    scanned = {r['path']: r['sha256'] for r in s['inventory']}
    current = {r['path']: r['sha256'] for r in inventory(config)}
    if scanned != current:
        raise ValueError('Source files changed after scan; rescan before completion')
    reviewed = {(r['path'], r['sha256']) for r in m.get('reviewed_inputs', [])}
    for r in s['inventory']:
        if r['status'] != 'unchanged' and (r['path'], r['sha256']) not in reviewed:
            raise ValueError('Unreviewed input: ' + r['path'])
    result = {'completed_at': datetime.now(timezone.utc).isoformat(),
              'inventory': s['inventory'], 'manifest': str(Path(manifest_path).resolve()),
              'manifest_sha256': sha(manifest_path), 'verification': currentcheck}
    write(config['baseline_file'], result)
    write(config['latest_manifest'], {'path': result['manifest'], 'sha256': result['manifest_sha256']})
    return {'status': 'PASS', 'count': len(m['items'])}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['scan', 'verify', 'commit'])
    p.add_argument('--config'); p.add_argument('--out'); p.add_argument('--scan')
    p.add_argument('--manifest'); p.add_argument('--verification')
    a = p.parse_args()
    if a.command == 'scan':
        result = scan(read(a.config))
    elif a.command == 'verify':
        result = verify(a.manifest)
    else:
        result = commit(read(a.config), a.scan, a.manifest, a.verification)
    if a.out:
        write(a.out, result)
    print(json.dumps({k: v for k, v in result.items() if k not in ['inventory', 'files']}, ensure_ascii=False))
    return int(result.get('status') == 'FAIL')


if __name__ == '__main__':
    raise SystemExit(main())
