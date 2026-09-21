"""Shared, dependency-free release checks. No source-library writes or network calls."""
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]
NAME = re.compile(r"yl-[a-z0-9]+(?:-[a-z0-9]+)*")
VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
TEXT_SUFFIXES = {'.md', '.py', '.ps1', '.yaml', '.yml', '.json', '.txt', '.toml',
                 '.js', '.mjs', '.ts', '.tsx', '.jsx', '.css', '.html', '.sh', '.csv'}
ROOT_FILES = ['README.md', 'PRD.md', 'MAINTAINING.md', 'CHANGELOG.md', 'LICENSE',
              'THIRD_PARTY_NOTICES.md', 'AGENTS.md', '.gitignore', 'release.json',
              'install.py', 'build.py', 'yl集群_审核说明.md', 'Skill清单_v2.1.0.md', '版本对齐_v2.1.0.md']
ASSET_FILES = ['YL-Skill集群.jpg']

def digest(data):
    return hashlib.sha256(data).hexdigest()

def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')

def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def is_link(path):
    return path.is_symlink() or (path.exists() and
        bool(getattr(path.stat(), 'st_file_attributes', 0) & 0x400))

def relative_file(value):
    return (isinstance(value, str) and bool(value) and '\\' not in value
            and ':' not in value and not value.startswith('/')
            and all(p not in ('', '.', '..') for p in value.split('/')))

def file_map(folder):
    if is_link(folder):
        raise ValueError('Linked directory: ' + folder.name)
    result = {}
    for p in sorted(folder.rglob('*')):
        if is_link(p):
            raise ValueError('Linked member: ' + p.name)
        if not p.is_file():
            continue
        if '__pycache__' in p.parts or p.name.startswith('.env'):
            raise ValueError('Runtime data found: ' + p.name)
        if p.suffix.lower() not in TEXT_SUFFIXES and p.name not in {
                'LICENSE', 'NOTICE', 'VERSION', '.gitignore', 'COPYING'}:
            raise ValueError('File type needs review: ' + p.name)
        result[p.relative_to(folder).as_posix()] = p.read_bytes()
    return result

def skill_metadata(folder):
    content = (folder/'SKILL.md').read_text(encoding='utf-8-sig')
    if not content.startswith('---\n'):
        raise ValueError('Missing frontmatter: ' + folder.name)
    fm = content.split('---', 2)[1]
    name = re.search(r'^name:\s*(.+)$', fm, re.M)
    desc = re.search(r'^description:\s*(.+)$', fm, re.M)
    if not NAME.fullmatch(folder.name) or not name or name[1].strip() != folder.name or not desc:
        raise ValueError('Invalid Skill metadata: ' + folder.name)
    return {'name': folder.name, 'description': desc[1].strip()}

def check_links(folder, blobs):
    errors = []
    for rel, data in blobs.items():
        if not rel.endswith('.md'):
            continue
        for link in re.findall(r'\]\(([^\n]+?)\)', data.decode('utf-8-sig')):
            link = link.strip().split(' "')[0].strip('<>')
            if re.match(r'^(https?://|mailto:|#)', link):
                continue
            if any(c in link for c in ('{', '}', '<', '>')) or not link:
                continue
            target = (folder/rel).parent / link.split('#')[0]
            if not target.exists():
                errors.append(rel + ': ' + link)
    if errors:
        raise ValueError('Missing relative references: ' + '; '.join(errors))

def project_map(root=ROOT):
    values = {name: (root/name).read_bytes() for name in ROOT_FILES}
    for name in ASSET_FILES:
        path = root/name
        if is_link(path):
            raise ValueError('Linked project asset')
        values[name] = path.read_bytes()
    for p in sorted((root/'tools').glob('*.py')):
        if is_link(p):
            raise ValueError('Linked maintenance script')
        values[p.relative_to(root).as_posix()] = p.read_bytes()
    return values

def hash_map(blobs):
    return {name: digest(data) for name, data in blobs.items()}
