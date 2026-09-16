"""Local read-only media checks; standard library only, optional imageio ffmpeg discovery.

Protection manifest: {"files":[{"path":"...","sha256":"64 hex characters"}]}.
A files dictionary (such as the project QA baseline) is also accepted. Relative paths
are resolved beside the manifest. PASS covers only the reported technical checks;
visual correctness, spoken semantics and subjective sharpness need separate review.
"""
from pathlib import Path
from fractions import Fraction
import argparse
import datetime
import hashlib
import importlib.util
import json
import math
import re
import shutil
import subprocess
import sys
import uuid


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def default_max_silence():
    policy_path = Path(__file__).resolve().parent.parent / 'references' / 'pause-policy.json'
    policy = json.loads(policy_path.read_text(encoding='utf-8-sig'))
    if policy.get('coordinate') != 'final_output_seconds':
        raise ValueError('pause-policy coordinate must be final_output_seconds')
    value = float(policy['technicalCandidateSeconds'])
    if not math.isfinite(value) or value <= 0:
        raise ValueError('technicalCandidateSeconds must be positive and finite')
    return value


def identity(path):
    before = path.stat()
    value = digest(path)
    after = path.stat()
    return {'path': str(path), 'sha256': value, 'bytes': after.st_size,
            'mtimeNs': after.st_mtime_ns,
            'stableDuringHash': (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)}


def discover(name, explicit, video):
    if explicit:
        candidate = Path(explicit).expanduser()
        resolved = str(candidate.resolve()) if candidate.is_file() else shutil.which(explicit)
        if not resolved:
            raise RuntimeError('Explicit {} was not found: {}'.format(name, explicit))
        return resolved
    on_path = shutil.which(name)
    if on_path:
        return on_path
    if name == 'ffmpeg':
        try:
            import imageio_ffmpeg
            candidate = imageio_ffmpeg.get_ffmpeg_exe()
            if Path(candidate).is_file():
                return candidate
        except ImportError:
            pass
    # Existing project-local binaries only. Never run npx or fetch a package.
    for root in dict.fromkeys([Path.cwd(), video.parent]):
        for relative in [Path('node_modules/.bin') / (name + '.exe'),
                         Path('node_modules/@remotion/compositor-win32-x64-msvc') / (name + '.exe'),
                         Path('node_modules/@remotion/compositor-linux-x64-gnu') / name]:
            candidate = root / relative
            if candidate.is_file():
                return str(candidate.resolve())
    raise RuntimeError('{} was not found locally. Pass --{} / -{}Path; nothing was installed.'.format(name, name, name.capitalize()))


def rate(value):
    try:
        return float(Fraction(value))
    except (ValueError, TypeError, ZeroDivisionError):
        return None


def intervals(log, prefix, final_duration):
    pattern = r'{}_(start|end):\s*(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)'.format(prefix)
    rows, opened = [], None
    for match in re.finditer(pattern, log, re.IGNORECASE):
        kind, timestamp = match.group(1), float(match.group(2))
        if kind == 'start':
            opened = timestamp
        elif opened is not None:
            rows.append({'startSec': opened, 'endSec': timestamp, 'durationSec': max(0, timestamp - opened), 'closedAtEof': False})
            opened = None
    if opened is not None and final_duration is not None:
        rows.append({'startSec': opened, 'endSec': final_duration, 'durationSec': max(0, final_duration - opened), 'closedAtEof': True})
    return rows


