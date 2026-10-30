"""Check a typed revision ledger against final EDL, text, measured media and links.
Inputs are evidence supplied by the workflow, not a substitute for listening.
Source ranges use half-open frame intervals on the named original source.
"""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path


def verify(c):
    errors = []
    def require(ok, reason):
        if not ok: errors.append(reason)
    rate = Decimal(str(c['requestedRate']))
    require(rate.is_finite() and rate > 0, 'invalid requested rate')
    edl = c['edl']; keeps = edl['keeps']
    require(Decimal(str(edl['playbackRate'])) == rate, 'EDL decimal rate mismatch')
    require(Decimal(str(c['audioTempo'])) == rate, 'audio tempo mismatch')
    require(Decimal(str(c['previewRate'])) == rate, 'preview rate mismatch')
    for k in keeps:
        require(k['sourceEndFrame'] > k['sourceStartFrame'], 'invalid source interval')
        require(Decimal(str(k['appliedRate'])) == rate, 'keep rate mismatch')
        require(Decimal(str(k.get('existingRate', 1))) == 1, 'rate compounded on already sped source')
    source_frames = sum(k['sourceEndFrame'] - k['sourceStartFrame'] for k in keeps)
    source_fps = Decimal(str(edl.get('sourceFps', edl['fps'])))
    projected = Decimal(source_frames) / source_fps / rate * Decimal(str(edl['fps']))
    require(abs(float(projected) - edl['outputFrames']) <= .500001, 'EDL length inconsistent with source ranges and rate')
    ids = set()
    for op in c['operations']:
        require(bool(op.get('id')) and op.get('id') not in ids, 'missing or duplicate operation ID')
        ids.add(op.get('id'))
        kind = op.get('kind')
        require(kind in {'delete_audio_text','caption_correction','copy_hook','move','speed','cover'}, 'unresolved operation type')
        require(op.get('status') == 'done', 'unresolved operation ' + str(op.get('id')))
        if kind == 'delete_audio_text':
            ranges = op.get('sourceRanges', [])
            require(bool(ranges), 'deletion lacks source boundaries')
            for cut in ranges:
                require(cut['end'] > cut['start'] and bool(cut.get('source')), 'invalid deletion range/source')
                for k in keeps:
                    source = k.get('source', edl.get('source'))
                    scope = op.get('role', 'all')
                    if source == cut.get('source') and (scope == 'all' or k.get('role') == scope):
                        require(max(cut['start'],k['sourceStartFrame']) >= min(cut['end'],k['sourceEndFrame']), 'deleted source still kept: ' + op['id'])
            if op.get('text'):
                require(c['finalText'].count(op['text']) == op['expectedRemainingCount'], 'deleted text count mismatch: ' + op['id'])
        if kind == 'copy_hook':
            # Copying requires coverage in both roles; a word found in one is insufficient.
            for interval in op.get('sourceRanges', []):
                for role in ('hook','main'):
                    spans = sorted((k['sourceStartFrame'], k['sourceEndFrame']) for k in keeps
                                   if k.get('source',edl.get('source')) == interval['source'] and k.get('role') == role)
                    cursor = interval['start']
                    for a,b in spans:
                        if a <= cursor: cursor = max(cursor,b)
                    require(cursor >= interval['end'], 'copy hook lost ' + role + ' coverage')
            require(bool(op.get('sourceRanges')), 'copy hook lacks source intervals')
    measured = c['measured']
    require(measured['frames'] == edl['outputFrames'], 'actual frame count differs from EDL')
    tolerance = 1 / float(edl['fps']) + .005
    expected = edl['outputFrames'] / float(edl['fps'])
    require(abs(measured['audioDuration'] - expected) <= tolerance, 'actual audio duration differs from EDL')
    if c.get('enhancementInput'):
        clean = c['enhancementInput']
        require(clean['frames'] == edl['outputFrames'], 'clean input frame count mismatch; do not upload')
        require(abs(clean['audioDuration'] - expected) <= tolerance, 'clean input audio duration mismatch; do not upload')
        require(clean.get('hookCoverageChecked') is True, 'clean input hook coverage unchecked')
    final = Path(c['finalVideo']); linked = Path(c['previewVideo'])
    require(final.resolve() == linked.resolve(), 'preview links stale video')
    if final.is_file():
        with final.open('rb') as f: actual = hashlib.file_digest(f,'sha256').hexdigest()
        require(actual == c['videoSha256'] == c['previewSha256'], 'final/preview hash mismatch')
    else: require(False, 'final video missing')
    return {'status':'FAIL' if errors else 'PASS','errors':errors,'boundary':'Evidence consistency only; source listening and visual review remain separate.'}

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--contract',required=True)
    try:
        result=verify(json.loads(Path(p.parse_args().contract).read_text('utf-8-sig')))
    except (KeyError,TypeError,ValueError,OSError,ArithmeticError) as e:
        result={'status':'FAIL','errors':[str(e)]}
    print(json.dumps(result,ensure_ascii=False,indent=2));raise SystemExit(result['status']!='PASS')
