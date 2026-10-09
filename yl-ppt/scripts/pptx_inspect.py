"""Read-only PPTX inventory and structural comparison; Python standard library only."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import xml.etree.ElementTree as ET
import zipfile

NS = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def relationships(blobs, part):
    p = PurePosixPath(part)
    relpart = str(p.parent / '_rels' / (p.name + '.rels'))
    result = {}
    if relpart not in blobs:
        return result
    for e in ET.fromstring(blobs[relpart]):
        target = e.attrib['Target']
        external = e.get('TargetMode') == 'External'
        if not external:
            target = posixpath.normpath(posixpath.join(str(p.parent), target)).lstrip('/')
        result[e.attrib['Id']] = {'target': target, 'type': e.attrib['Type'],
                                'external': external,
                                'sha256': None if external else sha(blobs[target])}
    return result


def normalized(root, rels):
    root = copy.deepcopy(root)
    for parent in root.iter():
        for child in list(parent):
            if child.tag.rsplit('}', 1)[-1] == 'creationId':
                parent.remove(child)
    for e in root.iter():
        if e.tag == '{' + NS['p'] + '}cNvPr':
            e.attrib.pop('id', None)
            e.attrib.pop('name', None)
        for k, v in list(e.attrib.items()):
            if k.startswith('{' + NS['r'] + '}') and v in rels:
                r = rels[v]
                e.set(k, r['target'] if r['external'] else r['sha256'])
    return sha(ET.canonicalize(ET.tostring(root, encoding='unicode')).encode('utf-8'))


def inventory(path):
    path = Path(path)
    raw = path.read_bytes()
    with zipfile.ZipFile(path) as z:
        if len(z.namelist()) != len(set(z.namelist())):
            raise ValueError('Duplicate ZIP members')
        if z.testzip() is not None:
            raise ValueError('ZIP CRC failed')
        blobs = {n: z.read(n) for n in z.namelist() if not n.endswith('/')}
    for name, data in blobs.items():
        if name.endswith(('.xml', '.rels')):
            ET.fromstring(data)
        if name.endswith('.rels'):
            p = PurePosixPath(name)
            owner = str(p.parent.parent / p.name[:-5]) if name != '_rels/.rels' else ''
            relationships(blobs, owner)
    main = ET.fromstring(blobs['ppt/presentation.xml'])
    rels = relationships(blobs, 'ppt/presentation.xml')
    slides = []
    for number, item in enumerate(main.findall('p:sldIdLst/p:sldId', NS), 1):
        part = rels[item.attrib['{' + NS['r'] + '}id']]['target']
        tree = ET.fromstring(blobs[part])
        sr = relationships(blobs, part)
        shapes = []
        for e in tree.iter():
            if e.tag not in {'{' + NS['p'] + '}' + k for k in ('sp', 'pic', 'cxnSp', 'graphicFrame', 'grpSp')}:
                continue
            nv = e.find('.//p:cNvPr', NS)
            geom = e.find('./p:spPr/a:xfrm', NS)
            if geom is None:
                geom = e.find('./p:xfrm', NS)
            if geom is None:
                geom = e.find('./p:grpSpPr/a:xfrm', NS)
            images = []
            for b in e.findall('.//a:blip', NS):
                for key in ('embed', 'link'):
                    rid = b.get('{' + NS['r'] + '}' + key)
                    if rid:
                        images.append(sr[rid])
            shapes.append({'kind': e.tag.rsplit('}', 1)[-1],
                           'id': nv.get('id') if nv is not None else None,
                           'name': nv.get('name') if nv is not None else None,
                           'text': '\n'.join(t.text or '' for t in e.findall('.//a:t', NS)),
                           'geometry_local_emu': None if geom is None else
                           {g.tag.rsplit('}', 1)[-1]: dict(g.attrib) for g in geom},
                           'images': images})
        slides.append({'number': number, 'ooxml_id': item.get('id'), 'part': part,
                       'text': '\n'.join(t.text or '' for t in tree.findall('.//a:t', NS)),
                       'structural_sha256': normalized(tree, sr), 'shapes': shapes})
    size = main.find('p:sldSz', NS)
    return {'file': str(path.resolve()), 'sha256': sha(raw), 'slide_count': len(slides),
            'size_emu': dict(size.attrib) if size is not None else None,
            'parts': {n: sha(b) for n, b in sorted(blobs.items())}, 'slides': slides,
            'limits': 'Structural inventory only; not visual, typography or QR scan acceptance.'}


def compare(a, b):
    left, right = inventory(a), inventory(b)
    lp, rp = left['parts'], right['parts']
    return {'before_sha256': left['sha256'], 'after_sha256': right['sha256'],
            'slide_counts': [left['slide_count'], right['slide_count']],
            'added_parts': sorted(rp.keys() - lp.keys()),
            'removed_parts': sorted(lp.keys() - rp.keys()),
            'changed_parts': sorted(n for n in lp.keys() & rp.keys() if lp[n] != rp[n]),
            'changed_slide_positions': [i + 1 for i in range(max(len(left['slides']), len(right['slides'])))
                if i >= len(left['slides']) or i >= len(right['slides']) or
                left['slides'][i]['structural_sha256'] != right['slides'][i]['structural_sha256']],
            'limits': 'Compares slide positions, not semantic identity. Master/theme/layout changes require separate review.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    inv = sub.add_parser('inventory')
    inv.add_argument('file', type=Path)
    cmp = sub.add_parser('compare')
    cmp.add_argument('before', type=Path)
    cmp.add_argument('after', type=Path)
    for s in (inv, cmp):
        s.add_argument('--out', type=Path)
    args = p.parse_args()
    inputs = [args.file] if args.command == 'inventory' else [args.before, args.after]
    if args.out and (args.out.resolve() in [x.resolve() for x in inputs] or args.out.suffix.lower() != '.json'):
        p.error('--out must be a separate JSON report, never an input deck')
    report = inventory(args.file) if args.command == 'inventory' else compare(args.before, args.after)
    data = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(data, encoding='utf-8')
        print(json.dumps({'report': str(args.out), 'status': 'written'}, ensure_ascii=False))
    else:
        print(data)


if __name__ == '__main__':
    main()
