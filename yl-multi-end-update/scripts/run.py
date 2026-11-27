"""Run trusted, installer-owned endpoint adapters and retain per-endpoint outcomes."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone


PHASES = ("check", "apply", "verify")


def endpoints(config):
    entries = json.loads(config.read_text(encoding="utf-8-sig"))["endpoints"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("Configure at least one endpoint")
    seen = set()
    for entry in entries:
        name = entry["name"]
        if not isinstance(name, str) or not name.strip() or name in seen:
            raise ValueError("Endpoint names must be unique and non-empty")
        seen.add(name)
        if not Path(entry["cwd"]).is_absolute():
            raise ValueError(f"{name}: expected an absolute working directory")
        for phase in PHASES:
            argv = entry[phase]
            if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) and arg for arg in argv):
                raise ValueError(f"{name}: invalid {phase} command")
    return entries


@contextmanager
def exclusive(folder):
    # OS-owned locks are released when a run exits, including after a crash.
    with (folder / "update.lock").open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def invoke(entry, phases):
    result = {"name": entry["name"], "phases": {}}
    for phase in phases:
        print(f"[{entry['name']}] {phase}", flush=True)
        try:
            code = subprocess.run(entry[phase], cwd=entry["cwd"], check=False).returncode
        except OSError as exc:
            print(str(exc), file=sys.stderr)
            code = 1
        result["phases"][phase] = code
        if code != 0:
            break
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=PHASES)
    parser.add_argument("--profile", type=Path, default=Path(os.environ.get("YL_PROFILE", "~/.config/yl-toolbox/profile.json")))
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    profile = args.profile.expanduser().resolve()
    config = (args.config or profile.with_name("multi-end-update.json")).expanduser().resolve()
    core = Path(json.loads(profile.read_text(encoding="utf-8-sig"))["core_root"]).expanduser().resolve()
    if config.is_relative_to(core):
        raise ValueError("Endpoint configuration belongs outside the distributed core")
    entries = endpoints(config)
    if args.mode != "check":
        # Check live source, immutable ZIP and installer before distributing any files.
        verified = subprocess.run([sys.executable, "-B", str(core / "tools" / "verify.py")], cwd=core)
        if verified.returncode:
            return verified.returncode
    if args.mode == "apply":
        folder = config.parent / "multi-end-update-state"
        folder.mkdir(exist_ok=True)
        with exclusive(folder):
            results = [invoke(entry, PHASES) for entry in entries]
            receipt = {"time": datetime.now(timezone.utc).isoformat(), "endpoints": results}
            pending = folder / "latest.tmp"
            pending.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            pending.replace(folder / "latest.json")
    else:
        results = [invoke(entry, (args.mode,)) for entry in entries]
    print(json.dumps(results, ensure_ascii=False))
    return int(any(any(result["phases"].values()) for result in results))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, KeyError, ValueError) as error:
        sys.exit(str(error))
