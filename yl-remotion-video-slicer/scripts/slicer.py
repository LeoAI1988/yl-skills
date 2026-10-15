"""Frame-based slice manifest -> editable Remotion -> static layers -> MP4.

Local inputs only; no upload, deletion, overwrite or implicit cache reuse.
"""
from pathlib import Path
from fractions import Fraction
import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess

HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def run(argv):
    return subprocess.run([str(v) for v in argv], check=True, capture_output=True).stdout


def probe(path, ffprobe, count=False):
    cmd = [ffprobe, '-v', 'error'] + (['-count_frames'] if count else [])
    return json.loads(run(cmd + ['-show_streams', '-show_format', '-of', 'json', path]))


def integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError('Expected integer >= ' + str(minimum) + ': ' + label)
    return value


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9-]{0,63}', value):
        raise ValueError('Invalid ID: ' + repr(value))
    return value


def timeline_sha(clip, fps):
    return fingerprint({'fps': str(Fraction(fps)), 'segments': [
        [s['source_start_frame'], s['source_end_frame']] for s in clip['segments']]})


def map_masks(segments, masks):
    result = []
    for s in segments:
        for mask in masks:
            lo = max(s['source_start_frame'], mask['source_start_frame'])
            hi = min(s['source_end_frame'], mask['source_end_frame'])
            if lo < hi:
                result.append({'id': mask['id'],
                               'start': s['output_start_frame'] + lo - s['source_start_frame'],
                               'end': s['output_start_frame'] + hi - s['source_start_frame']})
    return result


def validate(data):
    if data.get('schema_version') != 1:
        raise ValueError('Expected schema_version 1')
    fps = Fraction(data['fps'])
    if fps <= 0 or fps > 240:
        raise ValueError('Invalid frame rate')
    for k in ('width', 'height', 'source_frames'):
        integer(data[k], k, 1)
    if data['width'] % 2 or data['height'] % 2:
        raise ValueError('Static SDR export requires even dimensions')
    panel = data.get('style', {}).get('title_panel')
    if panel:
        if len(panel['rect']) != 4:
            raise ValueError('Expected title panel rect [x,y,width,height]')
        x, y, w, h = [integer(v, 'title_panel.rect', 0 if i < 2 else 1) for i, v in enumerate(panel['rect'])]
        if x+w > data['width'] or y+h > data['height']:
            raise ValueError('Title panel outside frame')
        opacity = panel.get('opacity', 0.6)
        if type(opacity) not in (int, float) or not 0 <= opacity <= 1:
            raise ValueError('Title panel opacity must be between zero and one')
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', panel.get('color', '#000000')):
            raise ValueError('Title panel color must be #RRGGBB; use opacity separately')
    seen = set()
    for m in data.get('masks', []):
        mid = safe_id(m['id'])
        if mid in seen:
            raise ValueError('Duplicate mask')
        seen.add(mid)
        a = integer(m['source_start_frame'], 'mask.start')
        b = integer(m['source_end_frame'], 'mask.end', 1)
        if not a < b <= data['source_frames']:
            raise ValueError('Mask outside source')
        rect = m['rect']
        if len(rect) != 4:
            raise ValueError('Expected rect [x,y,width,height]')
        x, y, w, h = [integer(v, 'mask.rect', 0 if i < 2 else 1) for i, v in enumerate(rect)]
        if x + w > data['width'] or y + h > data['height']:
            raise ValueError('Mask outside frame')
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', m.get('color', '#111111')):
            raise ValueError('Mask background must be opaque #RRGGBB')
        if not isinstance(m.get('text', ''), str):
            raise ValueError('Mask text must be a string')
    seen = set()
    if not data.get('clips'):
        raise ValueError('No clips')
    for c in data['clips']:
        cid = safe_id(c['id'])
        if cid in seen:
            raise ValueError('Duplicate clip')
        seen.add(cid)
        if not c.get('segments'):
            raise ValueError('Empty segments')
        offset = 0
        for s in c['segments']:
            a = integer(s['source_start_frame'], 'segment.start')
            b = integer(s['source_end_frame'], 'segment.end', 1)
            if not a < b <= data['source_frames']:
                raise ValueError('Segment outside source')
            if not isinstance(s.get('text'), str) or not s['text'].strip():
                raise ValueError('Each segment needs full retained source text')
            s['output_start_frame'] = offset
            offset += b - a
            s['output_end_frame'] = offset
        c['duration_frames'] = offset
        c['timeline_sha256'] = timeline_sha(c, fps)
        c['mask_ranges'] = map_masks(c['segments'], data.get('masks', []))
        title = c.get('title')
        if title:
            if not title.get('lines') or not all(isinstance(v, str) for v in title['lines']):
                raise ValueError('Title requires lines of text')
            integer(title['duration_frames'], 'title.duration', 1)
            title['duration_frames'] = min(title['duration_frames'], offset)
        if c.get('approved_audio') and c['approved_audio']['timeline_sha256'] != c['timeline_sha256']:
            raise ValueError('Approved audio timeline differs: ' + cid)
    return data


