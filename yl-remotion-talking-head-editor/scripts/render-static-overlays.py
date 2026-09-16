#!/usr/bin/env python3
"""Encode camera footage once per variant with frame-timed transparent PNG overlays.

Supported EDL: source, fps (positive integer), width, height, outputFrames,
playbackRate, and ascending nonoverlapping keeps containing sourceStartFrame /
sourceEndFrame. Frames refer to the source AFTER fps=fps:start_time=0 normalization;
end frames are exclusive. sourceFps must match fps unless frameGridFps explicitly
declares the normalized grid. Reordering, prependCuts, mixed speed, and cropping
are deliberately unsupported. The supplied AAC audio must already be edited and
sped up to this EDL; it is copied, never re-encoded or sped up again.

Color conversion is automatic from actual source metadata: verified BT.2020 HLG
is tone mapped to SDR, and clean BT.709 SDR is retained. The legacy --tone-map-hlg
flag asserts that the input is HLG; applying it to SDR/PQ/unknown input is rejected.
PQ, mixed or unknown color metadata needs a dedicated color-managed conversion.
Mild enhancement remains an explicit opt-in.
All outputs must be new files. Commands, concatenation lists, progress, metadata,
and results are written to a unique run folder below --work-dir.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import time
import uuid


class ValidationError(ValueError):
    pass


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def positive_integer(value, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValidationError(f'{label} must be a positive integer')
    return value


def resolve_input(value: str, relative_to: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = relative_to / path
    path = path.resolve()
    if not path.is_file():
        raise ValidationError(f'Input file not found: {path}')
    return path


def find_program(explicit: str | None, name: str, sibling: Path | None = None) -> str:
    if explicit:
        found = shutil.which(explicit) or (str(Path(explicit).resolve()) if Path(explicit).is_file() else None)
        if not found:
            raise ValidationError(f'{name} not found: {explicit}')
        return found
    suffix = '.exe' if os.name == 'nt' else ''
    if sibling and (sibling.parent / (name + suffix)).is_file():
        return str(sibling.parent / (name + suffix))
    found = shutil.which(name)
    if found:
        return found
    if name == 'ffmpeg':
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            pass
    raise ValidationError(f'Cannot locate {name}; pass --{name} explicitly')


def probe(program: str, path: Path, count_frames=False):
    command = [program, '-v', 'error']
    if count_frames:
        command.append('-count_frames')
    command += ['-show_streams', '-show_format', '-of', 'json', str(path)]
    completed = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if completed.returncode:
        raise ValidationError(f'ffprobe failed for {path}: {completed.stderr[-2000:]}')
    return json.loads(completed.stdout)


SDR_SETPARAMS = 'setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709'
HLG_TO_SDR = ('zscale=t=linear:npl=100,format=gbrpf32le,'
              'tonemap=tonemap=hable:desat=0,zscale=p=bt709:t=bt709:m=bt709:r=tv,')


def mp4_colr(path: Path):
    """Inspect MP4/MOV container labels independently of ffprobe's codec labels."""
    records = []
    if path.suffix.lower() not in ('.mp4', '.mov', '.m4v'):
        return records
    total = path.stat().st_size
    with path.open('rb') as handle:
        while handle.tell() + 8 <= total:
            header = handle.read(8)
            size, kind = struct.unpack('>I4s', header)
            header_size = 8
            if size == 1:
                extra = handle.read(8)
                if len(extra) != 8:
                    raise ValidationError('Truncated MP4 extended atom header')
                size, header_size = struct.unpack('>Q', extra)[0], 16
            elif size == 0:
                size = total - handle.tell() + 8
            if size < header_size or handle.tell() + size - header_size > total:
                raise ValidationError('Invalid MP4 atom size while reading color metadata')
            if kind != b'moov':
                handle.seek(size - header_size, 1)
                continue
            data = handle.read(size - header_size)
            # Recognize complete, valid-sized nclc/nclx colr atoms inside moov.
            # Rejecting disagreement is safer than relying on a player's priority.
            for match in re.finditer(b'colr', data):
                offset = match.start()
                if offset < 4 or offset + 14 > len(data):
                    continue
                atom_size = struct.unpack('>I', data[offset - 4:offset])[0]
                color_type = data[offset + 4:offset + 8]
                expected_size = {b'nclc': 18, b'nclx': 19}.get(color_type)
                if atom_size != expected_size or offset - 4 + atom_size > len(data):
                    continue
                primaries, transfer, matrix = struct.unpack('>HHH', data[offset + 8:offset + 14])
                records.append({'type': color_type.decode(), 'primaries': primaries,
                                'transfer': transfer, 'matrix': matrix,
                                'fullRange': bool(data[offset + 14] & 128) if color_type == b'nclx' else None})
    return records


