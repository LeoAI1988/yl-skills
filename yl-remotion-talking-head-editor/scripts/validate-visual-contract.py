"""Compatibility entry point for existing project scripts and CLI commands."""
from pathlib import Path
import runpy

implementation = Path(__file__).resolve().parents[2] / "yl-video-text-layout" / "scripts" / Path(__file__).name
if __name__ == "__main__":
    runpy.run_path(str(implementation), run_name="__main__")
else:
    # Some existing projects import public functions from this file by path.
    globals().update({k: v for k, v in runpy.run_path(str(implementation)).items() if not k.startswith("_")})