def source_check(data, ffprobe):
    p = probe(data['source'], ffprobe, True)
    v = next(s for s in p['streams'] if s['codec_type'] == 'video')
    if not any(s['codec_type'] == 'audio' for s in p['streams']):
        raise ValueError('Source has no audio; use an explicit silent-video workflow')
    if (v['width'], v['height']) != (data['width'], data['height']):
        raise ValueError('Dimensions differ from source')
    if any(Fraction(v[k]) != Fraction(data['fps']) for k in ('avg_frame_rate', 'r_frame_rate')):
        raise ValueError('CFR/fps mismatch; normalize VFR with an explicit source mapping first')
    if int(v['nb_read_frames']) != data['source_frames']:
        raise ValueError('Source frame count mismatch')
    if v.get('sample_aspect_ratio', '1:1') not in ('1:1', 'N/A'):
        raise ValueError('Normalize non-square pixels first')
    if any(float(x.get('rotation', 0)) for x in v.get('side_data_list', [])) or float(v.get('tags', {}).get('rotate', 0)):
        raise ValueError('Normalize rotation first')
    if v.get('color_transfer') in ('smpte2084', 'arib-std-b67') or '10' in v.get('pix_fmt', ''):
        raise ValueError('HDR/10-bit needs an explicitly verified color workflow')
    return p


def resolve_input(path, base):
    p = Path(path)
    return str((p if p.is_absolute() else base / p).resolve(strict=True))


def generate(data, project):
    j = lambda v: json.dumps(v, ensure_ascii=False)
    fps = float(Fraction(data['fps']))
    w, h = data['width'], data['height']
    components = ["import React from 'react';",
                  "import {Composition, Sequence, registerRoot, staticFile, useVideoConfig} from 'remotion';",
                  "import {Video} from '@remotion/media';", "import {Layer} from './Layer';"]
    registrations, layers = [], []
    for i, c in enumerate(data['clips']):
        nodes = []
        for k, s in enumerate(c['segments']):
            n = s['source_end_frame'] - s['source_start_frame']
            nodes.append(f'<Video name="Segment{k + 1}" src={{staticFile("source.mp4")}} from={{{s["output_start_frame"]}}} trimBefore={{{s["source_start_frame"]}}} durationInFrames={{{n}}} premountFor={{fps}} style={{{{width:"100%",height:"100%",objectFit:"contain"}}}} />')
        layer_title = None
        if c.get('title'):
            lid = c['id'] + '-Title'
            layer_title = lid
            components.append(f'const Title{i} = () => <Layer title={{{j(c["title"])}}} styleConfig={{{j(data.get("style", {}))}}} font={{{j(data.get("public_font"))}}} />;')
            registrations.append(f'<Composition id="{lid}" component={{Title{i}}} durationInFrames={{1}} fps={{{fps}}} width={{{w}}} height={{{h}}} />')
            layers.append(lid)
        for k, r in enumerate(c['mask_ranges']):
            mi = next(n for n, m in enumerate(data.get('masks', [])) if m['id'] == r['id'])
            nodes.append(f'<Sequence name="Mask{k + 1}" from={{{r["start"]}}} durationInFrames={{{r["end"] - r["start"]}}} premountFor={{fps}}><Mask{mi} /></Sequence>')
        if c.get('title'):
            nodes.append(f'<Sequence name="Title" from={{0}} durationInFrames={{{c["title"]["duration_frames"]}}} premountFor={{fps}}><Title{i} /></Sequence>')
        components.append(f'const Clip{i} = () => {{ const {{fps}}=useVideoConfig(); return <>{"".join(nodes)}</>; }};')
        registrations.append(f'<Composition id="{c["id"]}" component={{Clip{i}}} durationInFrames={{{c["duration_frames"]}}} fps={{{fps}}} width={{{w}}} height={{{h}}} />')
        c['title_layer'] = layer_title
    for i, m in enumerate(data.get('masks', [])):
        components.append(f'const Mask{i} = () => <Layer mask={{{j(m)}}} styleConfig={{{j(data.get("style", {}))}}} font={{{j(data.get("public_font"))}}} />;')
        lid = m['id'] + '-Mask'
        layers.append(lid)
        registrations.append(f'<Composition id="{lid}" component={{Mask{i}}} durationInFrames={{1}} fps={{{fps}}} width={{{w}}} height={{{h}}} />')
    components.append('const Root=()=><>' + ''.join(registrations) + '</>;\nregisterRoot(Root);')
    (project / 'index.tsx').write_text('\n'.join(components) + '\n', encoding='utf-8')
    for name in ('Layer.tsx', 'render-layers.mjs', 'package.json'):
        shutil.copyfile(HERE.parent / 'templates' / name, project / name)
    write(project / 'layer-list.json', layers)


