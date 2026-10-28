"""Validate archive-to-knowledge receipts; never performs semantic distillation."""
import argparse
import hashlib
import json
from pathlib import Path

def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def verify(manifest):
    errors = []
    items = manifest.get('items', [])
    if not items:
        errors.append('No archive items supplied')
    videos = set()
    receipts = {}
    accepted = {'distilled', 'merged_into_existing', 'no_new_atoms', 'external_reference', 'excluded'}
    for item in items:
        sid = item.get('source_id', '')
        try:
            if not sid:
                raise ValueError('missing source_id')
            video = Path(item['video_path'])
            if not video.is_absolute() or not video.is_file():
                raise ValueError('missing absolute final video')
            key = str(video.resolve()).casefold()
            if key in videos:
                raise ValueError('duplicate video entry')
            videos.add(key)
            if sha256(video) != item['video_sha256']:
                raise ValueError('final video version changed')
            if item.get('knowledge_exception'):
                if not item['knowledge_exception'].get('user_instruction'):
                    raise ValueError('exception lacks explicit user instruction')
                continue
            text = Path(item['text_path'])
            if not text.is_absolute() or not text.is_file() or not text.read_text('utf-8-sig').strip():
                raise ValueError('missing final text')
            if sha256(text) != item['text_sha256']:
                raise ValueError('final text version changed')
            rp = Path(item['receipt_path'])
            if not rp.is_absolute():
                raise ValueError('receipt path must be absolute')
            if str(rp) not in receipts:
                data = json.loads(rp.read_text('utf-8-sig'))
                records = data.get('sources', [data])
                if len({r['source_id'] for r in records}) != len(records):
                    raise ValueError('duplicate receipt source_id')
                receipts[str(rp)] = {r['source_id']: r for r in records}
            receipt = receipts[str(rp)][sid]
            if receipt['source_sha256'] != item['text_sha256']:
                raise ValueError('stale semantic receipt')
            if receipt.get('full_source_read') is not True or receipt.get('retrieval_verified') is not True:
                raise ValueError('reading or retrieval unfinished')
            if receipt.get('disposition') not in accepted or receipt.get('unresolved') != []:
                raise ValueError('unresolved knowledge processing')
            dedup_path = Path(receipt.get('cross_source_dedup_receipt', ''))
            if receipt.get('cross_source_dedup_checked') is not True or not dedup_path.is_absolute() or not dedup_path.is_file():
                raise ValueError('cross-source body deduplication unchecked or evidence missing')
            for field in ('ownership', 'dedup_reason', 'expression_reason', 'organization_reason'):
                if not str(receipt.get(field, '')).strip():
                    raise ValueError('missing ' + field)
            if not receipt.get('artifacts'):
                raise ValueError('no traceable knowledge artifacts')
            for artifact in receipt['artifacts']:
                if not Path(artifact).is_absolute() or not Path(artifact).is_file():
                    raise ValueError('missing artifact: ' + artifact)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append({'source_id': sid, 'error': str(exc)})
    return {'status': 'PASS' if not errors else 'FAIL', 'items': len(items), 'errors': errors,
            'boundary': 'Structural/version validation only; semantic review and audio listening are separate.'}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', required=True)
    args = parser.parse_args()
    result = verify(json.loads(Path(args.manifest).read_text('utf-8-sig')))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['status'] == 'PASS' else 1)
