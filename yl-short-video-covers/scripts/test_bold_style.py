"""Behavior checks for the stable technology-cover defaults and failure modes."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tempfile
from PIL import Image, ImageDraw
from tech_background import approved_background_path, DEFAULT_BACKGROUND, BACKGROUND_SHA256


def main():
    scripts = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="cover-style-") as temp:
        work = Path(temp)
        def render(name, extra=()):
            return subprocess.run([sys.executable, "-X", "utf8", str(scripts/"render_bold_cover.py"),
                "--title", "从想法|到作品", "--supplement", "清晰表达|立即行动",
                "--yellow-terms", "到作品", "--out", str(work/(name+".png")),
                "--manifest-out", str(work/(name+".json")), *extra], capture_output=True)
        def validate(name):
            return subprocess.run([sys.executable, "-X", "utf8", str(scripts/"validate_bold_cover.py"),
                "--image", str(work/(name+".png")), "--manifest", str(work/(name+".json")),
                "--expected-primary-title", "从想法到作品", "--expected-supplement", "清晰表达立即行动",
                "--source-mode", "script", "--allow-sparse-headline", "--check-line-overlap"], capture_output=True)
        for name in ("first", "repeat"):
            result=render(name)
            assert result.returncode == 0, result.stderr.decode(errors="replace")
            result=validate(name)
            assert result.returncode == 0, result.stdout.decode(errors="replace")
        assert (work/"first.png").read_bytes() == (work/"repeat.png").read_bytes()
        for name, extra in [
            ("yellow", ["--yellow-terms", "从想法,到作品,清晰表达,立即行动"]),
            ("rotation", ["--line-angles", "1,0,0,0"]),
            ("box", ["--boxed-terms", "从想法"]),
        ]:
            assert render(name, extra).returncode != 0, name+" incorrectly accepted"
        plain=work/"plain.png"
        Image.new("RGB", (1080,1440), (5,7,10)).save(plain)
        assert render("missing_texture", ["--background", str(plain)]).returncode != 0
        # Another detailed circuit picture must fail even when it is not solid black.
        d = ImageDraw.Draw(Image.open(plain))
        alternate = Image.new("RGB", (1080,1440), (5,7,10)); d = ImageDraw.Draw(alternate)
        for y in range(0,1440,20): d.line((0,y,1080,y+120), fill=(80,85,90), width=2)
        alternate.save(work/"alternate.png")
        assert render("wrong_template", ["--background", str(work/"alternate.png")]).returncode != 0
        assert hashlib.sha256(DEFAULT_BACKGROUND.read_bytes()).hexdigest() == BACKGROUND_SHA256
        try:
            approved_background_path(work/"missing.png")
        except FileNotFoundError:
            pass
        else:
            raise AssertionError("missing master must never fall back")
        # Even a forged up-to-date manifest cannot make an erased background pass.
        image=Image.open(work/"first.png")
        image.paste((5,7,10), (0,1100,360,1440))
        image.save(work/"first.png")
        m=json.loads((work/"first.json").read_text(encoding="utf-8"))
        m["sha256"]=hashlib.sha256((work/"first.png").read_bytes()).hexdigest()
        (work/"first.json").write_text(json.dumps(m),encoding="utf-8")
        assert validate("first").returncode != 0, "erased background passed"
    print("PASS: approved master hash, defaults, deterministic render, missing/alternate/solid/erased backgrounds and all-yellow/rotation/box rejected")


if __name__ == "__main__":
    main()
