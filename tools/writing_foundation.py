"""Reject missing direct-call contracts and drifting standalone foundation copies."""
from pathlib import Path

SHARED_FILES = (
    'references/writing-foundation.md',
    'references/anti-ai-rules.md',
    'references/anti-ai-extraction.md',
    'references/anti-ai-source-inventory.json',
    'scripts/check_writing.py',
    'LICENSES/DBS-CC-BY-NC-4.0.txt',
    'LICENSES/HUMAN-WRITING-MIT.txt',
    'LICENSES/WRITING-FOUNDATION-NOTICE.md',
)
HOOK = '[写作公共约束](references/writing-foundation.md)'

def validate(root, release):
    root = Path(root)
    canonical = root/'yl-writing'
    baseline = {rel: (canonical/rel).read_bytes() for rel in SHARED_FILES}
    for name, config in release['skills'].items():
        if config['category'] != 'writing':
            continue
        folder = root/name
        if HOOK not in (folder/'SKILL.md').read_text(encoding='utf-8-sig'):
            raise ValueError('Writing direct-call foundation missing: ' + name)
        for rel, expected in baseline.items():
            path = folder/rel
            if not path.is_file() or path.read_bytes() != expected:
                raise ValueError('Writing foundation copy differs: ' + name + '/' + rel)
