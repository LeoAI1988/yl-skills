#!/usr/bin/env python3
"""Kaipai raw enhancement with an SDR input gate and resumable checkpoints.

No local beauty/color filters are applied. --brighten is retired and rejected.
Exit 0: raw downloaded, technical checks passed, visual review still pending.
Exit 1: rejected/failed; 2: pending or recoverable; 3: raw needs review.
--task-id never submits a new task. Keep the checkpoint if anything fails.
"""
import argparse
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

VIDEO_TASKS = {"hdvideoallinone", "videoscreenclear"}
DEFAULT_TIMEOUT = {"image_restoration": 300, "eraser_watermark": 300,
                   "videoscreenclear": 3600, "hdvideoallinone": 3600}
SDR = {"color_range": "tv", "color_space": "bt709",
       "color_primaries": "bt709", "color_transfer": "bt709"}
STREAM_FIELDS = ("index", "codec_type", "codec_name", "width", "height", "pix_fmt",
                 *SDR, "r_frame_rate", "avg_frame_rate", "duration", "nb_frames",
                 "start_time", "sample_rate", "channels", "sample_aspect_ratio",
                 "display_aspect_ratio")


class GateError(Exception):
    """Only locally composed messages, never raw service responses."""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for data in iter(lambda: f.read(1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()


def save_json(path, data, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if exclusive:
        # Prevent two new invocations from consuming for the same checkpoint.
        with path.open("x", encoding="utf-8", newline="\n") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        return
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with tmp.open("x", encoding="utf-8", newline="\n") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def save_checkpoint(path, cp):
    cp["updatedAt"] = now()
    save_json(path, cp)


def load_env_file(path):
    data = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip().strip("\"'")
    return data


def resolve_credentials(cli_env):
    ak, sk = os.environ.get("MT_AK"), os.environ.get("MT_SK")
    if ak and sk:
        return ak, sk
    candidates = [Path(cli_env).expanduser()] if cli_env else []
    for path in candidates:
        if path.is_file():
            d = load_env_file(path)
            if d.get("MT_AK") and d.get("MT_SK"):
                return d["MT_AK"], d["MT_SK"]
    raise GateError("缺少开拍凭据，请配置 MT_AK / MT_SK 或 --env-file。")


def make_client(env_file, sdk_dir=None):
    ak, sk = resolve_credentials(env_file)
    location = sdk_dir or os.environ.get("KAIPAI_SDK_DIR")
    if not location:
        raise GateError("请通过 --sdk-dir 或 KAIPAI_SDK_DIR 指定自行取得的官方 SDK 目录。")
    root = Path(location).expanduser().resolve()
    entry = root / "__init__.py"
    if not entry.is_file() or not (root / "core" / "client.py").is_file():
        raise GateError("SDK 目录结构无效：须包含 __init__.py 和 core/client.py。")
    existing = sys.modules.get("sdk")
    if existing is not None and Path(getattr(existing, "__file__", "")).resolve() != entry:
        raise GateError("当前进程存在不同来源的 sdk 模块，请使用独立进程。")
    if existing is None:
        spec = importlib.util.spec_from_file_location(
            "sdk", entry, submodule_search_locations=[str(root)])
        mod = importlib.util.module_from_spec(spec)
        sys.modules["sdk"] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception:
            for name in list(sys.modules):
                if name == "sdk" or name.startswith("sdk."):
                    del sys.modules[name]
            raise GateError("SDK 导入失败，请检查版本及依赖。") from None
    from sdk import SkillClient
    return SkillClient(ak=ak, sk=sk)


def discover_ffprobe(explicit=None):
    if explicit:
        path = shutil.which(explicit) or (str(Path(explicit).resolve())
                                         if Path(explicit).is_file() else None)
        if not path:
            raise GateError("--ffprobe 指向的程序不存在。")
        return path
    for path in (os.environ.get("FFPROBE"), shutil.which("ffprobe")):
        if path and Path(path).is_file():
            return str(path)
    raise GateError("未找到 ffprobe；请用 --ffprobe 指定，不能跳过色彩检查。")


def run_probe(ffprobe, args):
    result = subprocess.run([ffprobe, "-v", "error", *args], capture_output=True,
                            timeout=180, encoding="utf-8", errors="replace")
    if result.returncode or result.stderr.strip():
        raise GateError("ffprobe 检查失败，文件可能不完整或无法解码。")
    try:
        return json.loads(result.stdout)
    except (ValueError, TypeError):
        raise GateError("ffprobe 未返回有效 JSON。") from None


def positive_float(value):
    try:
        n = float(value)
        return n if math.isfinite(n) and n > 0 else None
    except (ValueError, TypeError):
        return None


def fps_value(value):
    try:
        n, d = str(value).split("/")
        return positive_float(float(n) / float(d))
    except (ValueError, ZeroDivisionError):
        return None


def integer_count(value):
    try:
        n = int(value)
        return n if n > 0 else None
    except (ValueError, TypeError):
        return None


def rotation_value(value):
    try:
        angle = float(value)
        return angle % 360 if math.isfinite(angle) else None
    except (ValueError, TypeError):
        return None


def display_geometry(stream):
    """Compute display size from coded dimensions, SAR and rotation metadata."""
    width, height = positive_float(stream.get("width")), positive_float(stream.get("height"))
    sar = fps_value(str(stream.get("sample_aspect_ratio", "")).replace(":", "/"))
    rotation = stream.get("rotationDegrees")
    if not width or not height or not sar or rotation is None:
        return None
    if min(abs(rotation - x) for x in (0, 90, 180, 270, 360)) > 1e-6:
        return None
    width *= sar
    if abs(rotation - 90) < 1e-6 or abs(rotation - 270) < 1e-6:
        width, height = height, width
    return {"displayWidth": width, "displayHeight": height,
            "sampleAspectRatio": sar, "rotationDegrees": rotation}


def read_video_colr(path):
    """Parse only ISO BMFF video sample entries; never load mdat into memory."""
    with Path(path).open("rb") as f:
        length = os.fstat(f.fileno()).st_size

        def boxes(start, end):
            offset = start
            while offset + 8 <= end:
                f.seek(offset)
                size, kind = struct.unpack(">I4s", f.read(8))
                header = 8
                if size == 1:
                    size = struct.unpack(">Q", f.read(8))[0]
                    header = 16
                elif size == 0:
                    size = end - offset
                if size < header or offset + size > end:
                    raise GateError("MP4 box 边界无效。")
                yield kind, offset + header, offset + size
                offset += size

        def child(parent, kind):
            return [b for b in boxes(parent[1], parent[2]) if b[0] == kind]

        found = []
        for moov in boxes(0, length):
            if moov[0] != b"moov":
                continue
            for track_index, trak in enumerate(child(moov, b"trak")):
                for mdia in child(trak, b"mdia"):
                    handlers = child(mdia, b"hdlr")
                    if not handlers:
                        continue
                    f.seek(handlers[0][1] + 8)
                    if f.read(4) != b"vide":
                        continue
                    for minf in child(mdia, b"minf"):
                        for stbl in child(minf, b"stbl"):
                            for stsd in child(stbl, b"stsd"):
                                for entry in boxes(stsd[1] + 8, stsd[2]):
                                    for box in boxes(entry[1] + 78, entry[2]):
                                        if box[0] != b"colr":
                                            continue
                                        f.seek(box[1])
                                        data = f.read(min(11, box[2] - box[1]))
                                        item = {"trackIndex": track_index,
                                                "sampleEntry": entry[0].decode("ascii", "replace"),
                                                "type": data[:4].decode("ascii", "replace")}
                                        if data[:4] in (b"nclx", b"nclc") and len(data) >= 10:
                                            p, t, m = struct.unpack(">HHH", data[4:10])
                                            item.update(primaries=p, transfer=t, matrix=m)
                                            item["fullRange"] = bool(data[10] & 128) if len(data) >= 11 else None
                                        found.append(item)
        return found


def probe_media(path, ffprobe, video=True):
    raw = run_probe(ffprobe, ["-show_streams", "-show_format", "-of", "json", str(path)])
    streams = []
    for stream in raw.get("streams", []):
        item = {k: stream[k] for k in STREAM_FIELDS if k in stream}
        item["sideDataTypes"] = [d.get("side_data_type", "")
                                for d in stream.get("side_data_list", [])]
        if stream.get("codec_type") == "video":
            rotations = [rotation_value(d["rotation"]) for d in stream.get("side_data_list", [])
                         if "rotation" in d]
            if "rotate" in stream.get("tags", {}):
                rotations.append(rotation_value(stream["tags"]["rotate"]))
            item["rotationDegrees"] = (rotations[0] if rotations and len(set(rotations)) == 1
                                       else None if rotations else 0.0)
            item["frameCount"] = integer_count(stream.get("nb_frames"))
            item["frameCountMethod"] = "container_nb_frames" if item["frameCount"] else None
        streams.append(item)
    videos = [s for s in streams if s.get("codec_type") == "video"]
    duration = positive_float(videos[0].get("duration")) if videos else None
    duration = duration or positive_float(raw.get("format", {}).get("duration"))
    report = {"probeSchemaVersion": 2, "streams": streams, "videoDurationSeconds": duration,
              "formatName": raw.get("format", {}).get("format_name"), "sampleFrames": []}
    if video and videos:
        if videos[0].get("frameCount") is None:
            counted = run_probe(ffprobe, ["-select_streams", "v:0", "-count_frames",
                                "-show_entries", "stream=nb_read_frames", "-of", "json", str(path)])
            counts = counted.get("streams", [])
            videos[0]["frameCount"] = integer_count(counts[0].get("nb_read_frames")) if counts else None
            videos[0]["frameCountMethod"] = "decoded_nb_read_frames"
        positions = [0.0]
        if duration and duration > 1:
            positions += [duration / 2, max(0, duration - 0.5)]
        for sec in positions:
            sample = run_probe(ffprobe, [
                "-select_streams", "v:0", "-read_intervals", f"{sec:.6f}%+0.25",
                "-show_frames", "-show_entries",
                "frame=color_range,color_space,color_primaries,color_transfer:frame_side_data=side_data_type",
                "-of", "json", str(path)])
            frames = sample.get("frames", [])
            item = {"requestedTimeSeconds": sec, "decodedFrameFound": bool(frames)}
            if frames:
                item.update({k: frames[0].get(k) for k in SDR})
                item["sideDataTypes"] = [d.get("side_data_type", "")
                                        for d in frames[0].get("side_data_list", [])]
            report["sampleFrames"].append(item)
        try:
            report["containerColr"] = read_video_colr(path)
        except (GateError, OSError, struct.error):
            report["containerColr"] = []
            report["containerColrError"] = "invalid_or_unsupported_bmff"
    return report


def sdr_issues(probe):
    issues = []
    videos = [s for s in probe.get("streams", []) if s.get("codec_type") == "video"]
    if len(videos) != 1:
        issues.append("expected_one_video_stream")
    for index, sample in enumerate(videos + probe.get("sampleFrames", [])):
        if any(sample.get(k) != v for k, v in SDR.items()):
            issues.append(f"non_sdr709_color_record_{index}")
        if any(any(w in name.lower() for w in ("dovi", "dolby", "mastering", "content light"))
               for name in sample.get("sideDataTypes", [])):
            issues.append(f"hdr_side_data_record_{index}")
    if not probe.get("sampleFrames") or not all(s.get("decodedFrameFound")
                                               for s in probe["sampleFrames"]):
        issues.append("decoded_color_unverified")
    colrs = probe.get("containerColr", [])
    if not colrs:
        issues.append("container_colr_missing_or_unreadable")
    for c in colrs:
        if (c.get("type") != "nclx" or c.get("primaries") != 1 or c.get("transfer") != 1
                or c.get("matrix") != 1 or c.get("fullRange") is not False):
            issues.append("container_colr_not_limited_bt709")
    if not probe.get("videoDurationSeconds"):
        issues.append("video_duration_unknown")
    return sorted(set(issues))


def validate_params(text, task):
    try:
        params = json.loads(text) if text else {}
    except ValueError:
        raise GateError("--params 必须为合法 JSON 对象。") from None
    if not isinstance(params, dict):
        raise GateError("--params 必须为 JSON 对象。")
    if task == "hdvideoallinone" and params:
        raise GateError("当前核验的 hdvideoallinone 预设 params={}，没有公开磨皮强度选项；拒绝猜测参数。")

    def check(value):
        if isinstance(value, dict):
            for k, v in value.items():
                if re.search(r"(?i)(secret|token|authorization|password|credential|^ak$|^sk$|api.?key)", k):
                    raise GateError("--params 不得包含凭据字段。")
                check(v)
        elif isinstance(value, list):
            for v in value:
                check(v)
        elif isinstance(value, str) and re.search(r"https?://", value, re.I):
            raise GateError("--params 不得包含签名 URL；媒体请用 --input。")
    check(params)
    return params


def effective_preset(task, overrides):
    """Verify the fetched preset before SDK execute can upload/consume anything."""
    from sdk.core.config import INVOKE
    from sdk.core.api import _deep_merge_params
    preset = copy.deepcopy(INVOKE.get(task))
    if not isinstance(preset, dict) or not isinstance(preset.get("task"), str):
        raise GateError("服务端未提供有效任务预设，未提交。")
    base = preset.get("params", {})
    if not isinstance(base, dict):
        raise GateError("服务端任务参数不是有效对象，未提交。")
    merged = _deep_merge_params(base, overrides)
    # Also applies the no-secrets/no-URLs rule before persisting server fields.
    validate_params(json.dumps(merged), task)
    endpoint = preset["task"]
    task_type = preset.get("task_type") or "mtlab"
    if (not re.fullmatch(r"/[A-Za-z0-9_/-]{1,160}", endpoint)
            or not isinstance(task_type, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", task_type)):
        raise GateError("服务端任务类型或路径无法安全核验，未提交。")
    if task == "hdvideoallinone" and (endpoint != "/v1/hdvideoallinone_async" or task_type != "mtlab"):
        raise GateError("服务端 hdvideoallinone 预设已改变；需先重新核验接口，未提交。")
    snapshot = {"taskName": task, "task": endpoint, "taskType": task_type, "params": merged}
    snapshot["sha256"] = hashlib.sha256(json.dumps(snapshot, sort_keys=True,
                                                   separators=(",", ":")).encode()).hexdigest()
    return snapshot


def task_id_value(value):
    if value is None:
        return None
    value = str(value).strip()
    if not value or len(value) > 512 or any(x in value for x in ("://", "?", "\n", "\r")):
        raise GateError("任务 ID 无效。")
    return value


def input_record(source, task, ffprobe):
    if source.startswith(("http://", "https://")):
        if task in VIDEO_TASKS:
            raise GateError("视频需先下载到本地再用 --input，以完成提交前色彩校验。")
        return {"kind": "url", "sourceUrlSha256": hashlib.sha256(source.encode()).hexdigest(),
                "mediaSha256": None, "probe": None}
    path = Path(source).resolve()
    if not path.is_file():
        raise GateError("--input 本地文件不存在。")
    probe = probe_media(path, ffprobe, task in VIDEO_TASKS)
    issues = sdr_issues(probe) if task in VIDEO_TASKS else []
    if task not in VIDEO_TASKS and not any(s.get("codec_type") == "video" for s in probe["streams"]):
        issues.append("image_not_decodable")
    return {"kind": "local", "path": str(path), "sha256": sha256(path),
            "bytes": path.stat().st_size, "probe": probe, "preflightIssues": issues}


def download_raw(url, out_path, before_publish):
    """Retry GET only; checkpoint downloaded hash before atomic no-clobber publish."""
    import requests
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        raise GateError("API 结果没有有效下载地址。")
    tmp = out_path.with_name(out_path.name + "." + uuid.uuid4().hex + ".part")
    try:
        for attempt in range(3):
            try:
                with requests.get(url, stream=True, timeout=(15, 180)) as response:
                    response.raise_for_status()
                    count = 0
                    with tmp.open("wb") as f:
                        for chunk in response.iter_content(1024 * 1024):
                            if chunk:
                                f.write(chunk)
                                count += len(chunk)
                        f.flush()
                        os.fsync(f.fileno())
                    expected = response.headers.get("Content-Length")
                    if count == 0 or (expected and not response.headers.get("Content-Encoding")
                                      and count != int(expected)):
                        raise GateError("API 原始结果下载不完整。")
                break
            except (requests.RequestException, GateError, ValueError):
                if attempt == 2:
                    raise GateError("下载失败；有 task_id 时续查重下，不要重新提交。") from None
                time.sleep(attempt + 1)
        before_publish(sha256(tmp))
        # Same-filesystem hard link publishes complete bytes and refuses overwrite,
        # including on Windows NTFS. The .part link is always removed afterward.
        os.link(tmp, out_path)
    finally:
        if tmp.exists():
            tmp.unlink()


def output_review(path, cp, ffprobe, task):
    result = {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path),
              "rawApiBytesPreserved": True, "localColorFiltersApplied": False,
              "visualReview": "pending", "accepted": False}
    try:
        probe = probe_media(path, ffprobe, task in VIDEO_TASKS)
        issues = sdr_issues(probe) if task in VIDEO_TASKS else []
        result["probe"] = probe
        if task in VIDEO_TASKS:
            original = (cp.get("input") or {}).get("probe") or {}
            source_video = next((s for s in original.get("streams", [])
                                 if s.get("codec_type") == "video"), {})
            output_video = next((s for s in probe.get("streams", [])
                                 if s.get("codec_type") == "video"), {})
            source_fps = fps_value(source_video.get("r_frame_rate"))
            output_fps = fps_value(output_video.get("r_frame_rate"))
            source_avg = fps_value(source_video.get("avg_frame_rate"))
            output_avg = fps_value(output_video.get("avg_frame_rate"))
            result["frameRateComparison"] = {"input": source_fps, "output": output_fps,
                                              "inputAverage": source_avg, "outputAverage": output_avg,
                                              "basis": "nominal_rate_plus_frame_count_and_one_frame_end_tolerance"}
            if source_fps is None or output_fps is None:
                issues.append("frame_rate_unverified")
            elif abs(source_fps - output_fps) > 1e-6:
                issues.append("frame_rate_changed")
            source_count = integer_count(source_video.get("frameCount")) or integer_count(source_video.get("nb_frames"))
            output_count = integer_count(output_video.get("frameCount")) or integer_count(output_video.get("nb_frames"))
            frame_delta = output_count - source_count if source_count and output_count else None
            result["frameCountComparison"] = {"input": source_count, "output": output_count,
                                              "delta": frame_delta, "toleranceFrames": 1}
            if frame_delta is None:
                issues.append("frame_count_unverified")
            elif abs(frame_delta) > 1:
                issues.append("frame_count_mismatch")
            # API MP4s can extend the last packet by ~16 ms: e.g. 180 frames at
            # nominal 30 fps / 6.016 s gives avg_frame_rate=5625/188. Accept this
            # only when average rate agrees with frame count and actual duration.
            actual_duration = probe.get("videoDurationSeconds")
            if output_avg is None:
                issues.append("average_frame_rate_unverified")
            elif output_count and actual_duration and output_fps:
                implied_duration_delta = output_count / output_avg - actual_duration
                result["frameRateComparison"]["averageImpliedDurationDeltaSeconds"] = implied_duration_delta
                if abs(implied_duration_delta) > 1 / output_fps + 0.002:
                    issues.append("frame_rate_changed")
            before_geometry, after_geometry = display_geometry(source_video), display_geometry(output_video)
            result["displayGeometryComparison"] = {"input": before_geometry, "output": after_geometry}
            if before_geometry is None or after_geometry is None:
                issues.append("display_geometry_unverified")
            else:
                scale_x = after_geometry["displayWidth"] / before_geometry["displayWidth"]
                scale_y = after_geometry["displayHeight"] / before_geometry["displayHeight"]
                result["displayGeometryComparison"].update(scaleX=scale_x, scaleY=scale_y)
                if (scale_x < 1 - 1e-6 or scale_y < 1 - 1e-6):
                    issues.append("resolution_reduced")
                if (abs(scale_x - scale_y) > 1e-6 or abs(scale_x - round(scale_x)) > 1e-6
                        or abs(scale_y - round(scale_y)) > 1e-6):
                    issues.append("display_scale_not_uniform_integer")
                if after_geometry["rotationDegrees"] != 0:
                    issues.append("output_rotation_not_normalized")
                if abs(after_geometry["sampleAspectRatio"] - 1) > 1e-6:
                    issues.append("output_pixels_not_square")
            baseline = original.get("videoDurationSeconds")
            if not baseline:
                issues.append("source_duration_unverified")
            else:
                fps = fps_value(source_video.get("r_frame_rate")) or 30
                tolerance = 1 / fps + 0.002
                actual = probe.get("videoDurationSeconds")
                result["durationToleranceSeconds"] = tolerance
                result["durationDeltaSeconds"] = actual - baseline if actual else None
                if actual is None or abs(actual - baseline) > tolerance:
                    issues.append("duration_mismatch")
                before_audio = [s for s in original.get("streams", []) if s.get("codec_type") == "audio"]
                after_audio = [s for s in probe.get("streams", []) if s.get("codec_type") == "audio"]
                if len(before_audio) != len(after_audio):
                    issues.append("audio_stream_count_changed")
                result["audioPreservation"] = "not_verified_api_may_reencode_use_original_edit_audio_for_delivery"
        elif not any(s.get("codec_type") == "video" for s in probe.get("streams", [])):
            issues.append("image_not_decodable")
    except (GateError, OSError, subprocess.SubprocessError):
        result["probe"] = None
        issues = ["output_probe_failed"]
    result["technicalIssues"] = sorted(set(issues))
    result["technicalChecksPassed"] = not issues
    return result


def emit(cp_path, cp, hint=None):
    payload = {"status": cp.get("status"), "task_id": cp.get("taskId"),
               "checkpoint": str(cp_path), "out": cp.get("out"), "accepted": False}
    if cp.get("output"):
        payload["technical_issues"] = cp["output"].get("technicalIssues")
    if hint:
        payload["hint"] = hint
    print(json.dumps(payload, ensure_ascii=False))


def refresh_legacy_input_probe(cp, ffprobe, task):
    """Refresh missing probe fields only after proving the original input bytes.

    Old checkpoints lack SAR/rotation/count fields. Never assume square pixels
    or zero rotation, change the recorded input identity, or submit a new task.
    """
    if task not in VIDEO_TASKS:
        return []
    original = cp.get("input") or {}
    old_probe = original.get("probe") or {}
    video = next((s for s in old_probe.get("streams", [])
                  if s.get("codec_type") == "video"), {})
    if (old_probe.get("probeSchemaVersion") == 2 and display_geometry(video) is not None
            and integer_count(video.get("frameCount")) and fps_value(video.get("r_frame_rate"))):
        return []
    issue = None
    expected = original.get("sha256")
    if (original.get("kind") != "local" or not original.get("path")
            or not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected)):
        issue = "legacy_input_identity_unverified"
    else:
        source = Path(original["path"])
        try:
            if not source.is_file():
                issue = "legacy_input_file_missing"
            elif sha256(source) != expected.lower():
                issue = "legacy_input_hash_mismatch"
            else:
                fresh = probe_media(source, ffprobe, True)
                if sha256(source) != expected.lower():
                    issue = "legacy_input_changed_during_probe"
                elif sdr_issues(fresh):
                    issue = "legacy_input_color_recheck_failed"
                else:
                    previous_digest = hashlib.sha256(json.dumps(old_probe, sort_keys=True,
                                                    separators=(",", ":")).encode()).hexdigest()
                    # Preserve path, sha256, bytes, taskId and all original
                    # submission fields. Only the derived probe is upgraded.
                    original["probe"] = fresh
                    cp["input"] = original
                    cp.setdefault("inputProbeRefreshes", []).append({
                        "refreshedAt": now(), "reason": "upgrade_missing_probe_fields",
                        "verifiedInputSha256": expected.lower(),
                        "previousProbeSha256": previous_digest, "probeSchemaVersion": 2,
                        "networkUsed": False})
        except (OSError, GateError, subprocess.SubprocessError):
            issue = "legacy_input_probe_refresh_failed"
    return [issue] if issue else []


def finish_review(out_path, cp_path, cp, ffprobe, task):
    refresh_issues = refresh_legacy_input_probe(cp, ffprobe, task)
    cp["output"] = output_review(out_path, cp, ffprobe, task)
    if refresh_issues:
        cp["output"]["technicalIssues"] = sorted(set(cp["output"]["technicalIssues"] + refresh_issues))
        cp["output"]["technicalChecksPassed"] = False
    passed = cp["output"]["technicalChecksPassed"]
    cp["status"] = "downloaded_pending_visual_review" if passed else "needs_review"
    save_checkpoint(cp_path, cp)
    emit(cp_path, cp, "保存的是 API 原始结果；技术检查不等于主观画质/美颜验收。")
    return 0 if passed else 3


def run(args):
    if args.brighten:
        raise GateError("--brighten 已废弃：不要在开拍结果叠加提亮/偏色滤镜。请先校正源片 HDR→SDR，再检查自然原始 API 输出。")
    if args.timeout is not None and args.timeout <= 0:
        raise GateError("--timeout 必须大于 0。")
    params = validate_params(args.params, args.task)
    task_id = task_id_value(args.task_id)
    out = Path(args.out).resolve()
    cp_path = Path(args.checkpoint).resolve() if args.checkpoint else Path(str(out) + ".kaipai.json")
    if cp_path == out:
        raise GateError("checkpoint 路径不能与输出文件相同。")
    if not task_id and (out.exists() or cp_path.exists()):
        raise GateError("输出或 checkpoint 已存在，已阻止重复消费。用原 task_id 续查；不要盲目新建任务。")
    if not task_id and not args.input:
        raise GateError("新任务必须提供 --input。")
    ffprobe = discover_ffprobe(args.ffprobe)
    if task_id and cp_path.exists():
        try:
            cp = json.loads(cp_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            raise GateError("checkpoint 无法读取；保留现场，禁止重新提交。") from None
        if cp.get("task") != args.task or cp.get("out") != str(out) or cp.get("taskId") not in (None, task_id):
            raise GateError("任务 ID、任务类型或输出路径与 checkpoint 不一致。")
        if args.params is not None and cp.get("params") != params:
            raise GateError("续查参数与原 checkpoint 不一致。")
        cp["taskId"] = task_id
    else:
        if out.exists():
            raise GateError("输出已存在且没有匹配 checkpoint；不覆盖、不重新消费。")
        cp = {"schemaVersion": 2, "createdAt": now(), "task": args.task,
              "taskId": task_id, "out": str(out), "params": params, "input": None,
              "status": "prepared", "submissionAttempted": False,
              "accepted": False, "visualReview": "pending"}
    if args.input:
        if not args.input.startswith(("http://", "https://")) and Path(args.input).resolve() in (out, cp_path):
            raise GateError("输入不得与输出或 checkpoint 相同。")
        record = input_record(args.input, args.task, ffprobe)
        old = cp.get("input")
        if old and any(old.get(k) != record.get(k) for k in ("sha256", "sourceUrlSha256")):
            raise GateError("续查输入与原任务哈希不一致。")
        if record.get("preflightIssues") and not task_id:
            save_json(Path(str(out) + ".preflight.json"),
                      {"status": "rejected_input", "input": record,
                       "apiSubmitted": False, "createdAt": now()})
            raise GateError("输入不是已核验的 SDR BT.709 limited，已阻止 API 提交；检查旁边的 .preflight.json，从原片修正，勿只改标签。")
        cp["input"] = record
        if task_id and not old:
            cp["inputBinding"] = "provided_on_resume_not_independently_bound_to_task"
    out.parent.mkdir(parents=True, exist_ok=True)
    if task_id and cp_path.exists():
        save_checkpoint(cp_path, cp)
    else:
        # First submissions must ALWAYS reserve exclusively after preflight.
        # An exists() branch here would let another first invocation overwrite
        # a checkpoint created while this process was checking the input.
        save_json(cp_path, cp, exclusive=True)
    if out.exists():
        expected = (cp.get("output") or {}).get("sha256") or cp.get("downloadSha256")
        if not expected or sha256(out) != expected:
            raise GateError("已有输出无法与 checkpoint 哈希对应；保留原文件，不覆盖。")
        return finish_review(out, cp_path, cp, ffprobe, args.task)

    os.environ["MT_AI_POLL_MIN_TOTAL_MS"] = str((args.timeout or DEFAULT_TIMEOUT[args.task]) * 1000)
    os.environ["MT_AI_PROGRESS"] = "0"

    def on_submitted(value):
        cp["taskId"] = task_id_value(value)
        cp["status"] = "submitted"
        cp["submittedAt"] = now()
        save_checkpoint(cp_path, cp)

    try:
        # Suppress SDK raw logging, including signed URLs in error responses.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            client = make_client(args.env_file, args.sdk_dir)
            if task_id:
                cp["status"] = "querying"
                save_checkpoint(cp_path, cp)
                result = client.query(task_id)
            else:
                cp["effectivePreset"] = effective_preset(args.task, params)
                cp["submissionAttempted"] = True
                cp["status"] = "submitting"
                save_checkpoint(cp_path, cp)
                result = client.execute(task_name=args.task, source=args.input,
                                        params=params, on_async_submitted=on_submitted)
    except Exception as exc:
        cp["failureType"] = type(exc).__name__
        if isinstance(exc, GateError):
            cp["localFailureReason"] = str(exc)
        cp["status"] = ("query_failed_resumable" if cp.get("taskId") else
                        "submission_outcome_unknown" if cp["submissionAttempted"] else
                        "setup_failed_no_submission")
        save_checkpoint(cp_path, cp)
        emit(cp_path, cp, "有 task_id 时续查；没有 ID 时先核实任务，禁止自动重提。")
        return 2 if cp.get("taskId") else 1
    if not isinstance(result, dict):
        cp["status"] = "invalid_result"
        save_checkpoint(cp_path, cp)
        emit(cp_path, cp, "保留 checkpoint，不重新提交。")
        return 2 if cp.get("taskId") else 1
    returned_id = task_id_value(result.get("task_id"))
    if returned_id:
        if cp.get("taskId") and cp["taskId"] != returned_id:
            cp["status"] = "task_id_mismatch"
            save_checkpoint(cp_path, cp)
            emit(cp_path, cp, "结果任务 ID 不一致，未下载。")
            return 1
        cp["taskId"] = returned_id
    urls = result.get("output_urls") or []
    if result.get("error") or result.get("skill_status") == "failed" or not urls:
        # SDK also labels polling timeouts/network aborts as skill_status=failed;
        # those are query failures, not an algorithm failure or permission to re-submit.
        failed = (result.get("skill_status") == "failed"
                  and result.get("error") not in ("poll_timeout", "poll_aborted"))
        cp["status"] = "api_failed" if failed else "pending_or_query_error"
        error = result.get("error")
        cp["apiErrorCode"] = error if isinstance(error, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", error) else None
        save_checkpoint(cp_path, cp)
        emit(cp_path, cp, "只用 --task-id 续查，不重新 execute。" if cp.get("taskId")
             else "缺少 task_id，需核实服务端状态；禁止自动重提。")
        return 1 if failed or not cp.get("taskId") else 2
    cp["status"] = "downloading"
    save_checkpoint(cp_path, cp)

    def before_publish(digest):
        cp["downloadSha256"] = digest
        cp["status"] = "download_verified_before_publish"
        save_checkpoint(cp_path, cp)

    try:
        download_raw(urls[0], out, before_publish)
        cp["status"] = "downloaded_unchecked"
        save_checkpoint(cp_path, cp)
    except Exception as exc:
        cp["status"] = "download_failed_resumable"
        cp["failureType"] = type(exc).__name__
        save_checkpoint(cp_path, cp)
        emit(cp_path, cp, "下载失败；保留 task_id，续查重下，不重新提交。")
        return 2 if cp.get("taskId") else 1
    return finish_review(out, cp_path, cp, ffprobe, args.task)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, choices=sorted(DEFAULT_TIMEOUT))
    parser.add_argument("--input", help="视频须为本地已正确转换的 SDR709 MP4/MOV；图片也支持 URL")
    parser.add_argument("--out", required=True, help="API 原始结果，不覆盖已有文件")
    parser.add_argument("--checkpoint", help="默认 <out>.kaipai.json")
    parser.add_argument("--task-id", help="只续查已有任务，不重复消费")
    parser.add_argument("--env-file", help="仅读取显式指定的凭证文件；优先使用环境变量")
    parser.add_argument("--sdk-dir", help="官方 SDK 目录；也可配置 KAIPAI_SDK_DIR")
    parser.add_argument("--params", help="JSON 对象；当前 hdvideoallinone 只接受已核验的空对象")
    parser.add_argument("--brighten", action="store_true", help="已废弃，传入即拒绝")
    parser.add_argument("--ffprobe", help="ffprobe 可执行文件路径")
    parser.add_argument("--timeout", type=int)
    args = parser.parse_args(argv)
    try:
        return run(args)
    except GateError as exc:
        print(json.dumps({"status": "rejected", "message": str(exc), "accepted": False}, ensure_ascii=False))
        return 1
    except Exception as exc:
        # Do not echo exception strings: they can contain signed URLs.
        print(json.dumps({"status": "local_failure", "failure_type": type(exc).__name__,
                          "accepted": False, "hint": "保留输出/checkpoint，核实状态；不要自动重新提交。"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