def source_color_policy(stream: dict, source: Path, force_hlg: bool = False):
    """Select a pixel conversion, never a tag-only workaround for HDR."""
    colors = tuple(stream.get(k, 'unknown') for k in ('color_primaries', 'color_transfer', 'color_space'))
    if colors == ('bt2020', 'arib-std-b67', 'bt2020nc'):
        mode, expected = 'HLG-to-SDR-hable-npl100', (9, 18, 9)
    elif colors == ('bt709', 'bt709', 'bt709'):
        mode, expected = 'SDR-BT709', (1, 1, 1)
    else:
        raise ValidationError(f'Unsupported PQ/mixed/unknown source color metadata {colors}; perform a verified color-managed conversion from the original, not retagging')
    if force_hlg and mode == 'SDR-BT709':
        raise ValidationError('--tone-map-hlg requires verified BT.2020 / HLG / BT.2020 matrix input; refusing to tone map SDR')
    if stream.get('color_range') not in ('tv', 'pc'):
        raise ValidationError('Source color range is unknown; do not guess limited/full range')
    container = mp4_colr(source)
    for record in container:
        if tuple(record[k] for k in ('primaries', 'transfer', 'matrix')) != expected:
            raise ValidationError('MP4 container colr disagrees with decoded stream color metadata; inspect the original pixel conversion before proceeding')
        if record['fullRange'] is not None and record['fullRange'] != (stream['color_range'] == 'pc'):
            raise ValidationError('MP4 container full-range flag disagrees with stream metadata')
    return {'mode': mode, 'toneMapHlg': mode != 'SDR-BT709', 'sourceColors': list(colors),
            'sourceRange': stream['color_range'], 'containerColr': container, 'selection': 'actual-source-probe'}


def validate_sdr_color(stream: dict, output: Path):
    policy = source_color_policy(stream, output)
    if policy['toneMapHlg'] or stream.get('color_range') != 'tv':
        raise ValidationError(f'Rendered output must be actual BT.709 limited-range SDR: {output}')
    if output.suffix.lower() == '.mp4' and not policy['containerColr']:
        raise ValidationError(f'Rendered MP4 lacks a verifiable colr atom: {output}')
    return policy


def validate_edl(edl_path: Path):
    edl = read_json(edl_path)
    for key in ('fps', 'width', 'height', 'outputFrames'):
        positive_integer(edl.get(key), f'EDL.{key}')
    if edl['width'] % 2 or edl['height'] % 2:
        raise ValidationError('EDL dimensions must be even for yuv420p')
    fps = edl['fps']
    if edl.get('frameGridFps', edl.get('sourceFps', fps)) != fps:
        raise ValidationError('EDL keeps must use the normalized fps grid; declare frameGridFps=fps when sourceFps differs')
    rate = edl.get('playbackRate', 1)
    if isinstance(rate, bool) or not isinstance(rate, (float, int)) or not math.isfinite(rate) or rate <= 0:
        raise ValidationError('EDL.playbackRate must be one finite positive number')
    if edl.get('prependCuts'):
        raise ValidationError('prependCuts / reordered hooks need a trim/concat timeline renderer; this select-based script cannot preserve requested reordering')
    keeps = edl.get('keeps')
    if not isinstance(keeps, list) or not keeps:
        raise ValidationError('EDL.keeps must be a nonempty array')
    previous_end, kept_frames = 0, 0
    for i, keep in enumerate(keeps):
        start, end = keep.get('sourceStartFrame'), keep.get('sourceEndFrame')
        if type(start) is not int or type(end) is not int or start < 0 or end <= start:
            raise ValidationError(f'keep {i}: expected nonnegative start and exclusive end integer frames')
        if start < previous_end:
            raise ValidationError(f'keep {i}: reordered or overlapping intervals are unsupported; no silent sorting is performed')
        if any(key in keep and keep[key] != rate for key in ('playbackRate', 'speed')):
            raise ValidationError(f'keep {i}: per-segment speed is unsupported')
        previous_end = end
        kept_frames += end - start
    if abs(edl['outputFrames'] - kept_frames / rate) > 1.000001:
        raise ValidationError('EDL.outputFrames disagrees with kept frame count / playbackRate by more than one rounding frame')
    source = resolve_input(edl.get('source', ''), edl_path.parent)
    return edl, source


