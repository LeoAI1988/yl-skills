"""Compatibility for existing landscape projects and command lines."""
from pathlib import Path
import runpy

implementation = Path(__file__).resolve().parents[2] / "yl-video-text-layout" / "scripts" / "layout.py"
shared = runpy.run_path(str(implementation))
read_json = shared["read_json"]
settings = shared["settings"]
resolve = shared["landscape_layout"]
title_backdrop = shared["title_backdrop"]


def main():
    shared["main"](landscape_only=True)


if __name__ == "__main__":
    main()
