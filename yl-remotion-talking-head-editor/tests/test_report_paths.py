"""Isolated report collision checks; no network, real video, or FFmpeg required."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate-video.py"
LAUNCHER = SCRIPT.with_name("validate-talking-head-video.ps1")


class ReportPathTests(unittest.TestCase):
    def run_validator(self, folder, video, report, *extra):
        return subprocess.run([sys.executable, "-B", "-X", "utf8", str(SCRIPT),
            "--video", str(video), "--report", str(report),
            "--ffmpeg", "__yl_missing_ffmpeg__", *extra], cwd=folder,
            capture_output=True, text=True, encoding="utf-8", check=False)

    def test_rejects_video_reference_manifest_and_protected_aliases(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            video = folder / "source.mp4"
            audio = folder / "reference.m4a"
            protected = folder / "protected.mov"
            manifest = folder / "protected.json"
            for item in (video, audio, protected):
                item.write_bytes(b"original media bytes")
            manifest.write_text(json.dumps({"files": [{"path": "protected.mov",
                "sha256": hashlib.sha256(protected.read_bytes()).hexdigest()}]}), encoding="utf-8")
            args = ("--reference-audio", str(audio), "--protection-manifest", str(manifest))
            baseline = {f: f.read_bytes() for f in (video, audio, protected, manifest)}
            cases = [video, Path("source.mp4"), audio, manifest, protected]
            for report in cases:
                with self.subTest(report=str(report)):
                    result = self.run_validator(folder, video, report, *args)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn("report_preflight", result.stdout)
                    self.assertEqual({f: f.read_bytes() for f in baseline}, baseline)
                    self.assertFalse(any(folder.glob("*_logs*")))

    def test_rejects_hardlink_and_unrelated_existing_report(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            video = folder / "source.mp4"
            video.write_bytes(b"original bytes")
            alias = folder / "alias.json"
            os.link(video, alias)
            report = folder / "existing.json"
            report.write_text("existing report", encoding="utf-8")
            for target in (alias, report):
                result = self.run_validator(folder, video, target)
                self.assertEqual(result.returncode, 1)
                self.assertIn("report_preflight", result.stdout)
            self.assertEqual(video.read_bytes(), b"original bytes")
            self.assertEqual(alias.read_bytes(), b"original bytes")
            self.assertEqual(report.read_text(encoding="utf-8"), "existing report")
            self.assertFalse(any(folder.glob("*_logs*")))

    def test_protected_missing_path_cannot_be_used_for_report(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            video = folder / "source.mp4"
            video.write_bytes(b"original bytes")
            report = folder / "future.json"
            manifest = folder / "protected.json"
            manifest.write_text(json.dumps({"files": [{"path": "future.json", "sha256": "0" * 64}]}), encoding="utf-8")
            result = self.run_validator(folder, video, report, "--protection-manifest", str(manifest))
            self.assertEqual(result.returncode, 1)
            self.assertIn("collides", result.stdout)
            self.assertFalse(report.exists())
            self.assertFalse(any(folder.glob("*_logs*")))

    def test_new_failure_report_is_written_and_old_evidence_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            video = folder / "source.mp4"
            video.write_bytes(b"original bytes")
            old_logs = folder / "validation_logs"
            old_logs.mkdir()
            sentinel = old_logs / "probe.stdout.log"
            sentinel.write_text("old evidence", encoding="utf-8")
            report = folder / "validation.json"
            result = self.run_validator(folder, video, report)
            self.assertEqual(result.returncode, 1)
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "FAIL")
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "old evidence")
            self.assertEqual(video.read_bytes(), b"original bytes")
            self.assertNotEqual(Path(payload["evidenceDirectory"]), old_logs)

    @unittest.skipUnless(shutil.which("powershell") or shutil.which("pwsh"), "PowerShell unavailable")
    def test_launcher_failure_never_writes_report_over_input(self):
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp) / "source.mp4"
            video.write_bytes(b"protected source")
            shell = shutil.which("powershell") or shutil.which("pwsh")
            result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-File", str(LAUNCHER),
                "-VideoPath", str(video), "-ReportPath", str(video),
                "-PythonPath", "__yl_missing_python__"], capture_output=True, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(video.read_bytes(), b"protected source")


if __name__ == "__main__":
    unittest.main()
