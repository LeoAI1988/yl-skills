"""Conservative privacy pre-screen; semantic review is still required."""
import argparse
import json
import re
import zipfile
from library import ROOT, TEXT_SUFFIXES, ROOT_FILES, ASSET_FILES

RULES = {
    'email': r'(?<![\w.+-])[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',
    'phone': r'(?<![0-9a-fA-F])1[3-9][0-9]{9}(?![0-9a-fA-F])',
    'api_key': r'\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})\b',
    'absolute_windows_path': r'(?i)\b[A-Z]:[\\/](?![\\/])[^\s\x22\x27]+',
    'absolute_home_path': r'(?:/Users|/home)/[^/\s]+',
    'private_key': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'bearer': r'(?i)\bBearer\s+(?!\[)[A-Za-z0-9._~-]{20,}',
}

def scan(items, private_terms=()):
    rules = {k: re.compile(v) for k, v in RULES.items()}
    rules.update({'private_term_' + str(i): re.compile(re.escape(v), re.I)
                  for i, v in enumerate(private_terms) if v})
    hits = []
    for name, data in items:
        try:
            content = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            hits.append({'file': name, 'line': 0, 'rule': 'unreadable_text'})
            continue
        for line, value in enumerate(content.splitlines(), 1):
            for key, pattern in rules.items():
                if pattern.search(value):
                    hits.append({'file': name, 'line': line, 'rule': key})
    return hits

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-term', action='append', default=[])
    parser.add_argument('--zip', action='store_true', help='Also scan the current distribution ZIP')
    args = parser.parse_args()
    paths = [ROOT/n for n in ROOT_FILES if (ROOT/n).is_file()]
    paths += list((ROOT/'tools').glob('*.py')) + list((ROOT/'reviews').glob('*.json'))
    for folder in ROOT.glob('yl-*'):
        if folder.is_dir():
            paths += [p for p in folder.rglob('*') if p.is_file() and
                      (p.suffix in TEXT_SUFFIXES or p.name in {'LICENSE','VERSION','.gitignore'})]
    items = [(p.relative_to(ROOT).as_posix(), p.read_bytes()) for p in paths]
    if args.zip:
        with zipfile.ZipFile(ROOT/'yl-toolbox-cluster.zip') as z:
            # Explicitly reviewed raster assets require visual review, not UTF-8 scanning.
            assets = {'yl-toolbox-cluster/'+n for n in ASSET_FILES}
            items += [('ZIP::'+n, z.read(n)) for n in z.namelist() if n not in assets]
    hits = scan(items, args.private_term)
    print(json.dumps({'files_scanned': len(items), 'findings': hits,
                      'semantic_review_required': True}, ensure_ascii=False, indent=2))
    return int(bool(hits))

if __name__ == '__main__':
    raise SystemExit(main())
