"""Find VAD speech not covered by ASR; shared source-second coordinates required."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def merge(intervals):
    out = []
    for pair in intervals:
        if (len(pair) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                or not math.isfinite(v) for v in pair)
                or pair[0] < 0 or pair[1] <= pair[0]):
            raise ValueError('Intervals must be finite nonnegative [start,end] seconds')
    for start, end in sorted(intervals):
        if out and start <= out[-1][1]:
            out[-1][1] = max(end, out[-1][1])
        else:
            out.append([start, end])
    return out


def uncovered(vad, asr, threshold=.3):
    if not math.isfinite(threshold) or threshold <= 0:
        raise ValueError('Positive finite threshold required')
    coverage, gaps = merge(asr), []
    for start, end in merge(vad):
        cursor = start
        for left, right in coverage:
            if right <= cursor:
                continue
            if left >= end:
                break
            if left > cursor:
                gaps.append([cursor, min(left, end)])
            cursor = max(cursor, min(right, end))
        if cursor < end:
            gaps.append([cursor, end])
    return [pair for pair in gaps if pair[1] - pair[0] >= threshold - 1e-9]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True, help='JSON: coordinate=source_seconds, vad/asr arrays of [start,end]')
    args = p.parse_args()
    data = args.input.read_bytes()
    value = json.loads(data.decode('utf-8-sig'))
    if value.get('coordinate') != 'source_seconds':
        p.error('Expected source_seconds; align source, VAD and ASR first')
    print(json.dumps({'status': 'LISTENING_REVIEW_REQUIRED',
        'input_sha256': hashlib.sha256(data).hexdigest(),
        'uncovered': uncovered(value['vad'], value['asr'])}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
