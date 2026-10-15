"""Portable course candidate scanning and reviewed FFmpeg timeline export. MIT."""
import argparse
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''):
            h.update(b)
    return h.hexdigest()


def probe(path, binary):
    return json.loads(subprocess.check_output([binary, '-v', 'error', '-show_format',
                    '-show_streams', '-of', 'json', str(path)]))


def words(asr):
    return [w for s in asr['segments'] for w in s.get('words', [])]


def candidates(asr):
    ww = words(asr)
    out = []
    def add(kind, start, end, text):
        out.append({'id': f'{kind}-{len(out)+1:05d}', 'type': kind,
                    'start': start, 'end': end, 'context': text,
                    'action': 'pending', 'reason': ''})
    for i, w in enumerate(ww):
        text = re.sub(r'[\W_]', '', w['word'])
        ctx = ''.join(z['word'] for z in ww[max(0, i-4):i+8])
        if text in {'嗯', '呃', '那个', '这个'}:
            add('filler', w['start'], w['end'], ctx)
        if i:
            prev = ww[i-1]
            if w['start']-prev['end'] > .5:
                add('gap', prev['end'], w['start'], ctx)
            if text and text == re.sub(r'[\W_]', '', prev['word']):
                add('stutter', prev['start'], w['end'], ctx)
        for n in range(2, min(10, (len(ww)-i)//2)+1):
            a = ''.join(z['word'] for z in ww[i:i+n])
            b = ''.join(z['word'] for z in ww[i+n:i+2*n])
            a = re.sub(r'[\W_]', '', a); b = re.sub(r'[\W_]', '', b)
            if len(a) >= 4 and a == b:
                add('phrase-repeat', w['start'], ww[i+2*n-1]['end'], ctx)
                break
        for j in range(i+2, min(i+5, len(ww))):
            if (2 <= len(text) <= 4 and ww[j]['end']-w['start'] <= 6
                    and text == re.sub(r'[\W_]', '', ww[j]['word'])):
                add('near-repeat', w['start'], ww[j]['end'], ctx)
        end = i
        while end+1 < len(ww) and ww[end+1]['end']-w['start'] <= 8:
            end += 1
        span = ww[end]['end']-w['start']
        active = sum(max(0, z['end']-z['start']) for z in ww[i:end+1])
        if span >= 5 and active/span <= .55:
            if not out or out[-1]['type'] != 'drift' or w['start'] >= out[-1]['end']:
                add('drift', w['start'], ww[end]['end'], ctx)
    # ASR-negative ranges are only candidates; they may contain valid demo audio.
    cursor = 0
    for w in sorted(ww, key=lambda z: z['start']):
        if w['start']-cursor >= .15:
            add('asr-negative', cursor, w['start'], 'Check original audio and consecutive frames')
        cursor = max(cursor, w['end'])
    if asr.get('duration', cursor)-cursor >= .15:
        add('asr-negative', cursor, asr['duration'], 'Check ending context')
    return out


def width(text):
    return sum(.55 if ord(c) < 128 else 1 for c in text)


def prepare(plan, ffprobe):
    if plan.get('schema_version') != 1:
        raise ValueError('Unsupported plan schema')
    fps = float(plan['fps']); speed = float(plan['speed'])
    if not (1 <= fps <= 120 and .5 <= speed <= 2):
        raise ValueError('Invalid fps/speed')
    for c in plan.get('candidates', []):
        if c.get('action') not in {'cut', 'keep', 'compress', 'subtitle_only'} or not c.get('reason'):
            raise ValueError('Unresolved candidate: '+str(c.get('id')))
    metadata = {}
    for tag, src in plan['sources'].items():
        if sha(src['path']) != src['sha256']:
            raise ValueError('Source changed: '+tag)
        meta = probe(src['path'], ffprobe)
        video = next(z for z in meta['streams'] if z['codec_type'] == 'video')
        a, b = video['avg_frame_rate'].split('/')
        if float(b) == 0 or abs(float(a)/float(b)-fps) > .001:
            raise ValueError('Normalize source frame rate first: '+tag)
        metadata[tag] = meta
    offset = 0; mapping = []; captions = []; mute = []; audio_hashes = {}
    source_ends = {}
    for part in plan['parts']:
        tag = part['source']; src = plan['sources'][tag]
        duration = float(metadata[tag]['format']['duration'])
        local = []
        for start, end in part['keeps']:
            if not (0 <= start < end <= duration+.04):
                raise ValueError('Invalid keep')
            # Inward quantization; coverage checks below prevent eating retained words.
            s = math.ceil(start*fps-1e-7)/fps; e = math.floor(end*fps+1e-7)/fps
            if e <= s:
                raise ValueError('Keep disappears on frame grid')
            if s < source_ends.get(tag, -1)-1e-7:
                raise ValueError('Course source order changed')
            row = {'source': tag, 'start': s, 'end': e, 'offset': offset,
                   'audio_source': part.get('audio_source', src['path'])}
            mapping.append(row); local.append(row)
            offset += e-s; source_ends[tag] = e
            if row['audio_source'] != src['path']:
                ah = sha(row['audio_source'])
                if ah != part.get('audio_sha256'):
                    raise ValueError('Corrected audio changed or unbound')
                audio_hashes[row['audio_source']] = ah
        if src.get('asr'):
            bounds = part.get('bounds', [0, duration])
            deleted = part.get('deletions', [])
            if any(not z.get('reason') for z in deleted):
                raise ValueError('Deletion without rationale')
            for w in words(read(src['asr'])):
                if w['end'] <= bounds[0] or w['start'] >= bounds[1]:
                    continue
                covered = sum(max(0, min(w['end'], r['end'])-max(w['start'], r['start'])) for r in local)
                missing = max(0, w['end']-w['start']-covered)
                if missing > .025 and not any(z['start'] <= w['start']+.025 and z['end'] >= w['end']-.025 for z in deleted):
                    raise ValueError('Unexplained/truncated word: '+w['word']+f" at {w['start']}")
        for c in part.get('captions', []):
            pieces = [r for r in local if c['end'] > r['start'] and c['start'] < r['end']]
            if len(pieces) > 1:
                raise ValueError('Regroup subtitle words at each cut: '+c['text'])
        for r in local:
            for c in part.get('captions', []):
                a = max(c['start'], r['start']); b = min(c['end'], r['end'])
                if b <= a:
                    continue
                if '\n' in c['text'] or '\\' in c['text'] or '{' in c['text'] or '}' in c['text']:
                    raise ValueError('Subtitle must be plain single-line text')
                if width(c['text']) > plan['style'].get('max_em', 19.3) or b-a > 8:
                    raise ValueError('Split subtitle before rendering: '+c['text'])
                captions.append({'start': r['offset']+a-r['start'],
                                 'end': r['offset']+b-r['start'], 'text': c['text']})
            for z in part.get('mute', []):
                if z.get('kind') != 'demo_noise' or not z.get('reason'):
                    raise ValueError('Mute requires reviewed demo_noise classification')
                a = max(z['start'], r['start']); b = min(z['end'], r['end'])
                if b > a:
                    mute.append([r['offset']+a-r['start'], r['offset']+b-r['start']])
    frames = round(offset/speed*fps)
    return {'source_hashes': {k: v['sha256'] for k, v in plan['sources'].items()},
            'mapping': mapping, 'captions': captions, 'mute': mute, 'audio_hashes': audio_hashes,
            'frames': frames, 'duration': frames/fps, 'speed': speed,
            'fps': fps, 'metadata': metadata, 'perceptual_review': 'pending'}


def timestamp(t):
    t = round(t*100); h, t = divmod(t, 360000); m, t = divmod(t, 6000); s, cs = divmod(t, 100)
    return f'{h}:{m:02d}:{s:02d}.{cs:02d}'


def ass(path, captions, style):
    font = style.get('font', 'Arial')
    if any(c in font for c in ',\n\r'):
        raise ValueError('Invalid font')
    txt = '[Script Info]\nScriptType: v4.00+\nPlayResX: 1620\nPlayResY: 1080\nWrapStyle: 2\n'
    txt += '[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n'
    txt += f"Style: Default,{font},{style.get('fontsize',76)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{style.get('outline',3)},0,2,40,40,{style.get('margin_v',70)},1\n"
    txt += '[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n'
    for c in sorted(captions, key=lambda z: z['start']):
        txt += f"Dialogue: 0,{timestamp(c['start'])},{timestamp(c['end'])},Default,,0,0,0,,{c['text']}\n"
    path.write_text(txt, encoding='utf-8-sig')


def render(plan, prepared, ffmpeg):
    work = Path(plan['workdir']); work.mkdir(parents=True, exist_ok=True)
    out = Path(plan['output'])
    if out.exists():
        raise ValueError('Use a new output version; overwrite refused')
    ass(work/'course_subs.ass', prepared['captions'], plan['style'])
    cmd = [ffmpeg, '-hide_banner', '-y']; index = {}
    for r in prepared['mapping']:
        for p in (plan['sources'][r['source']]['path'], r['audio_source']):
            if p not in index:
                index[p] = len(index); cmd += ['-i', str(p)]
    graph = []; fps = prepared['fps']; speed = prepared['speed']; w, h = plan['size']
    for i, r in enumerate(prepared['mapping']):
        vi = index[plan['sources'][r['source']]['path']]; ai = index[r['audio_source']]
        graph.append(f"[{vi}:v]trim=start={r['start']:.9f}:end={r['end']:.9f},setpts=PTS-STARTPTS,scale={w}:{h},setsar=1[v{i}]")
        graph.append(f"[{ai}:a]atrim=start={r['start']:.9f}:end={r['end']:.9f},asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[a{i}]")
    n = len(prepared['mapping'])
    graph.append(''.join(f'[v{i}][a{i}]' for i in range(n))+f'concat=n={n}:v=1:a=1[vc][ac]')
    graph.append(f'[vc]subtitles=course_subs.ass,setpts=PTS/{speed},fps={fps}[v]')
    mute = prepared['mute']
    af = ("volume=0:enable='"+'+'.join(f'between(t,{a:.9f},{b:.9f})' for a,b in mute)+"',") if mute else ''
    graph.append(f"[ac]{af}atempo={speed},apad,atrim=duration={prepared['duration']:.9f}[a]")
    (work/'course_filter.txt').write_text(';\n'.join(graph), encoding='utf-8')
    enc = plan.get('encoder', 'libx264')
    if enc == 'libx264':
        encoding = ['-c:v', enc, '-preset', 'fast', '-crf', '21']
    elif enc == 'h264_qsv':
        encoding = ['-c:v', enc, '-global_quality', '21', '-preset', 'veryfast']
    else:
        raise ValueError('Unsupported encoder; validate before extending')
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(out.stem+'.rendering.mp4')
    cmd += ['-filter_complex_threads', '2', '-filter_complex_script', 'course_filter.txt',
            '-map', '[v]', '-map', '[a]', '-frames:v', str(prepared['frames']), *encoding,
            '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(partial)]
    with open(work/'render.log', 'w', encoding='utf-8') as log:
        subprocess.run(cmd, cwd=work, stdout=log, stderr=log, check=True)
    if out.exists():
        raise ValueError('Output appeared during rendering; inspect partial')
    partial.rename(out)


def verify(plan, prepared, ffmpeg, ffprobe):
    out = Path(plan['output']); meta = probe(out, ffprobe)
    subprocess.run([ffmpeg, '-v', 'error', '-xerror', '-i', str(out), '-f', 'null', '-'], check=True)
    delta = abs(float(meta['format']['duration'])-prepared['duration'])
    v = next(s for s in meta['streams'] if s['codec_type'] == 'video')
    if delta > .15 or [v['width'], v['height']] != plan['size']:
        raise ValueError('Export duration or geometry differs')
    return {'technical_decode': 'pass', 'sha256': sha(out), 'duration_delta': delta,
            'metadata': meta, 'source_frame_audio_review': 'pending',
            'subtitle_visual_review': 'pending', 'playback_loudness_review': 'pending',
            'actual_listening': 'pending'}


def main():
    p = argparse.ArgumentParser(description=__doc__); sub = p.add_subparsers(dest='command', required=True)
    s = sub.add_parser('scan'); s.add_argument('--asr', required=True); s.add_argument('--output', required=True)
    for name in ('prepare', 'render', 'verify'):
        s = sub.add_parser(name); s.add_argument('--plan', required=True); s.add_argument('--ffprobe', required=True)
        if name != 'prepare':
            s.add_argument('--ffmpeg', required=True)
    a = p.parse_args()
    if a.command == 'scan':
        result = candidates(read(a.asr)); write(a.output, result); print(json.dumps({'candidates': len(result)})); return
    plan = read(a.plan); work = Path(plan['workdir']); work.mkdir(parents=True, exist_ok=True)
    prepared = prepare(plan, a.ffprobe)
    if a.command == 'verify':
        frozen = read(work/'prepared.json')
        if prepared != frozen:
            raise ValueError('Plan changed since rendering')
        write(work/'verification.json', verify(plan, frozen, a.ffmpeg, a.ffprobe))
    else:
        if a.command == 'render':
            render(plan, prepared, a.ffmpeg)
        write(work/'prepared.json', prepared)
    print(json.dumps({'status': a.command, 'duration': prepared['duration']}))


if __name__ == '__main__':
    main()