def validate_manifest(path: Path, edl: dict):
    manifest = read_json(path)
    for key, expected in (('fps', edl['fps']), ('width', edl['width']), ('height', edl['height']), ('durationInFrames', edl['outputFrames'])):
        if manifest.get(key) != expected:
            raise ValidationError(f'{path.name}: {key} must equal EDL value {expected}')
    states = manifest.get('states')
    if not isinstance(states, list) or not states:
        raise ValidationError(f'{path.name}: states must be a nonempty array')
    cursor, seen, normalized = 0, set(), []
    for i, state in enumerate(states):
        start, end = state.get('startFrame'), state.get('endFrame')
        if type(start) is not int or type(end) is not int or start != cursor or end <= start or end > edl['outputFrames']:
            raise ValidationError(f'{path.name}: state {i} must extend continuous [0, outputFrames) coverage without gaps/overlap')
        image = resolve_input(state.get('image', ''), path.parent)
        if image not in seen:
            with image.open('rb') as handle:
                header = handle.read(33)
            if len(header) < 33 or header[:8] != b'\x89PNG\r\n\x1a\n' or header[12:16] != b'IHDR':
                raise ValidationError(f'Overlay is not a PNG: {image}')
            width, height = struct.unpack('>II', header[16:24])
            if (width, height) != (edl['width'], edl['height']):
                raise ValidationError(f'PNG dimensions differ from EDL: {image} ({width}x{height})')
            if header[25] not in (4, 6):
                raise ValidationError(f'Overlay must have a native alpha channel (RGBA or gray-alpha PNG): {image}')
            seen.add(image)
        normalized.append({**state, 'image': str(image)})
        cursor = end
    if cursor != edl['outputFrames']:
        raise ValidationError(f'{path.name}: final state does not reach outputFrames')
    return {**manifest, 'states': normalized}


def validate_output_geometry(edl: dict, stream: dict, allow_downscale: bool = False):
    """Keep the original display resolution unless a lower deliverable was requested."""
    rotation = next((float(s['rotation']) for s in stream.get('side_data_list', []) if 'rotation' in s),
                    float(stream.get('tags', {}).get('rotate', 0)))
    width, height = stream['width'], stream['height']
    if abs(rotation) % 180 == 90:
        width, height = height, width
    if abs((width / height) / (edl['width'] / edl['height']) - 1) > 0.01:
        raise ValidationError('Source display aspect differs from EDL; this script does not silently crop or stretch')
    if (edl['width'] < width or edl['height'] < height) and not allow_downscale:
        raise ValidationError('EDL lowers source display resolution; retain original dimensions. --allow-downscale is only for an explicitly requested lower delivery size')
    return width, height