def project_hash(project):
    names = ['index.tsx', 'Layer.tsx', 'render-layers.mjs', 'package.json', 'layer-list.json', 'manifest.json']
    names += [p.relative_to(project).as_posix() for p in (project / 'public').iterdir() if p.is_file()]
    return fingerprint({n: sha(project / n) for n in sorted(names)})


def prepare(manifest, output, ffprobe):
    data = validate(read(manifest))
    base = Path(manifest).resolve().parent
    for k in ('source', 'preview_source', 'font_file'):
        if data.get(k):
            data[k] = resolve_input(data[k], base)
    source_check(data, ffprobe)
    if data.get('preview_source'):
        source_check({**data, 'source': data['preview_source']}, ffprobe)
    inputs = {data['source']: sha(data['source'])}
    for k in ('preview_source', 'font_file'):
        if data.get(k):
            inputs[data[k]] = sha(data[k])
    for c in data['clips']:
        if c.get('approved_audio'):
            a = c['approved_audio']
            a['path'] = resolve_input(a['path'], base)
            inputs[a['path']] = sha(a['path'])
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    project = output / 'Remotion'
    (project / 'public').mkdir(parents=True)
    shutil.copyfile(data.get('preview_source') or data['source'], project / 'public' / 'source.mp4')
    if data.get('font_file'):
        data['public_font'] = 'font' + Path(data['font_file']).suffix.lower()
        shutil.copyfile(data['font_file'], project / 'public' / data['public_font'])
    generate(data, project)
    write(project / 'manifest.json', data)
    binding = {'inputs': inputs, 'project_sha256': project_hash(project),
               'tool_sha256': sha(__file__), 'source_probe': probe(data['source'], ffprobe)}
    write(project / 'binding.json', binding)
    write(output / 'mapping.json', data)
    transcript = []
    for c in data['clips']:
        transcript += ['## ' + c['id'] + ' ' + c.get('topic', ''),
                       '标题：' + ' / '.join((c.get('title') or {}).get('lines', [])),
                       '时长：' + str(round(c['duration_frames'] / float(Fraction(data['fps'])), 3)) + '秒', '',
                       '\n'.join(s['text'] for s in c['segments']), '']
    (output / '切片顺读稿.md').write_text('\n'.join(transcript), encoding='utf-8')
    return {'status': 'prepared', 'project': str(project), 'clips': len(data['clips'])}


def bound(project):
    project = Path(project).resolve()
    binding = read(project / 'binding.json')
    if binding['tool_sha256'] != sha(__file__) or binding['project_sha256'] != project_hash(project):
        raise ValueError('Project/tool changed; reconcile edits and prepare a new version')
    for p, expected in binding['inputs'].items():
        if sha(p) != expected:
            raise ValueError('Input changed: ' + p)
    return project, read(project / 'manifest.json'), binding


