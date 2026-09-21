"""Read-only final-output candidate review; never certifies editorial quality."""
import argparse
import bisect
import difflib
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def candidates(caps):
    if not isinstance(caps, list):
        raise ValueError('Captions must be an array')
    stream, offsets, times, out = '', [], [], []
    previous = -1
    for c in caps:
        start, end = c['startMs'], c['endMs']
        if (not isinstance(c['text'], str) or any(isinstance(v, bool) or
                not isinstance(v, (float, int)) or not math.isfinite(v) for v in (start, end))
                or start < 0 or end <= start or start < previous):
            raise ValueError('Invalid or unsorted caption interval')
        previous = start
        t = re.sub(r'[^\w\u4e00-\u9fff]', '', c['text'])
        if t:
            offsets.append(len(stream)); times.append(start / 1000); stream += t
        if end - start >= 8000:
            out.append({'type': 'caption_freeze', 'at': start / 1000, 'text': c['text']})

    def time_at(i):
        return times[bisect.bisect_right(offsets, i) - 1]

    seen = set()
    for n in range(8, 1, -1):
        for i in range(len(stream) - 2 * n + 1):
            a, b = stream[i:i+n], stream[i+n:i+2*n]
            if not re.search(r'[\u4e00-\u9fff]', a):
                continue
            ratio = difflib.SequenceMatcher(None, a, b).ratio()
            if a == b or (n >= 4 and ratio >= .85):
                key = (time_at(i), a[:4])
                if key not in seen:
                    seen.add(key)
                    out.append({'type': 'adjacent_repeat' if a == b else 'adjacent_near_repeat',
                                'text': a + '/' + b, 'length': n,
                                'at': time_at(i), 'at2': time_at(i+n)})
    for n in range(3, 9):
        positions = {}
        for i in range(len(stream) - n + 1):
            phrase = stream[i:i+n]
            if not re.fullmatch(r'[\u4e00-\u9fff]+', phrase):
                continue
            old = positions.get(phrase)
            if old is not None and i - old >= n and time_at(i) - time_at(old) < 40:
                out.append({'type': 'repeated_phrase', 'text': phrase,
                            'at': time_at(old), 'at2': time_at(i)})
            positions[phrase] = i
    for filler in ('这个嗯', '那个嗯', '嗯那个', '那就是', '所以说', '这样的话呢',
                   '就是说', '然后然后', '就是就是', '我我', '的的', '了了'):
        for m in re.finditer(re.escape(filler), stream):
            out.append({'type': 'filler_candidate', 'text': filler, 'at': time_at(m.start())})
    return out


def silence(audio, ffmpeg):
    result = subprocess.run([str(ffmpeg), '-hide_banner', '-nostdin', '-i', str(audio),
        '-vn', '-af', 'silencedetect=noise=-32dB:d=0.15', '-f', 'null', '-'],
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=600)
    if result.returncode:
        raise ValueError('FFmpeg scan failed; no clearance was issued')
    if not re.search(r'Audio:', result.stderr):
        raise ValueError('No decoded audio stream')
    return [{'type': 'silence', 'at': float(m.group(1))} for m in
            re.finditer(r'silence_start:\s*([\d.]+)', result.stderr)]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--captions', type=Path, required=True)
    p.add_argument('--audio', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--ffmpeg', default=shutil.which('ffmpeg'))
    args = p.parse_args()
    skill = Path(__file__).resolve().parents[1]
    if args.output.resolve().is_relative_to(skill) or args.output.exists():
        p.error('Use a new output file outside the Skill directory')
    if not args.ffmpeg:
        p.error('FFmpeg required: install on PATH or supply --ffmpeg')
    try:
        before = {'captions': sha(args.captions), 'audio': sha(args.audio)}
        findings = candidates(json.loads(args.captions.read_text(encoding='utf-8-sig')))
        findings += silence(args.audio, args.ffmpeg)
        if before != {'captions': sha(args.captions), 'audio': sha(args.audio)}:
            raise ValueError('Inputs changed during review')
        report = {'status': 'SEMANTIC_REVIEW_REQUIRED', 'input_sha256': before,
                  'coordinate': 'final_output_seconds', 'findings': findings,
                  'note': 'Caption-level locations; inspect original sound before editing.'}
        with args.output.open('x', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(json.dumps({'status': report['status'], 'candidates': len(findings)}))
        return 0
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as exc:
        p.exit(2, str(exc) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