def write_concat(path: Path, manifest: dict):
    lines, image = ['ffconcat version 1.0'], ''
    for state in manifest['states']:
        image = Path(state['image']).as_posix().replace("'", "'\\''")
        lines += [f"file '{image}'", f"option framerate {manifest['fps']}",
                  f"duration {(state['endFrame'] - state['startFrame']) / manifest['fps']:.12f}"]
    # The final repeated file makes the last state's duration effective; output is frame-limited.
    lines += [f"file '{image}'", f"option framerate {manifest['fps']}"]
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def build_command(args, run_dir: Path, edl: dict, source: Path, audio: Path, variants, ffmpeg: str):
    fps, rate = edl['fps'], edl.get('playbackRate', 1)
    count = len(variants)
    select = '+'.join(f"between(n,{k['sourceStartFrame']},{k['sourceEndFrame'] - 1})" for k in edl['keeps'])
    last_source_frame = edl['keeps'][-1]['sourceEndFrame']
    base = (f"[0:v:0]fps={fps}:start_time=0,trim=end_frame={last_source_frame},"
            f"select='{select}',setpts=N/({fps * rate:.12g}*TB),fps={fps},")
    if args.tone_map_hlg:
        base += HLG_TO_SDR
    base += f"scale={edl['width']}:{edl['height']}:flags=lanczos:out_color_matrix=bt709:out_range=tv,format=yuv420p,"
    base += SDR_SETPARAMS + ','
    if args.enhance_mild:
        base += 'eq=contrast=1.04:brightness=0.003:saturation=1.015,unsharp=5:5:0.28:3:3:0,'
    base += f"setsar=1,tpad=stop_mode=clone:stop_duration={2 / fps:.12f},trim=end_frame={edl['outputFrames']}"
    base += (f",split={count}" if count > 1 else '') + ''.join(f'[base_{i}]' for i in range(count))
    graph = [base]
    command = [ffmpeg, '-hide_banner', '-loglevel', 'warning', '-nostdin', '-n', '-threads', '4', '-i', str(source)]
    for i, (_, manifest, _) in enumerate(variants):
        concat = run_dir / f'variant_{i:02d}.ffconcat'
        write_concat(concat, manifest)
        command += ['-f', 'concat', '-safe', '0', '-i', str(concat)]
        graph += [f'[{i+1}:v:0]scale=iw:ih:in_range=pc:out_range=tv:out_color_matrix=bt709,format=yuva420p,{SDR_SETPARAMS}[ov_{i}]',
                  f'[base_{i}][ov_{i}]overlay=format=yuv420:eof_action=repeat,{SDR_SETPARAMS}[v_{i}]']
    graph_path = run_dir / 'filter_complex.txt'
    graph_path.write_text(';\n'.join(graph) + '\n', encoding='utf-8')
    command += ['-i', str(audio), '-filter_complex_threads', '3', '-filter_complex_script', str(graph_path),
                '-progress', str(run_dir / 'progress.log')]
    for i, (_, _, output) in enumerate(variants):
        command += ['-map', f'[v_{i}]', '-map', f'{count+1}:a:0', '-frames:v', str(edl['outputFrames']),
                    '-r', str(fps), '-fps_mode', 'cfr', '-c:v', 'libx264', '-preset', args.preset,
                    '-crf', str(args.crf), '-threads', '4', '-pix_fmt', 'yuv420p', '-c:a', 'copy',
                    '-map_metadata', '-1', '-map_chapters', '-1', '-color_primaries', 'bt709',
                    '-color_trc', 'bt709', '-colorspace', 'bt709', '-color_range', 'tv',
                    '-movflags', '+faststart', str(output)]
    return command