def export(project, ffmpeg, ffprobe):
    project, data, binding = bound(project)
    receipt = read(project / 'layers' / 'receipt.json')
    if receipt['project_sha256'] != binding['project_sha256']:
        raise ValueError('Layers do not match project')
    for lid in read(project / 'layer-list.json'):
        png = project / 'layers' / (lid + '.png')
        if sha(png) != receipt['files'][lid]:
            raise ValueError('Layer changed: ' + lid)
        rgba = run([ffmpeg, '-v', 'error', '-i', png, '-frames:v', '1', '-pix_fmt', 'rgba', '-f', 'rawvideo', '-'])
        if len(rgba) != data['width'] * data['height'] * 4 or max(rgba[3::4]) != 255:
            raise ValueError('Wrong layer dimensions or empty alpha: ' + lid)
    out = project.parent / 'exports'
    out.mkdir(exist_ok=False)
    fps = Fraction(data['fps'])
    sec = lambda n: f'{float(n / fps):.12f}'
    reports = []
    for c in data['clips']:
        video = out / (c['id'] + '-video.mp4')
        audio = out / (c['id'] + '-audio.m4a')
        final = out / (c['id'] + '.mp4')
        cmd = [ffmpeg, '-v', 'error', '-nostdin', '-n', '-filter_complex_threads', '2']
        graph, labels = [], []
        for i, s in enumerate(c['segments']):
            n = s['source_end_frame'] - s['source_start_frame']
            cmd += ['-ss', sec(s['source_start_frame']), '-t', sec(n + 2), '-i', data['source']]
            graph.append(f'[{i}:v]trim=end_frame={n},setpts=N/({fps.numerator}/{fps.denominator}*TB),setsar=1[v{i}]')
            labels.append(f'[v{i}]')
        graph.append(''.join(labels) + f'concat=n={len(labels)}:v=1:a=0[base]')
        current = 'base'
        idx = len(labels)
        for m in data.get('masks', []):
            ranges = [r for r in c['mask_ranges'] if r['id'] == m['id']]
            if not ranges:
                continue
            cmd += ['-loop', '1', '-framerate', str(fps), '-i', project / 'layers' / (m['id'] + '-Mask.png')]
            enable = '+'.join(f'between(n,{r["start"]},{r["end"] - 1})' for r in ranges)
            graph.append(f"[{current}][{idx}:v]overlay=format=yuv420:enable='{enable}'[m{idx}]")
            current = 'm' + str(idx)
            idx += 1
        if c.get('title_layer'):
            cmd += ['-loop', '1', '-framerate', str(fps), '-i', project / 'layers' / (c['title_layer'] + '.png')]
            graph.append(f"[{current}][{idx}:v]overlay=format=yuv420:enable='lt(n,{c['title']['duration_frames']})'[titled]")
            current = 'titled'
        cmd += ['-filter_complex', ';'.join(graph), '-map', '[' + current + ']', '-an', '-frames:v',
                str(c['duration_frames']), '-r', str(fps), '-c:v', 'libx264', '-crf', '16', '-preset', 'medium',
                '-threads', '2', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', video]
        run(cmd)
        if c.get('approved_audio'):
            audio = Path(c['approved_audio']['path'])
            streams = probe(audio, ffprobe)['streams']
            a = next(s for s in streams if s['codec_type'] == 'audio')
            if a['codec_name'] != 'aac':
                raise ValueError('Approved reference must have AAC for packet-copy mode')
        else:
            graph, labels = [], []
            for i, s in enumerate(c['segments']):
                graph.append(f'[0:a]atrim=start={sec(s["source_start_frame"])}:end={sec(s["source_end_frame"])},asetpts=PTS-STARTPTS[a{i}]')
                labels.append(f'[a{i}]')
            graph.append(''.join(labels) + f'concat=n={len(labels)}:v=0:a=1[aout]')
            run([ffmpeg, '-v', 'error', '-nostdin', '-n', '-i', data['source'], '-filter_complex',
                 ';'.join(graph), '-map', '[aout]', '-c:a', 'aac', '-b:a', '192k', audio])
        run([ffmpeg, '-v', 'error', '-nostdin', '-n', '-i', video, '-i', audio, '-map', '0:v:0',
             '-map', '1:a:0', '-c', 'copy', '-map_metadata', '-1', '-movflags', '+faststart', final])
        reports.append({'id': c['id'], 'file': str(final), 'sha256': sha(final),
                        'audio_reference': str(audio), 'approved_audio_copy': bool(c.get('approved_audio')),
                        'timeline_sha256': c['timeline_sha256']})
    write(out / 'export.json', {'project_sha256': binding['project_sha256'], 'clips': reports})
    return verify(project, ffmpeg, ffprobe)


def audio_packets(path, ffprobe):
    p = json.loads(run([ffprobe, '-v', 'error', '-select_streams', 'a:0', '-show_packets',
                       '-show_data_hash', 'sha256', '-show_entries', 'packet=data_hash', '-of', 'json', path]))
    return [x['data_hash'] for x in p['packets']]


def verify(project, ffmpeg, ffprobe):
    project, data, binding = bound(project)
    out = project.parent / 'exports'
    records = read(out / 'export.json')
    if records['project_sha256'] != binding['project_sha256']:
        raise ValueError('Export binding mismatch')
    if [x['id'] for x in records['clips']] != [c['id'] for c in data['clips']]:
        raise ValueError('Missing exports')
    results = []
    for c, r in zip(data['clips'], records['clips']):
        if sha(r['file']) != r['sha256']:
            raise ValueError('Output changed')
        run([ffmpeg, '-v', 'error', '-i', r['file'], '-f', 'null', '-'])
        p = probe(r['file'], ffprobe, True)
        v = next(s for s in p['streams'] if s['codec_type'] == 'video')
        a = next(s for s in p['streams'] if s['codec_type'] == 'audio')
        if (int(v['nb_read_frames']), v['width'], v['height'], Fraction(v['avg_frame_rate'])) != (
                c['duration_frames'], data['width'], data['height'], Fraction(data['fps'])):
            raise ValueError('Video spec/frame mismatch: ' + c['id'])
        duration = float(Fraction(c['duration_frames']) / Fraction(data['fps']))
        if abs(float(a['duration']) - duration) > 0.1 or abs(float(a.get('start_time', 0))) > 0.05:
            raise ValueError('Audio duration/start mismatch: ' + c['id'])
        packets = audio_packets(r['file'], ffprobe)
        if not packets or packets != audio_packets(r['audio_reference'], ffprobe):
            raise ValueError('AAC packets changed')
        results.append({'id': c['id'], 'decode': 'passed', 'frames': 'passed', 'audio_packets': 'identical',
                        'visual_review': 'pending', 'listening_review': 'pending',
                        'semantic_completeness': 'pending', 'mask_coverage': 'pending'})
    write(out / 'verification.json', {'technical': 'passed', 'clips': results})
    cards = []
    for c in data['clips']:
        cid = html.escape(c['id'])
        text = html.escape(c.get('topic', c['id']))
        cards.append(f'<article><h2>{cid} {text}</h2><video controls preload="metadata" src="exports/{cid}.mp4"></video><p><a href="exports/{cid}.mp4" download>保存本条MP4</a></p></article>')
    page = '<!doctype html><meta charset="utf-8"><title>短视频预览</title><style>body{background:#151515;color:#fff;font-family:sans-serif;padding:24px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:24px}video{width:100%}a{color:#ffd400}article{padding:16px;background:#242424}</style><h1>短视频预览</h1><main>' + ''.join(cards) + '</main>'
    (project.parent / '视频预览.html').write_text(page, encoding='utf-8')
    return {'technical': 'passed', 'clips': len(results), 'human_review': 'pending'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    v = sub.add_parser('validate'); v.add_argument('manifest', type=Path)
    a = sub.add_parser('prepare'); a.add_argument('manifest', type=Path); a.add_argument('output', type=Path)
    a.add_argument('--ffprobe', default='ffprobe')
    for name in ('export', 'verify'):
        a = sub.add_parser(name); a.add_argument('project', type=Path)
        a.add_argument('--ffmpeg', default='ffmpeg'); a.add_argument('--ffprobe', default='ffprobe')
    args = p.parse_args()
    if args.command == 'validate':
        d = validate(read(args.manifest))
        result = {'valid': True, 'clips': [{k: c[k] for k in ('id', 'duration_frames', 'timeline_sha256', 'mask_ranges')} for c in d['clips']]}
    elif args.command == 'prepare':
        result = prepare(args.manifest, args.output, args.ffprobe)
    else:
        result = globals()[args.command](args.project, args.ffmpeg, args.ffprobe)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