def protected_rows(manifest):
    obj = json.loads(manifest.read_text(encoding='utf-8-sig'))
    rows = obj.get('files', obj.get('ProtectedFiles')) if isinstance(obj, dict) else obj
    if isinstance(rows, dict):
        rows = list(rows.values())
    if not isinstance(rows, list) or not rows:
        raise ValueError('Protection manifest must contain a nonempty files list or dictionary.')
    result = []
    for row in rows:
        name, expected = row.get('path', row.get('Path')), row.get('sha256', row.get('SHA256'))
        if not name or not isinstance(expected, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', expected):
            raise ValueError('Each protected file needs path and a 64-character SHA-256.')
        path = Path(name).expanduser()
        path = path.resolve() if path.is_absolute() else (manifest.parent / path).resolve()
        result.append((path, expected.lower()))
    return result


def verify_end_packet_rounding(stream, packets, expected_fps, expected_frames,
                               expected_duration, decoded_frames, decode_complete):
    """Prove CFR packet timing with only the display-last packet rounded.

    Integer media timestamps and Fractions are authoritative. A microsecond is
    allowed for the API's timestamp quantization, not for frame-rate drift.
    This proves timing only; it does not prove distinct image content per frame.
    """
    proof = {'passed': False, 'issues': [], 'packetCount': len(packets),
             'expectedFrames': expected_frames, 'decodedFrames': decoded_frames,
             'method': 'all video packet PTS/DTS and durations; integer timestamps/Fraction arithmetic',
             'scope': 'timing only; does not certify unique pictures or subjective motion'}
    issues = proof['issues']
    try:
        fps = Fraction(str(expected_fps))
        total_frames = int(expected_frames)
        period = 1 / fps
        declared_duration = Fraction(str(expected_duration))
        nominal_duration = total_frames * period
        tick = Fraction(stream['time_base'])
        tolerance = max(tick, Fraction(1, 1000000))
        if fps <= 0 or total_frames < 2 or tick <= 0 or tolerance >= period / 100:
            raise ValueError('Unsupported frame rate, packet count, or timestamp precision')
        proof.update(timestampToleranceSeconds=float(tolerance), timeBase=str(tick),
                     nominalDurationSeconds=float(nominal_duration), expectedFps=str(fps))
        if abs(declared_duration - nominal_duration) > Fraction(1, 1000000):
            issues.append('declared_frames_fps_duration_inconsistent')
        if not decode_complete or decoded_frames != total_frames:
            issues.append('complete_decode_with_expected_frame_count_required')
        if len(packets) != total_frames:
            issues.append('packet_count_mismatch')
        if Fraction(stream['r_frame_rate']) != fps:
            issues.append('nominal_frame_rate_mismatch')
        metadata_frames = stream.get('nb_frames')
        if metadata_frames is not None and int(metadata_frames) != total_frames:
            issues.append('metadata_frame_count_mismatch')

        def timestamp(packet, key):
            value = packet[key]
            if isinstance(value, bool) or not re.fullmatch(r'-?\d+', str(value)):
                raise ValueError('Missing or noninteger packet ' + key)
            return int(value)

        rows = [(timestamp(p, 'pts'), timestamp(p, 'dts'), timestamp(p, 'duration')) for p in packets]
        if not rows:
            raise ValueError('No video packets')
        if any(p[2] <= 0 for p in rows):
            issues.append('nonpositive_packet_duration')
        decode_times = [p[1] for p in rows]
        if any(b <= a for a, b in zip(decode_times, decode_times[1:])):
            issues.append('dts_not_strictly_increasing')
        max_dts_error = max(abs((dts - decode_times[0]) * tick - index * period)
                            for index, dts in enumerate(decode_times))
        if max_dts_error > tolerance:
            issues.append('internal_dts_not_cfr_grid')
        display = sorted(rows, key=lambda row: row[0])
        pts = [p[0] for p in display]
        if any(b <= a for a, b in zip(pts, pts[1:])):
            issues.append('pts_not_unique')
        start = int(stream['start_pts'])
        if start != pts[0] or abs(start * tick) > tolerance:
            issues.append('presentation_start_not_zero')
        max_pts_error = max(abs((point - start) * tick - index * period)
                            for index, point in enumerate(pts))
        if max_pts_error > tolerance:
            issues.append('internal_pts_not_cfr_grid')
        bad_durations = [index for index, (packet, next_packet) in enumerate(zip(display, display[1:]))
                         if abs(packet[2] - (next_packet[0] - packet[0])) > 1]
        if bad_durations:
            issues.append('nonfinal_packet_duration_mismatch')
        duration_ts = int(stream['duration_ts'])
        actual_duration = duration_ts * tick
        last_pts, _, last_ticks = display[-1]
        last_duration = last_ticks * tick
        packet_span = (last_pts + last_ticks - start) * tick
        if abs(actual_duration - packet_span) > tick:
            issues.append('stream_duration_not_explained_by_packets')
        if not 0 < last_duration < 2 * period:
            issues.append('last_packet_duration_out_of_bounds')
        duration_delta = actual_duration - nominal_duration
        if abs(duration_delta) >= period:
            issues.append('total_rounding_reaches_one_frame')
        if abs(duration_delta - (last_duration - period)) > tolerance + tick:
            issues.append('duration_delta_not_only_last_packet')
        actual_average = Fraction(stream['avg_frame_rate'])
        if actual_duration <= 0 or abs(actual_average - total_frames / actual_duration) > Fraction(1, 1000000):
            issues.append('average_rate_not_explained_by_packet_span')
        proof.update(maxPtsGridErrorSeconds=float(max_pts_error),
                     maxDtsGridErrorSeconds=float(max_dts_error),
                     nonfinalDurationMismatchIndices=bad_durations[:20],
                     videoDurationSeconds=float(actual_duration), durationDeltaSeconds=float(duration_delta),
                     lastPacketDurationSeconds=float(last_duration),
                     lastPacketDeltaSeconds=float(last_duration - period),
                     lastDisplayPts=last_pts, lastDisplayDurationTicks=last_ticks,
                     averageFrameRate=str(actual_average))
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        issues.append('insufficient_or_invalid_packet_evidence:' + str(exc))
    proof['issues'] = sorted(set(issues))
    proof['passed'] = not proof['issues']
    return proof


def main(args):
    result = {'ok': False, 'status': 'FAIL', 'verificationComplete': False,
              'technicalVerificationComplete': False, 'verificationScope': 'technical_only',
              'editorialAcceptance': 'not_assessed',
              'recordedAtUtc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'videoPath': str(Path(args.video).expanduser().resolve()), 'durationSec': None,
              'maxDurationSec': args.max_duration, 'expectedFrames': args.frames,
              'expectedDurationSec': args.duration, 'decodedFrames': None,
              'videoStreams': 0, 'audioStreams': 0, 'dataStreams': 0,
              'streams': [], 'blackFrames': [], 'silences': [], 'checks': {}, 'errors': [],
              'scope': 'Technical checks only; bitrate is not a clarity score. No claim of human listening or visual review.'}
    report, evidence, protected = None, None, []
    # Validate every input/output relationship before creating directories or logs.
    # Reports are new files only: this also protects unrelated existing media,
    # symlink aliases and hard-link aliases without relying on file extensions.
    try:
        manifest = Path(args.protection_manifest).expanduser().resolve() if args.protection_manifest else None
        protected = protected_rows(manifest) if manifest else []
        inputs = {Path(result['videoPath'])}
        if args.reference_audio:
            inputs.add(Path(args.reference_audio).expanduser().resolve())
        if manifest:
            inputs.add(manifest)
        inputs.update(path for path, _ in protected)
        for executable in (args.ffmpeg, args.ffprobe):
            if executable and Path(executable).expanduser().is_file():
                inputs.add(Path(executable).expanduser().resolve())
        if args.report:
            requested_report = Path(args.report).expanduser()
            report = requested_report.resolve()
            if report in inputs:
                raise ValueError('Report path collides with an input or protected file; nothing was written.')
            if requested_report.exists() or requested_report.is_symlink() or report.exists():
                raise ValueError('Report must be a new file; refusing to overwrite an existing path.')
            evidence = report.parent / (report.stem + '_logs-' + uuid.uuid4().hex)
    except Exception as exc:
        result['checks']['report_preflight'] = {'status': 'FAIL', 'detail': str(exc)}
        result['errors'].append('report_preflight: ' + str(exc))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    allow_rounding = bool(getattr(args, 'allow_end_packet_rounding', False))
    deferred_timing = {}

    def check(name, passed=None, detail=None, state=None):
        status = state or ('PASS' if passed else 'FAIL')
        result['checks'][name] = {'status': status, 'detail': detail}
        if status == 'FAIL':
            result['errors'].append('{}: {}'.format(name, detail))

    def run(name, command):
        process = subprocess.run(command, capture_output=True, text=True, encoding='utf8', errors='replace')
        if evidence:
            (evidence / (name + '.stdout.log')).write_text(process.stdout, encoding='utf8')
            (evidence / (name + '.stderr.log')).write_text(process.stderr, encoding='utf8')
            (evidence / (name + '.command.json')).write_text(json.dumps(command, ensure_ascii=False, indent=2), encoding='utf8')
        return process

    try:
        if args.width <= 0 or args.height <= 0 or args.fps <= 0 or args.max_silence <= 0 or args.duration_tolerance < 0:
            raise ValueError('Dimensions, frame rate and silence duration must be positive; tolerance must not be negative.')
        if (args.frames is not None and args.frames <= 0) or (args.duration is not None and args.duration <= 0) or (args.max_duration is not None and args.max_duration <= 0):
            raise ValueError('Expected frames and explicitly supplied durations must be positive.')
        if allow_rounding and (not getattr(args, 'fps_explicit', False) or args.frames is None
                               or args.duration is None or args.skip_decode):
            raise ValueError('--allow-end-packet-rounding requires explicit --fps, --frames, --duration and complete decoding (no --skip-decode).')
        video_path = Path(result['videoPath'])
        if not video_path.is_file():
            raise FileNotFoundError(video_path)
        initial = identity(video_path)
        if evidence:
            evidence.mkdir(parents=True, exist_ok=False)
            result['evidenceDirectory'] = str(evidence)
        ffmpeg = discover('ffmpeg', args.ffmpeg, video_path)
        ffprobe = discover('ffprobe', args.ffprobe, video_path)
        result['tools'] = {}
        for name, exe in [('ffmpeg', ffmpeg), ('ffprobe', ffprobe)]:
            version = run(name + '_version', [exe, '-version'])
            if version.returncode:
                raise RuntimeError('{} could not run: {}'.format(name, version.stderr[-1000:]))
            result['tools'][name] = {'path': exe, 'version': version.stdout.splitlines()[0] if version.stdout else ''}
        protection_before = []
        for path, expected in protected:
            current = identity(path)
            protection_before.append(current)
            check('protected_before:' + str(path), current['sha256'] == expected and current['stableDuringHash'], current)
        if not protected:
            check('protected_files', state='NOT_APPLICABLE', detail='No protection manifest supplied; source integrity is not certified.')
        probe_process = run('probe', [ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(video_path)])
        if probe_process.returncode:
            raise RuntimeError('ffprobe failed: ' + probe_process.stderr[-2000:])
        probe = json.loads(probe_process.stdout)
        streams = probe.get('streams', [])
        videos = [s for s in streams if s.get('codec_type') == 'video']
        audios = [s for s in streams if s.get('codec_type') == 'audio']
        result.update(streams=streams, videoStreams=len(videos), audioStreams=len(audios),
                      dataStreams=sum(s.get('codec_type') == 'data' for s in streams))
        duration = float(probe['format']['duration'])
        result['durationSec'] = duration
        check('one_video_one_audio', len(streams) == 2 and len(videos) == 1 and len(audios) == 1,
              {'total': len(streams), 'video': len(videos), 'audio': len(audios), 'other': len(streams) - len(videos) - len(audios)})
        if args.max_duration is not None:
            check('maximum_duration', duration <= args.max_duration, {'actual': duration, 'maximum': args.max_duration})
        else:
            check('maximum_duration', state='NOT_APPLICABLE', detail='No maximum duration was requested.')
        if len(videos) == 1:
            v = videos[0]
            video_duration = float(v.get('duration', duration))
            result.update(videoDurationSec=video_duration, nominalFrameRate=v.get('r_frame_rate'), averageFrameRate=v.get('avg_frame_rate'))
            check('video_codec', v.get('codec_name') == 'h264', v.get('codec_name'))
            rotation = next((float(s['rotation']) for s in v.get('side_data_list', []) if 'rotation' in s),
                            float(v.get('tags', {}).get('rotate', 0)))
            check('upright_pixels_no_rotation', math.isfinite(rotation) and abs(rotation) < .001,
                  {'rotationDegrees': rotation, 'expected': 0, 'visualDirectionStillRequiresReview': True})
            check('pixel_format', v.get('pix_fmt') == 'yuv420p', v.get('pix_fmt'))
            check('dimensions', (v.get('width'), v.get('height')) == (args.width, args.height),
                  {'actual': [v.get('width'), v.get('height')], 'expected': [args.width, args.height]})
            for field in ['r_frame_rate', 'avg_frame_rate']:
                value = rate(v.get(field))
                passed = value is not None and abs(value - args.fps) < .001
                detail = {'actual': v.get(field), 'expected': args.fps}
                if allow_rounding and field == 'avg_frame_rate':
                    deferred_timing[field] = (passed, detail)
                else:
                    check(field, passed, detail)
            if args.frames is not None:
                count = int(v['nb_frames']) if str(v.get('nb_frames', '')).isdigit() else None
                if count is None:
                    check('metadata_frames', state='NOT_APPLICABLE', detail='No stream frame-count metadata; actual decoding remains required.')
                else:
                    check('metadata_frames', count == args.frames, {'actual': count, 'expected': args.frames})
            if args.duration is not None:
                passed = abs(video_duration - args.duration) <= args.duration_tolerance
                detail = {'actual': video_duration, 'expected': args.duration, 'tolerance': args.duration_tolerance}
                if allow_rounding:
                    deferred_timing['expected_duration'] = (passed, detail)
                else:
                    check('expected_duration', passed, detail)
            if args.expect_bt709:
                colors = {k: v.get(k) for k in ['color_primaries', 'color_transfer', 'color_space']}
                # Import only local probe/gate functions. Importing this module
                # neither resolves credentials nor loads/calls the Kaipai SDK.
                # Do not use probe_media(video=True): its frame-count fallback
                # can decode the whole video, violating --skip-decode here.
                try:
                    gate_path = Path(__file__).resolve().parent / 'kaipai_enhance.py'
                    spec = importlib.util.spec_from_file_location('local_sdr_color_gate', gate_path)
                    gate = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(gate)
                    color_probe = gate.probe_media(video_path, ffprobe, video=False)
                    color_probe['containerColr'] = gate.read_video_colr(video_path)
                    sample_duration = color_probe.get('videoDurationSeconds')
                    positions = [0.0]
                    if sample_duration and sample_duration > 0:
                        positions += [sample_duration / 2, max(0, sample_duration - min(.5, sample_duration / 4))]
                    for index, sec in enumerate(positions):
                        sampled = run('bt709_frame_' + str(index), [
                            ffprobe, '-v', 'error', '-select_streams', 'v:0',
                            '-read_intervals', '{:.6f}%+0.25'.format(sec),
                            '-show_frames', '-show_entries',
                            'frame=color_range,color_space,color_primaries,color_transfer:frame_side_data=side_data_type',
                            '-of', 'json', str(video_path)])
                        if sampled.returncode:
                            raise RuntimeError('Short color-frame probe failed: ' + sampled.stderr[-1000:])
                        sample_frames = json.loads(sampled.stdout).get('frames', [])
                        record = {'requestedTimeSeconds': sec, 'decodedFrameFound': bool(sample_frames)}
                        if sample_frames:
                            record.update({k: sample_frames[0].get(k) for k in gate.SDR})
                            record['sideDataTypes'] = [d.get('side_data_type', '')
                                                      for d in sample_frames[0].get('side_data_list', [])]
                        color_probe['sampleFrames'].append(record)
                    color_issues = gate.sdr_issues(color_probe)
                    result['colorGate'] = color_probe
                    if evidence:
                        (evidence / 'bt709_color_gate.json').write_text(
                            json.dumps({'probe': color_probe, 'issues': color_issues}, ensure_ascii=False, indent=2), encoding='utf8')
                    check('bt709', not color_issues, {'streamColors': colors, 'issues': color_issues,
                          'scope': 'stream + MP4 video colr + first/middle/tail decoded color records; shared sdr_issues gate'})
                except Exception as exc:
                    check('bt709', False, {'streamColors': colors,
                          'error': '{}: {}'.format(type(exc).__name__, exc),
                          'scope': 'Color gate could not complete; stream tags alone cannot pass.'})
                check('limited_color_range', v.get('color_range') == 'tv', v.get('color_range'))
            else:
                check('bt709', state='NOT_APPLICABLE', detail='No BT.709 expectation supplied; stream tags are reported.')
        if len(audios) == 1:
            check('audio_codec', audios[0].get('codec_name') == 'aac', audios[0].get('codec_name'))
        if args.skip_decode:
            check('full_decode', state='SKIPPED', detail='Requested SkipDecode; actual frame count and black frames were not checked.')
            check('black_frames', state='SKIPPED', detail='Requires full decode.')
        elif len(videos) == len(audios) == 1:
            command = [ffmpeg, '-hide_banner', '-loglevel', 'info', '-xerror', '-err_detect', 'explode', '-nostdin', '-threads', '2', '-i', str(video_path),
                       '-map', '0:v:0', '-map', '0:a:0', '-vf', 'blackdetect=d=0.02:pix_th=0.10:pic_th=0.98',
                       '-fps_mode', 'passthrough', '-progress', 'pipe:1', '-nostats', '-f', 'null', '-']
            decoded = run('full_decode_black', command)
            counts = re.findall(r'^frame=(\d+)', decoded.stdout, re.MULTILINE)
            result['decodedFrames'] = int(counts[-1]) if counts else None
            check('full_decode', decoded.returncode == 0 and result['decodedFrames'] is not None,
                  {'exitCode': decoded.returncode, 'decodedFrames': result['decodedFrames'], 'error': decoded.stderr[-2000:] if decoded.returncode else None})
            if args.frames is not None:
                check('actual_frames', result['decodedFrames'] == args.frames, {'actual': result['decodedFrames'], 'expected': args.frames})
            result['blackFrames'] = intervals(decoded.stderr, 'black', duration)
            check('black_frames', not result['blackFrames'], {'intervals': result['blackFrames'], 'pictureFraction': .98, 'pixelThreshold': .10, 'minimumSeconds': .02})
        else:
            check('full_decode', state='SKIPPED', detail='Invalid stream count; mapping is unsafe.')
            check('black_frames', state='SKIPPED', detail='Invalid stream count.')
        if allow_rounding:
            proof = {'passed': False, 'issues': ['complete_decode_with_expected_frame_count_required']}
            if (len(videos) == 1 and result['checks']['full_decode']['status'] == 'PASS'
                    and result['decodedFrames'] == args.frames):
                packet_process = run('end_packet_rounding_packets', [
                    ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_packets',
                    '-show_entries', 'packet=pts,dts,duration', '-of', 'json', str(video_path)])
                if packet_process.returncode or packet_process.stderr.strip():
                    proof = {'passed': False, 'issues': ['all_packet_probe_failed']}
                else:
                    proof = verify_end_packet_rounding(videos[0], json.loads(packet_process.stdout).get('packets', []),
                        args.fps, args.frames, args.duration, result['decodedFrames'], True)
            result['endPacketRounding'] = proof
            check('end_packet_rounding_evidence', proof['passed'], proof)
            for name, (strict_passed, detail) in deferred_timing.items():
                detail.update(strictCheckPassed=strict_passed,
                              endPacketRoundingAccepted=proof['passed'] and not strict_passed,
                              evidenceCheck='end_packet_rounding_evidence')
                check(name, strict_passed or proof['passed'], detail)
        if args.skip_silence:
            check('silence', state='SKIPPED', detail='Requested SkipSilenceCheck.')
        elif len(audios) == 1:
            silence = run('silence', [ffmpeg, '-hide_banner', '-loglevel', 'info', '-xerror', '-nostdin', '-threads', '2', '-i', str(video_path),
                           '-map', '0:a:0', '-vn', '-af', 'silencedetect=noise={}dB:d={}'.format(args.silence_db, args.max_silence), '-f', 'null', '-'])
            result['silences'] = intervals(silence.stderr, 'silence', duration)
            check('silence_detector', silence.returncode == 0, {'exitCode': silence.returncode, 'error': silence.stderr[-2000:] if silence.returncode else None})
            check('silence', args.allow_long_silence or not result['silences'],
                  {'intervals': result['silences'], 'thresholdDb': args.silence_db, 'minimumSeconds': args.max_silence, 'allowedByCaller': args.allow_long_silence})
        else:
            check('silence', state='SKIPPED', detail='Invalid audio stream count.')
        if args.reference_audio and len(audios) == 1:
            reference = Path(args.reference_audio).expanduser().resolve()
            hashes = {}
            for label, path in [('output', video_path), ('reference', reference)]:
                audio = run('pcm_' + label, [ffmpeg, '-v', 'error', '-xerror', '-nostdin', '-threads', '2', '-i', str(path),
                            '-map', '0:a:0', '-vn', '-c:a', 'pcm_s32le', '-f', 'hash', '-hash', 'sha256', 'pipe:1'])
                if audio.returncode or not re.fullmatch(r'SHA256=[a-fA-F0-9]{64}', audio.stdout.strip()):
                    raise RuntimeError('PCM hashing failed for {}: {}'.format(label, audio.stderr[-1500:]))
                hashes[label] = audio.stdout.strip()
            check('reference_audio_pcm', hashes['output'] == hashes['reference'],
                  {'reference': str(reference), 'hashes': hashes, 'method': 'decoded PCM s32le, no forced resampling or remix', 'notCertified': 'Encoded AAC payload identity and mux timestamps need stricter project checks.'})
        else:
            check('reference_audio_pcm', state='NOT_APPLICABLE', detail='No reference supplied, or invalid output audio streams.')
        for path, expected in protected:
            current = identity(path)
            check('protected_after:' + str(path), current['sha256'] == expected and current['stableDuringHash'], current)
        final = identity(video_path)
        result['file'] = final
        check('output_stable', initial == final and initial['stableDuringHash'] and final['stableDuringHash'],
              'Output content, size and modification time stayed unchanged throughout validation.')
    except Exception as exc:
        check('validator_execution', False, '{}: {}'.format(type(exc).__name__, exc))
    skipped = any(c['status'] == 'SKIPPED' for c in result['checks'].values())
    result['status'] = 'FAIL' if result['errors'] else ('PARTIAL' if skipped else 'PASS')
    result['verificationComplete'] = result['status'] == 'PASS'
    result['technicalVerificationComplete'] = result['status'] == 'PASS'
    result['ok'] = result['status'] == 'PASS'
    if report:
        try:
            report.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation closes the gap between preflight and writing.
            with report.open('x', encoding='utf8') as handle:
                handle.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        except OSError as exc:
            check('report_write', False, '{}: {}'.format(type(exc).__name__, exc))
            result.update(ok=False, status='FAIL', verificationComplete=False,
                          technicalVerificationComplete=False)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result['errors'] else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', required=True)
    parser.add_argument('--width', type=int, default=1080)
    parser.add_argument('--height', type=int, default=1920)
    parser.add_argument('--fps', type=float, default=30)
    parser.add_argument('--max-duration', type=float)
    parser.add_argument('--max-silence', type=float,
                        help='Technical silence candidate duration in final-output seconds; default from pause-policy.json, not a listening verdict.')
    parser.add_argument('--silence-db', type=float, default=-32)
    parser.add_argument('--allow-long-silence', action='store_true')
    parser.add_argument('--skip-decode', action='store_true')
    parser.add_argument('--skip-silence', action='store_true')
    parser.add_argument('--ffmpeg')
    parser.add_argument('--ffprobe')
    parser.add_argument('--frames', type=int)
    parser.add_argument('--duration', type=float)
    parser.add_argument('--duration-tolerance', type=float, default=.005)
    parser.add_argument('--allow-end-packet-rounding', action='store_true',
                        help='Opt-in only: verify all packet timing and complete decoded frame count before accepting an API display-last packet duration difference smaller than one frame; requires explicit --fps --frames --duration.')
    parser.add_argument('--expect-bt709', action='store_true')
    parser.add_argument('--reference-audio')
    parser.add_argument('--protection-manifest')
    parser.add_argument('--report')
    options = parser.parse_args()
    if options.max_silence is None:
        try:
            options.max_silence = default_max_silence()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            parser.error(f'Cannot load shared pause policy: {exc}')
    options.fps_explicit = any(arg == '--fps' or arg.startswith('--fps=') for arg in sys.argv[1:])
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf8')
    sys.exit(main(options))