def execute(args, run_dir: Path):
    edl_path = resolve_input(args.edl, Path.cwd())
    edl, source = validate_edl(edl_path)
    audio = resolve_input(args.audio, Path.cwd())
    ffmpeg = find_program(args.ffmpeg, 'ffmpeg')
    ffprobe = find_program(args.ffprobe, 'ffprobe', Path(ffmpeg))
    variants, output_paths = [], set()
    for manifest_arg, output_arg in args.variant:
        manifest_path = resolve_input(manifest_arg, Path.cwd())
        output = Path(output_arg).expanduser().resolve()
        if output.suffix.lower() != '.mp4':
            raise ValidationError('Output files must use .mp4')
        if output.exists() or output in output_paths:
            raise ValidationError(f'Refusing to overwrite or duplicate output: {output}')
        variants.append((manifest_path, validate_manifest(manifest_path, edl), output))
        output_paths.add(output)
    source_meta, audio_meta = probe(ffprobe, source), probe(ffprobe, audio)
    video_streams = [s for s in source_meta['streams'] if s['codec_type'] == 'video' and not s.get('disposition', {}).get('attached_pic')]
    audio_streams = [s for s in audio_meta['streams'] if s['codec_type'] == 'audio']
    if len(video_streams) != 1 or len(audio_streams) != 1 or audio_streams[0].get('codec_name') != 'aac':
        raise ValidationError('Source must contain one video stream; --audio must contain exactly one AAC stream')
    stream = video_streams[0]
    color_policy = source_color_policy(stream, source, args.tone_map_hlg)
    args.tone_map_hlg = color_policy['toneMapHlg']
    width, height = validate_output_geometry(edl, stream, args.allow_downscale)
    source_duration = float(stream.get('duration') or source_meta['format'].get('duration') or 0)
    if not source_duration or edl['keeps'][-1]['sourceEndFrame'] / edl['fps'] > source_duration + 1 / edl['fps']:
        raise ValidationError('EDL source frame bounds exceed the probed source duration')
    expected_duration = edl['outputFrames'] / edl['fps']
    audio_duration = float(audio_streams[0].get('duration') or audio_meta['format'].get('duration') or 0)
    audio_duration_method = 'container-or-stream'
    if audio_meta.get('format', {}).get('format_name') in ('aac', 'adts'):
        # Raw ADTS duration may otherwise be estimated from bitrate and reject a
        # correctly edited VBR AAC file. Packet timestamps use the AAC frame grid.
        packet_command = [ffprobe, '-v', 'error', '-select_streams', 'a:0', '-show_packets',
                          '-show_entries', 'packet=pts_time,duration_time', '-of', 'json', str(audio)]
        packet_result = subprocess.run(packet_command, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if packet_result.returncode:
            raise ValidationError(f'Cannot determine raw AAC packet duration: {packet_result.stderr[-1000:]}')
        packets = json.loads(packet_result.stdout).get('packets', [])
        if not packets or any('pts_time' not in p or 'duration_time' not in p for p in packets):
            raise ValidationError('Raw AAC packets lack usable timestamps; remux the confirmed track to M4A first')
        audio_duration = max(float(p['pts_time']) + float(p['duration_time']) for p in packets) - min(float(p['pts_time']) for p in packets)
        audio_duration_method = 'raw-aac-packet-timestamps'
    tolerance = max(0.12, 3 * 1024 / int(audio_streams[0].get('sample_rate', 48000)))
    if not audio_duration or abs(audio_duration - expected_duration) > tolerance:
        raise ValidationError(f'--audio must already match the edited duration ({expected_duration:.6f}s); received {audio_duration:.6f}s')
    source_hash = sha256(source)
    if edl.get('sourceSha256') and edl['sourceSha256'].lower() != source_hash:
        raise ValidationError('Source SHA-256 differs from the EDL')
    evidence = {'edl': str(edl_path), 'source': str(source), 'sourceSha256': source_hash, 'audio': str(audio),
                'audioSha256': sha256(audio), 'sourceMetadata': source_meta, 'audioMetadata': audio_meta,
                'audioDurationSeconds': audio_duration, 'audioDurationMethod': audio_duration_method,
                'fps': edl['fps'], 'outputFrames': edl['outputFrames'], 'playbackRate': edl.get('playbackRate', 1),
                'toneMapHlg': args.tone_map_hlg, 'colorPolicy': color_policy, 'enhanceMild': args.enhance_mild,
                'crf': args.crf, 'preset': args.preset, 'sourceDisplayDimensions': [width, height],
                'allowDownscale': args.allow_downscale, 'variants': []}
    for i, (manifest_path, manifest, output) in enumerate(variants):
        output.parent.mkdir(parents=True, exist_ok=True)
        save_json(run_dir / f'variant_{i:02d}_manifest.json', manifest)
        evidence['variants'].append({'manifest': str(manifest_path), 'manifestSha256': sha256(manifest_path), 'output': str(output)})
    save_json(run_dir / 'inputs.json', evidence)
    command = build_command(args, run_dir, edl, source, audio, variants, ffmpeg)
    save_json(run_dir / 'command.json', command)
    started = time.monotonic()
    print(json.dumps({'event': 'render-start', 'runDir': str(run_dir), 'variants': len(variants), 'outputFrames': edl['outputFrames']}, ensure_ascii=False), flush=True)
    with (run_dir / 'render.log').open('w', encoding='utf-8') as handle:
        completed = subprocess.run(command, stdout=handle, stderr=handle)
    if completed.returncode:
        raise RuntimeError(f'FFmpeg exited {completed.returncode}; see {run_dir / "render.log"}')
    outputs = []
    for _, _, output in variants:
        metadata = probe(ffprobe, output, count_frames=True)
        videos = [s for s in metadata['streams'] if s['codec_type'] == 'video']
        audios = [s for s in metadata['streams'] if s['codec_type'] == 'audio']
        if len(videos) != 1 or len(audios) != 1 or videos[0].get('codec_name') != 'h264' or audios[0].get('codec_name') != 'aac':
            raise ValidationError(f'Rendered stream validation failed: {output}')
        if (videos[0]['width'], videos[0]['height'], int(videos[0].get('nb_read_frames', -1))) != (edl['width'], edl['height'], edl['outputFrames']):
            raise ValidationError(f'Rendered dimensions/frame count differ from EDL: {output}')
        if Fraction(videos[0]['r_frame_rate']) != edl['fps']:
            raise ValidationError(f'Rendered fps differs from EDL: {output}')
        color_check = validate_sdr_color(videos[0], output)
        outputs.append({'path': str(output), 'sha256': sha256(output), 'bytes': output.stat().st_size, 'metadata': metadata,
                        'colorValidation': color_check})
    return {'ok': True, 'scope': 'encode_structure_only', 'editorialAcceptance': 'pending_separate_review',
            'runDir': str(run_dir), 'elapsedSeconds': time.monotonic() - started,
            'videoEncodesPerVariant': 1, 'audioCodec': 'copy', 'outputFrames': edl['outputFrames'], 'outputs': outputs}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--edl', required=True)
    parser.add_argument('--audio', required=True, help='Already-edited AAC file or video containing one confirmed AAC stream')
    parser.add_argument('--variant', nargs=2, action='append', required=True, metavar=('MANIFEST', 'OUTPUT'))
    parser.add_argument('--work-dir', required=True)
    parser.add_argument('--ffmpeg')
    parser.add_argument('--ffprobe', help='Defaults to the ffmpeg directory or PATH; used for AAC/HDR and output validation')
    parser.add_argument('--tone-map-hlg', action='store_true', help='Optional legacy assertion: input must be HLG. HLG is automatically detected and converted when omitted')
    parser.add_argument('--enhance-mild', action='store_true')
    parser.add_argument('--allow-downscale', action='store_true', help='Only for a user-requested lower delivery resolution; default preserves original display dimensions')
    parser.add_argument('--crf', type=int, default=14, choices=range(0, 52), metavar='0..51')
    parser.add_argument('--preset', default='medium', choices=['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow'])
    args = parser.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
    run_dir = Path(args.work_dir).expanduser().resolve() / (datetime.now(timezone.utc).strftime('run-%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:8])
    run_dir.mkdir(parents=True, exist_ok=False)
    save_json(run_dir / 'arguments.json', vars(args))
    try:
        result = execute(args, run_dir)
    except (Exception, KeyboardInterrupt) as error:
        result = {'ok': False, 'runDir': str(run_dir), 'errorType': type(error).__name__, 'error': str(error)}
        save_json(run_dir / 'result.json', result)
        print(json.dumps(result, ensure_ascii=False), file=sys.stderr, flush=True)
        return 1
    save_json(run_dir / 'result.json', result)
    print(json.dumps({'event': 'render-complete', 'runDir': str(run_dir), 'outputs': [o['path'] for o in result['outputs']]}, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
