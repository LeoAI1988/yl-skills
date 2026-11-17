"""Reject missing direct-call contracts and drifting standalone foundation copies."""
from pathlib import Path

SHARED_FILES = (
    'references/writing-foundation.md',
    'references/anti-ai-rules.md',
    'references/anti-ai-extraction.md',
    'references/anti-ai-source-inventory.json',
    'scripts/check_writing.py',
    'LICENSES/HUMAN-WRITING-MIT.txt',
    'LICENSES/WRITING-FOUNDATION-NOTICE.md',
)
HOOK = '[写作公共约束](references/writing-foundation.md)'
INDEPENDENT_HOOK = '[表达与来源复核](references/voice.md)'

def uses_shared_foundation(config):
    strategy = config.get('writing_foundation', 'shared')
    if strategy not in ('shared', 'independent'):
        raise ValueError('Unknown writing foundation strategy')
    return strategy == 'shared'

def validate(root, release):
    root = Path(root)
    canonical = root/'yl-writing'
    baseline = {rel: (canonical/rel).read_bytes() for rel in SHARED_FILES}
    for name, config in release['skills'].items():
        if config['category'] != 'writing' and config.get('subcategory') != 'writing':
            continue
        folder = root/name
        if not uses_shared_foundation(config):
            if INDEPENDENT_HOOK not in (folder/'SKILL.md').read_text(encoding='utf-8-sig'):
                raise ValueError('Independent writing direct-call contract missing: ' + name)
            if not (folder/'references/voice.md').is_file():
                raise ValueError('Independent writing reference missing: ' + name)
            if any((folder/rel).exists() for rel in SHARED_FILES):
                raise ValueError('Independent writing member contains shared foundation copies: ' + name)
            continue
        if HOOK not in (folder/'SKILL.md').read_text(encoding='utf-8-sig'):
            raise ValueError('Writing direct-call foundation missing: ' + name)
        for rel, expected in baseline.items():
            path = folder/rel
            if not path.is_file() or path.read_bytes() != expected:
                raise ValueError('Writing foundation copy differs: ' + name + '/' + rel)
