#!/usr/bin/env python3
"""Transcribe a video and extract representative frames for cover planning."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--model", default="small")
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--language", default="zh")
    parser.add_argument("--frame-count", type=int, default=9)
    parser.add_argument(
        "--initial-prompt",
        default="人工智能，DeepSeek，Codex，AI Agent，短视频，内容创作。",
    )
    parser.add_argument("--reuse-transcript", action="store_true")
    return parser.parse_args()


def require_tool(name: str) -> str:
    executable = shutil.which(name)
    if not executable:
        raise FileNotFoundError(f"Required executable is not on PATH: {name}")
    return executable


def run(command: list[str], env: dict[str, str] | None = None) -> None:
    subprocess.run(command, check=True, env=env)


def probe_video(ffprobe: str, video: Path) -> dict[str, object]:
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "format=duration:stream=width,height",
            "-of",
            "json",
            str(video),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    data = json.loads(result.stdout)
    stream = data["streams"][0]
    return {
        "durationSeconds": float(data["format"]["duration"]),
        "width": int(stream["width"]),
        "height": int(stream["height"]),
    }


def extract_frames(
    ffmpeg: str, video: Path, frames_dir: Path, duration: float, count: int
) -> list[Path]:
    if not 3 <= count <= 15:
        raise ValueError("frame count must stay between 3 and 15")
    frames_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    timestamps = [0.0] + [duration * index / count for index in range(1, count)]
    for index, timestamp in enumerate(timestamps):
        output = frames_dir / f"frame-{index:02d}.jpg"
        run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(output),
            ]
        )
        paths.append(output.resolve())
    return paths


def transcribe(whisper: str, args: argparse.Namespace, transcript: Path) -> None:
    if args.reuse_transcript and transcript.exists():
        return
    command = [
        whisper,
        str(args.video),
        "--model",
        args.model,
        "--language",
        args.language,
        "--task",
        "transcribe",
        "--output_dir",
        str(args.out_dir),
        "--output_format",
        "all",
        "--verbose",
        "False",
        "--fp16",
        "False",
        "--initial_prompt",
        args.initial_prompt,
    ]
    if args.model_dir:
        command.extend(["--model_dir", str(args.model_dir)])
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    run(command, env=environment)


def main() -> None:
    args = parse_args()
    args.video = args.video.resolve()
    args.out_dir = args.out_dir.resolve()
    if not args.video.is_file():
        raise FileNotFoundError(f"Video does not exist: {args.video}")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg = require_tool("ffmpeg")
    ffprobe = require_tool("ffprobe")
    metadata = probe_video(ffprobe, args.video)
    frames = extract_frames(
        ffmpeg,
        args.video,
        args.out_dir / "frames",
        float(metadata["durationSeconds"]),
        args.frame_count,
    )
    transcript = args.out_dir / f"{args.video.stem}.txt"
    if not (args.reuse_transcript and transcript.is_file()):
        transcribe(require_tool("whisper"), args, transcript)
    if not transcript.exists():
        raise FileNotFoundError(f"Whisper did not create transcript: {transcript}")

    manifest = {
        "schemaVersion": 1,
        "inputMode": "video",
        "video": str(args.video),
        "videoBytes": args.video.stat().st_size,
        **metadata,
        "transcript": str(transcript.resolve()),
        "frames": [str(path) for path in frames],
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = args.out_dir / "video-evidence.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
