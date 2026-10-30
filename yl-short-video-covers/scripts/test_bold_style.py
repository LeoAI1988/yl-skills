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
                "--title", "从想法|到作品",
                "--yellow-terms", "作品", "--out", str(work/(name+".png")),
                "--manifest-out", str(work/(name+".json")), *extra], capture_output=True)
        def validate(name):
            return subprocess.run([sys.executable, "-X", "utf8", str(scripts/"validate_bold_cover.py"),
                "--image", str(work/(name+".png")), "--manifest", str(work/(name+".json")),
                "--expected-primary-title", "从想法到作品", "--expected-supplement", "",
                "--source-mode", "video", "--check-line-overlap"], capture_output=True)
        for name in ("first", "repeat"):
            result=render(name)
            assert result.returncode == 0, result.stderr.decode(errors="replace")
            result=validate(name)
            assert result.returncode == 0, result.stdout.decode(errors="replace")
        assert (work/"first.png").read_bytes() == (work/"repeat.png").read_bytes()
        assert len(json.loads((work/"first.json").read_text(encoding="utf-8"))["lines"]) == 2
        layout = json.loads((work/"first.json").read_text(encoding="utf-8"))
        sizes = [line["fontSize"] for line in layout["lineStyles"]]
        assert max(sizes) / min(sizes) >= 1.18, "equal-length lines lost size hierarchy"
        assert layout["titleTop"] == 190 and min(line["y"] for line in layout["lineStyles"]) > 115
        portrait = Image.new("RGBA", (300,400), (240,240,240,255))
        portrait.save(work/"portrait.png")
        assert render("portrait", ["--avatar", str(work/"portrait.png")]).returncode == 0
        placement = json.loads((work/"portrait.json").read_text(encoding="utf-8"))["avatarPlacement"]
        x0,y0,x1,y1 = placement["visibleBounds"]
        assert (x0+x1)/2 > 1080*.65 and y0 > 1440*.4
        assert .18 < (x1-x0)*(y1-y0)/(1080*1440) < .38
        assert render("three", ["--supplement", "立即行动"]).returncode == 0
        result = subprocess.run([sys.executable, "-X", "utf8", str(scripts/"validate_bold_cover.py"),
            "--image", str(work/"three.png"), "--manifest", str(work/"three.json"),
            "--expected-title", "从想法到作品立即行动", "--source-mode", "video"], capture_output=True)
        assert result.returncode == 0, result.stdout.decode(errors="replace")
        assert render("four", ["--supplement", "清晰表达|立即行动"]).returncode == 0
        result = subprocess.run([sys.executable, "-X", "utf8", str(scripts/"validate_bold_cover.py"),
            "--image", str(work/"four.png"), "--manifest", str(work/"four.json"),
            "--expected-title", "从想法到作品清晰表达立即行动", "--source-mode", "video"], capture_output=True)
        assert result.returncode == 0, result.stdout.decode(errors="replace")
        assert render("five", ["--supplement", "清晰表达|立即行动|更清楚"]).returncode != 0
        # Reject five total lines even if an existing image/manifest is supplied.
        forged = json.loads((work/"repeat.json").read_text(encoding="utf-8"))
        forged["lines"] = ["从", "想", "法", "到", "作品"]
        (work/"repeat.json").write_text(json.dumps(forged), encoding="utf-8")
        result = validate("repeat")
        assert result.returncode != 0 and b"1-4" in result.stdout
        for name, extra in [
            ("yellow", ["--yellow-terms", "从想法,到作品"]),
            ("rotation", ["--line-angles", "1,0"]),
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
        # Explicit hierarchy can occupy the former fixed background corridor.
        from render_bold_cover import render_line_image, find_font
        from PIL import ImageFont
        lines = ['看见','问题','才','有办法']; sizes = [280,260,350,200]
        cursor = 140; plan=[]
        for line,size in zip(lines,sizes):
            layer=render_line_image(line,ImageFont.truetype(str(find_font(None)),size),set(),{'问题'},0)
            bounds=layer.getchannel('A').getbbox()
            plan.append({'fontSize':size,'top':cursor});cursor += bounds[3]-bounds[1]+10
        assert cursor < 1440
        layout_path=work/'layout.json';layout_path.write_text(json.dumps(plan),encoding='utf-8')
        command=[sys.executable,'-B','-X','utf8',str(scripts/'render_bold_cover.py'),
                 '--title','|'.join(lines),'--yellow-terms','问题','--line-layout',str(layout_path),
                 '--out',str(work/'explicit.png')]
        result=subprocess.run(command,capture_output=True)
        assert result.returncode==0,result.stderr.decode(errors='replace')
        em=json.loads((work/'explicit.json').read_text('utf-8'))
        assert [x['fontSize'] for x in em['lineStyles']]==sizes, 'explicit hierarchy silently shrunk'
        assert em['lineStyles'][-1]['actualBounds'][3] > 1440*.79
        result=subprocess.run([sys.executable,'-B',str(scripts/'validate_bold_cover.py'),
                               '--image',str(work/'explicit.png'),'--expected-title',''.join(lines),
                               '--check-line-overlap'],capture_output=True)
        assert result.returncode==0,result.stdout.decode(errors='replace')
        plan[-1]['top']=1400;layout_path.write_text(json.dumps(plan),encoding='utf-8')
        assert subprocess.run(command,capture_output=True).returncode!=0, 'overflow accepted'
        # Even a forged up-to-date manifest cannot make an erased background pass.
        image=Image.open(work/"first.png")
        image.paste((5,7,10), (0,1100,360,1440))
        image.save(work/"first.png")
        m=json.loads((work/"first.json").read_text(encoding="utf-8"))
        m["sha256"]=hashlib.sha256((work/"first.png").read_bytes()).hexdigest()
        (work/"first.json").write_text(json.dumps(m),encoding="utf-8")
        assert validate("first").returncode != 0, "erased background passed"
    print("PASS: concise titles without filler, three/four lines accepted, five rejected, large size hierarchy and lower-right portrait, approved master/style checks")


if __name__ == "__main__":
    main()
