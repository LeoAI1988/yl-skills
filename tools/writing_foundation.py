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

def portable_text(root):
    ref = Path(root)/'yl-writing/references'
    content = '# yl Human Writing 便携版\n\n用于不支持 Skill 的聊天产品。把本文与需求一起提供；使用自然中文、材料驱动和适用文体，以下完整公共约束同样必做。无法运行脚本时执行等价语义复核。\n\n'
    for rel in ('writing-foundation.md', 'anti-ai-rules.md'):
        text = (ref/rel).read_text(encoding='utf-8')
        for target in ('writing-foundation.md', 'anti-ai-rules.md', 'anti-ai-extraction.md'):
            text = text.replace('](' + target + ')', '](../references/' + target + ')')
        content += text + '\n'
    return content

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
    portable = root/'yl-human-writing/dist/yl-human-writing-lite.md'
    if portable.read_text(encoding='utf-8') != portable_text(root):
        raise ValueError('Portable writing foundation differs')
