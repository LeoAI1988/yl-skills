"""Find installer-owned CJK fonts without bundling or downloading font assets."""
from pathlib import Path
import os
import shutil
import subprocess


def find_chinese_font(explicit: Path | None, serif: bool = False) -> Path:
    if explicit is not None:
        if not explicit.is_file():
            raise FileNotFoundError(f"Font does not exist: {explicit}")
        return explicit.resolve()
    names = (
        ("Source Han Serif SC Heavy (TrueType).ttf", "NotoSerifSC-VF.ttf", "NotoSerifCJK-Bold.ttc", "simsunb.ttf")
        if serif else
        ("Noto Sans SC Bold (TrueType).otf", "NotoSansCJK-Bold.ttc", "SourceHanSansSC-Bold.otf", "msyhbd.ttc", "simhei.ttf")
    )
    roots = [Path.home() / ".local/share/fonts", Path.home() / "Library/Fonts",
             Path("/Library/Fonts"), Path("/System/Library/Fonts"), Path("/usr/share/fonts/opentype/noto")]
    if os.name == "nt":
        windows_root = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
        if windows_root:
            roots.insert(0, Path(windows_root) / "Fonts")
    for root in roots:
        for name in names:
            candidate = root / name
            if candidate.is_file():
                return candidate.resolve()
    fc_match = shutil.which("fc-match")
    if fc_match:
        family = "Noto Serif CJK SC" if serif else "Noto Sans CJK SC"
        result = subprocess.run([fc_match, "-f", "%{file}", f"{family}:lang=zh:weight=bold"],
                                capture_output=True, text=True, timeout=10, check=False)
        candidate = Path(result.stdout.strip())
        if result.returncode == 0 and candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError("No CJK font found. Install a licensed CJK font or pass --font /path/to/font.")
