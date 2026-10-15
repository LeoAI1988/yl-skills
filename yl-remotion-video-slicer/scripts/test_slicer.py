"""Behavior tests using synthetic media, never personal recordings."""
from pathlib import Path
import argparse
import copy
import os
import subprocess
import tempfile
import slicer


def rejects(fn):
    try:
        fn()
    except (ValueError, FileExistsError):
        return
    raise AssertionError('Expected rejection')


def attach_modules(project, modules):
    target = project / 'node_modules'
    source = Path(modules).resolve(strict=True)
    if os.name == 'nt':
        env = {**os.environ, 'SLICE_MODULE_SOURCE': str(source), 'SLICE_MODULE_TARGET': str(target)}
        subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                        "$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path $env:SLICE_MODULE_TARGET -Target $env:SLICE_MODULE_SOURCE | Out-Null"], env=env, check=True, capture_output=True)
    else:
        target.symlink_to(source, target_is_directory=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--ffmpeg', default='ffmpeg'); p.add_argument('--ffprobe', default='ffprobe')
    p.add_argument('--node'); p.add_argument('--modules', type=Path); p.add_argument('--font', type=Path)
    p.add_argument('--output', type=Path, help='Retained isolated test root; must not exist')
    p.add_argument('--browser', type=Path, help='Optional verified Chromium executable')
    a = p.parse_args()
    render_env = {**os.environ}
    if a.browser:
        render_env['YL_SLICE_BROWSER'] = str(a.browser.resolve(strict=True))
    # Retained for review; do not recursively remove a tree containing shared module links.
    root = a.output.resolve() if a.output else Path(tempfile.mkdtemp(prefix='yl-slicer-test-')) / '中文 空格'
    root.mkdir(parents=True, exist_ok=False)
    source = root / 'source.mp4'
    slicer.run([a.ffmpeg, '-v', 'error', '-n', '-f', 'lavfi', '-i', 'testsrc2=size=320x240:rate=30:duration=6',
                '-f', 'lavfi', '-i', 'sine=frequency=1000:sample_rate=48000:duration=6',
                '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', source])
    data = {'schema_version': 1, 'source': 'source.mp4', 'fps': '30/1', 'width': 320, 'height': 240,
            'source_frames': 180, 'style': {'font_size': 24, 'font_weight': 900, 'title_top': 10,
                                         'title_left': 10, 'title_width': 280},
            'masks': [{'id': 'QrA', 'source_start_frame': 60, 'source_end_frame': 160,
                       'rect': [230, 100, 80, 100], 'text': 'Link', 'font_size': 16, 'color': '#111111'}],
            'clips': [{'id': 'Clip01', 'topic': 'Reordered sample', 'hook_reason': 'source result first',
                       'ending': 'complete', 'title': {'lines': ['Sample title'], 'duration_frames': 30},
                       'segments': [{'source_start_frame': 120, 'source_end_frame': 180, 'text': 'Result first.'},
                                    {'source_start_frame': 30, 'source_end_frame': 90, 'text': 'Explanation.'}]},
                      {'id': 'Clip02', 'topic': 'Overlap sample', 'segments': [
                          {'source_start_frame': 75, 'source_end_frame': 135, 'text': 'Independent overlapping sample.'}]}]}
    if a.font:
        data['font_file'] = str(a.font.resolve())
    data['style']['title_panel'] = {'rect': [8, 4, 290, 62], 'color': '#000000', 'opacity': 0.62}
    data['style']['line_colors'] = ['#ffffff', '#FEE10C']
    data['style']['title_align'] = 'center'
    d = slicer.validate(copy.deepcopy(data))
    assert d['clips'][0]['duration_frames'] == 120
    assert d['clips'][0]['mask_ranges'] == [{'id': 'QrA', 'start': 0, 'end': 40}, {'id': 'QrA', 'start': 90, 'end': 120}]
    assert d['clips'][1]['mask_ranges'] == [{'id': 'QrA', 'start': 0, 'end': 60}]
    for mutate in (lambda d: d['clips'][0]['segments'][0].update(source_end_frame=181),
                   lambda d: d['masks'][0].update(color='#11111188'),
                   lambda d: d['style']['title_panel'].update(opacity=2),
                   lambda d: d['clips'][0].update(id='../bad'),
                   lambda d: d['clips'][0]['segments'][0].update(text='')):
        bad = copy.deepcopy(data); mutate(bad)
        rejects(lambda: slicer.validate(bad))
    manifest = root / 'manifest.json'; slicer.write(manifest, data)
    output = root / 'v1'
    slicer.prepare(manifest, output, a.ffprobe)
    rejects(lambda: slicer.prepare(manifest, output, a.ffprobe))
    project = output / 'Remotion'
    nodes = (project / 'index.tsx').read_text(encoding='utf-8')
    assert nodes.count('<Video ') == 3 and nodes.count('id="Clip01"') == 1
    assert '字幕' not in nodes and 'Captions' not in nodes
    slicer.bound(project)
    original = (project / 'index.tsx').read_bytes()
    (project / 'index.tsx').write_bytes(original + b'\n// deliberate stale edit\n')
    rejects(lambda: slicer.bound(project))
    (project / 'index.tsx').write_bytes(original)
    if not (a.node and a.modules):
        print('PASS: mapping, constraints, independent nodes, stale inputs, overwrite refusal. Remotion export not requested.')
        print(root); return
    attach_modules(project, a.modules)
    subprocess.run([a.node, 'render-layers.mjs'], cwd=project, env=render_env, check=True)
    rgba = slicer.run([a.ffmpeg, '-v', 'error', '-i', project/'layers/Clip01-Title.png',
                      '-frames:v', '1', '-pix_fmt', 'rgba', '-f', 'rawvideo', '-'])
    assert 150 <= rgba[(6*320+12)*4+3] <= 165, 'Panel must be translucent; text remains opaque'
    assert slicer.export(project, a.ffmpeg, a.ffprobe)['technical'] == 'passed'
    rejects(lambda: slicer.export(project, a.ffmpeg, a.ffprobe))
    # Validate static mask pixel at all active frame boundaries after actual export.
    def pixel(n, xy):
        raw = slicer.run([a.ffmpeg, '-v', 'error', '-i', output / 'exports' / 'Clip01.mp4', '-vf',
                          f'select=eq(n\\,{n})', '-frames:v', '1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'])
        i = (xy[1] * 320 + xy[0]) * 3
        return raw[i:i + 3]
    for n in (0, 39, 90, 119):
        assert all(5 <= value <= 30 for value in pixel(n, (240, 190))), (n, pixel(n, (240, 190)))
    def region(path, n):
        return slicer.run([a.ffmpeg, '-v', 'error', '-i', path, '-vf',
                          f'select=eq(n\\,{n}),crop=120:80:20:120', '-frames:v', '1',
                          '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'])
    for n, original_frame in ((0, 120), (59, 179), (60, 30), (119, 89)):
        left = region(output / 'exports' / 'Clip01.mp4', n)
        right = region(source, original_frame)
        assert len(left) == len(right) == 120 * 80 * 3
        assert sum(abs(x-y) for x,y in zip(left,right)) / len(left) < 8, 'Wrong reordered source frame'
    # Packaging revision copies approved AAC; no extra captions, title can be added/removed independently.
    revision = copy.deepcopy(data)
    for c, old in zip(revision['clips'], d['clips']):
        c['approved_audio'] = {'path': str(output / 'exports' / (c['id'] + '.mp4')),
                               'timeline_sha256': old['timeline_sha256']}
    revision['clips'][0]['title']['lines'] = ['New title only']
    revision['clips'][1]['title'] = {'lines': ['Second title'], 'duration_frames': 30}
    revision_manifest = root / 'revision.json'; slicer.write(revision_manifest, revision)
    slicer.prepare(revision_manifest, root / 'v2', a.ffprobe)
    p2 = root / 'v2' / 'Remotion'; attach_modules(p2, a.modules)
    subprocess.run([a.node, 'render-layers.mjs'], cwd=p2, env=render_env, check=True)
    assert slicer.export(p2, a.ffmpeg, a.ffprobe)['technical'] == 'passed'
    for c in d['clips']:
        assert slicer.audio_packets(output / 'exports' / (c['id'] + '.mp4'), a.ffprobe) == slicer.audio_packets(root / 'v2' / 'exports' / (c['id'] + '.mp4'), a.ffprobe)
    wrong = copy.deepcopy(revision)
    wrong['clips'][0]['segments'][0]['source_start_frame'] += 1
    rejects(lambda: slicer.validate(wrong))
    png = p2 / 'layers' / 'QrA-Mask.png'; saved = png.read_bytes(); png.write_bytes(saved + b'stale')
    rejects(lambda: slicer.export(p2, a.ffmpeg, a.ffprobe))
    png.write_bytes(saved)
    slicer.write(root / 'test-result.json', {'status': 'passed', 'mapping': 'reordered and overlapping',
                 'mask_pixels': 'four boundaries', 'export': 'two versions, two clips each',
                 'aac_packets': 'unchanged in packaging revision', 'no_new_subtitles': True,
                 'stale_binding': 'rejected', 'human_quality': 'not evaluated'})
    print('PASS: real Remotion layers, full decode/frame check, mask boundaries, AAC copy, stale layer rejection.')
    print(root)


if __name__ == '__main__':
    main()
