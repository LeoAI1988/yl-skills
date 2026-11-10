"""Local timeline audit and immutable two-stage review snapshots. No media edits."""
import argparse
import hashlib
import json
import math
import mimetypes
import re
import unicodedata
from fractions import Fraction
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

CORE = Path(__file__).resolve().parents[2]
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}")
SHA = re.compile(r"[0-9a-f]{64}")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def external(path):
    path = Path(path).expanduser().resolve()
    if path == CORE or CORE in path.parents:
        raise ValueError("Runtime outputs must stay outside the Skill cluster")
    return path


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    path = external(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.write("\n")


def identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError("Invalid stable source/clip ID")
    return value


def text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Missing nonempty text: " + field)
    return value


def integer(value, field, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError("Invalid integer: " + field)
    return value


def positive(value, field):
    if isinstance(value, bool):
        raise ValueError("Invalid number: " + field)
    result = Fraction(str(value))
    if result <= 0:
        raise ValueError("Expected positive number: " + field)
    return result


def ceil(value):
    return -(-value.numerator // value.denominator)


def union(intervals):
    result = []
    for start, end in sorted(intervals):
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return result


def intersection(a, b):
    i = j = total = 0
    while i < len(a) and j < len(b):
        total += max(0, min(a[i][1], b[j][1]) - max(a[i][0], b[j][0]))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return total


def normalized(value):
    return re.sub(r"\W+", "", unicodedata.normalize("NFKC", value).casefold())


def audit(plan):
    fps = positive(plan["fps"], "fps")
    sources = {}
    for source in plan["sources"]:
        ident = identifier(source["id"])
        if ident in sources:
            raise ValueError("Duplicate source ID")
        sources[ident] = integer(source["duration_us"], "source duration", 1)
    maximum = plan.get("max_duration_seconds")
    maximum = positive(maximum, "maximum duration") if maximum is not None else None
    threshold = plan.get("shared_ratio_warning")
    if threshold is not None and (type(threshold) not in (float, int) or not math.isfinite(threshold) or not 0 <= threshold <= 1):
        raise ValueError("Overlap warning ratio must be between zero and one")
    clips, uses, warnings, seen = [], {}, [], set()
    for clip in plan["clips"]:
        ident = identifier(clip["id"])
        if ident in seen:
            raise ValueError("Duplicate clip ID")
        seen.add(ident)
        for key in ("title", "question", "thesis", "opening", "ending"):
            text(clip.get(key), key)
        if not isinstance(clip.get("logic"), list) or not clip["logic"]:
            raise ValueError("Each clip needs its own logic outline")
        for step in clip["logic"]:
            text(step, "logic step")
        if not clip.get("segments"):
            raise ValueError("A clip cannot have an empty timeline")
        cursor = 0
        exact = Fraction(0)
        mapping = []
        intervals = {}
        for number, segment in enumerate(clip["segments"]):
            source = segment["source"]
            if source not in sources:
                raise ValueError("Unknown source: " + str(source))
            start = integer(segment["start_us"], "source start")
            end = integer(segment["end_us"], "source end", 1)
            if not start < end <= sources[source]:
                raise ValueError("Source interval is empty or outside its source")
            text(segment.get("text"), "retained original words")
            text(segment.get("purpose"), "segment purpose")
            rate = positive(segment["rate"], "playback rate")
            ideal = Fraction(end - start, 1_000_000) / rate * fps
            exact += ideal
            if "output_frames" in segment:
                count = integer(segment["output_frames"], "output frame count", 1)
                if abs(count - ideal) > 1:
                    raise ValueError("Calibrated frame count differs by more than one frame")
            else:
                count = ceil(exact) - cursor
                if count < 1:
                    raise ValueError("Subframe interval requires an explicit media decision")
            mapping.append({"segment": number, "source": source, "start_us": start,
                            "end_us": end, "rate": str(rate), "output_start_frame": cursor,
                            "output_frames": count, "output_end_frame": cursor + count})
            cursor += count
            intervals.setdefault(source, []).append((start, end))
        duration = Fraction(cursor, 1) / fps
        if maximum is not None and duration > maximum:
            raise ValueError("Clip " + ident + " exceeds the final-duration limit")
        uses[ident] = {source: union(parts) for source, parts in intervals.items()}
        unique = sum(b - a for parts in uses[ident].values() for a, b in parts)
        clips.append({"id": ident, "frames": cursor, "duration_seconds": float(duration),
                      "retained_audio_seconds": float(exact / fps),
                      "quantization_error_seconds": float(duration - exact / fps),
                      "unique_source_seconds": unique / 1_000_000, "mapping": mapping})
    if not clips:
        raise ValueError("No clips in plan")
    pairs = []
    for index, left in enumerate(clips):
        for right in clips[index + 1:]:
            shared = sum(intersection(parts, uses[right["id"]].get(source, []))
                         for source, parts in uses[left["id"]].items()) / 1_000_000
            a, b = left["unique_source_seconds"], right["unique_source_seconds"]
            ratio = shared / min(a, b)
            pair = {"a": left["id"], "b": right["id"], "shared_source_seconds": shared,
                    "shared_min_ratio": ratio, "jaccard": shared / (a + b - shared)}
            pairs.append(pair)
            if threshold is not None and shared > 0 and ratio > threshold:
                warnings.append({"kind": "source_overlap", **pair})
    original = {c["id"]: c for c in plan["clips"]}
    for pair in pairs:
        for field in ("question", "thesis", "opening", "ending"):
            if normalized(original[pair["a"]][field]) == normalized(original[pair["b"]][field]):
                warnings.append({"kind": "identical_" + field, "a": pair["a"], "b": pair["b"]})
    return {"status": "COMPUTABLE_CHECKS_PASS", "fps": str(fps), "clips": clips,
            "pairs": pairs, "warnings": warnings, "semantic_review": "NOT_AUTOMATED",
            "actual_listening": "NOT_PERFORMED"}


PAGE = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>多主题短视频</title>
<style>body{margin:0;background:#121318;color:#eee;font:16px system-ui}main{max-width:1300px;margin:auto;padding:24px}header{margin-bottom:24px}button,a{font:inherit;color:#f5d33d}button{background:#292b33;border:1px solid #555;border-radius:6px;padding:8px;cursor:pointer}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:20px}article{padding:18px;background:#1d1f26;border-radius:12px}video{width:100%;border-radius:8px}img{max-width:180px;width:100%;display:block;margin:12px auto}.muted{color:#b8bac3}a{display:inline-block;margin:10px 12px 10px 0}.points{display:flex;gap:8px;flex-wrap:wrap}h2{font-size:20px}</style>
<style>button[aria-pressed="true"]{background:#f5d33d;color:#16171c;border-color:#f5d33d}</style>
<main><header><h1 id="heading"></h1><p id="status" class="muted"></p>
<button id="edited">剪辑版 · 未增强</button> <button id="enhanced">开拍增强版</button>
</header><div id="cards" class="grid"></div><p class="muted">页面展示已登记资产；实际听审、语义与画质验收以项目回执为准。</p></main>
<script>const data=__DATA__;const videos=[];let stage='edited';
document.getElementById('heading').textContent='多主题短视频 · '+data.batch;
document.getElementById('status').textContent=data.edit_status==='feedback_applied'?'本批修改已执行，按阶段查看。':'本批仍在制作或收集意见，请查看项目回执。';
function draw(){['edited','enhanced'].forEach(s=>document.getElementById(s).setAttribute('aria-pressed',String(stage===s)));videos.forEach(v=>v.pause());videos.length=0;const root=document.getElementById('cards');root.replaceChildren();
data.clips.forEach(c=>{const card=document.createElement('article');const title=document.createElement('h2');title.textContent=c.title;card.append(title);
const note=document.createElement('p');note.className='muted';note.textContent=data.batch+' · 内容 '+c.content_revision+' · '+(stage==='edited'?'未增强':'开拍增强');card.append(note);
if(c.cover_url){const image=document.createElement('img');image.src=c.cover_url;image.alt=c.title+'封面';card.append(image);const a=document.createElement('a');a.href=c.cover_url;a.download=c.id+'-cover';a.textContent='下载封面';card.append(a)}
const asset=c[stage];if(!asset){const p=document.createElement('p');p.textContent='本条这一阶段尚未生成';card.append(p);root.append(card);return}
const video=document.createElement('video');video.controls=true;video.playsInline=true;video.preload='metadata';video.src=asset.url;video.addEventListener('play',()=>videos.forEach(v=>{if(v!==video)v.pause()}));videos.push(video);card.append(video);
const duration=document.createElement('p');duration.className='muted';duration.textContent='登记时长 '+asset.duration_seconds.toFixed(3)+' 秒';card.append(duration);
const a=document.createElement('a');a.href=asset.url;a.download=asset.filename;a.textContent='下载当前版本';card.append(a);
const points=document.createElement('div');points.className='points';(asset.points||[]).forEach(p=>{const button=document.createElement('button');button.textContent=p.label;button.onclick=()=>{video.currentTime=p.time;video.play().catch(()=>{})};points.append(button)});card.append(points);root.append(card)})}
['edited','enhanced'].forEach(s=>document.getElementById(s).onclick=()=>{stage=s;draw()});draw();</script></html>"""


def snapshot(manifest, base, out):
    base = Path(base).resolve()
    out = external(out)
    if out.exists():
        raise ValueError("Snapshot directory already exists; choose a new batch snapshot")
    batch = text(manifest.get("batch"), "batch")
    assets, clips, seen = {}, [], set()

    def asset(path, key, expected=None):
        path = Path(path).expanduser()
        path = (path if path.is_absolute() else base / path).resolve()
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError("Missing or empty asset: " + str(path))
        digest = sha256(path)
        if expected is not None and expected != digest:
            raise ValueError("Asset SHA-256 does not match its declared version")
        stat = path.stat()
        assets[key] = {"path": str(path), "sha256": digest, "size": stat.st_size,
                       "mtime_ns": stat.st_mtime_ns,
                       "mime": mimetypes.guess_type(path.name)[0] or "application/octet-stream"}
        return "/asset/" + key, path.name

    for source in manifest["clips"]:
        ident = identifier(source["id"])
        if ident in seen:
            raise ValueError("Duplicate clip in batch snapshot")
        seen.add(ident)
        for field in ("timeline_sha256", "audio_sha256"):
            if not isinstance(source.get(field), str) or not SHA.fullmatch(source[field]):
                raise ValueError("A batch needs explicit timeline and original-audio fingerprints")
        clip = {"id": ident, "title": text(source.get("title"), "title"),
                "content_revision": text(source.get("content_revision"), "content revision")}
        if not source.get("edited"):
            raise ValueError("Every clip needs its final edited, unenhanced asset")
        paths = set()
        for stage in ("edited", "enhanced"):
            item = source.get(stage)
            if item is None:
                clip[stage] = None
                continue
            for field in ("timeline_sha256", "audio_sha256"):
                if item.get(field) != source[field]:
                    raise ValueError("Stage is bound to a different timeline or original audio")
            url, filename = asset(item["path"], ident + "." + stage, item.get("sha256"))
            resolved = assets[ident + "." + stage]["path"]
            if resolved in paths:
                raise ValueError("Different stages cannot point to the same media file")
            paths.add(resolved)
            duration = float(positive(item.get("duration_seconds", source.get("duration_seconds")), "duration"))
            points = item.get("points", [])
            for point in points:
                time = point["time"]
                if type(time) not in (int, float) or not math.isfinite(time) or not 0 <= time < duration:
                    raise ValueError("Review point is outside this stage's current timeline")
                text(point.get("label"), "review-point label")
            clip[stage] = {"url": url, "filename": filename, "duration_seconds": duration, "points": points}
        if source.get("cover"):
            clip["cover_url"], _ = asset(source["cover"], ident + ".cover")
        clips.append(clip)
    if not clips:
        raise ValueError("Empty batch snapshot")
    data = {"batch": batch, "edit_status": manifest.get("edit_status", "in_progress"), "clips": clips}
    encoded = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    out.mkdir(parents=True)
    (out / "index.html").write_text(PAGE.replace("__DATA__", encoded), encoding="utf-8")
    write_json(out / "assets.json", assets)
    write_json(out / "batch.json", data)
    return {"status": "SNAPSHOT_CREATED", "batch": batch, "clips": len(clips), "out": str(out),
            "media_copied": False, "media_edited": False, "actual_listening": "NOT_PERFORMED"}


def byte_range(header, size):
    if header is None:
        return 0, size - 1
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header)
    if not match or not any(match.groups()):
        raise ValueError("Invalid single byte range")
    first, last = match.groups()
    if not first:
        count = int(last)
        if count < 1:
            raise ValueError("Empty suffix range")
        return max(0, size - count), size - 1
    start = int(first)
    end = min(int(last), size - 1) if last else size - 1
    if start >= size or end < start:
        raise ValueError("Unsatisfiable byte range")
    return start, end


def handler(snapshot_root):
    root = external(snapshot_root)
    index = (root / "index.html").read_bytes()
    assets = read_json(root / "assets.json")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_HEAD(self):
            self.respond(False)

        def do_GET(self):
            self.respond(True)

        def respond(self, body):
            route = unquote(urlsplit(self.path).path)
            if route in ("/", "/index.html"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(index)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if body:
                    self.wfile.write(index)
                return
            record = assets.get(route[len("/asset/"):]) if route.startswith("/asset/") else None
            if record is None:
                self.send_error(404)
                return
            path = Path(record["path"])
            try:
                with path.open("rb") as file:
                    stat = path.stat()
                    if stat.st_size != record["size"] or stat.st_mtime_ns != record["mtime_ns"]:
                        self.send_error(409, "Asset changed after snapshot")
                        return
                    try:
                        start, end = byte_range(self.headers.get("Range"), stat.st_size)
                    except ValueError:
                        self.send_response(416)
                        self.send_header("Content-Range", "bytes */" + str(stat.st_size))
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    partial = self.headers.get("Range") is not None
                    self.send_response(206 if partial else 200)
                    self.send_header("Content-Type", record["mime"])
                    self.send_header("Content-Length", str(end - start + 1))
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("ETag", '"' + record["sha256"] + '"')
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    if partial:
                        self.send_header("Content-Range", f"bytes {start}-{end}/{stat.st_size}")
                    self.end_headers()
                    if body:
                        file.seek(start)
                        remaining = end - start + 1
                        while remaining:
                            chunk = file.read(min(1024 * 1024, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except FileNotFoundError:
                self.send_error(410)
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("audit")
    check.add_argument("plan", type=Path)
    check.add_argument("--out", type=Path)
    snap = sub.add_parser("snapshot")
    snap.add_argument("manifest", type=Path)
    snap.add_argument("--out", type=Path, required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("snapshot", type=Path)
    serve.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    try:
        if args.command == "audit":
            result = audit(read_json(args.plan))
            if args.out:
                if args.out.suffix.lower() != ".json":
                    raise ValueError("Audit output must be a JSON file")
                write_json(args.out, result)
        elif args.command == "snapshot":
            result = snapshot(read_json(args.manifest), args.manifest.resolve().parent, args.out)
        else:
            server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(args.snapshot))
            print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}/", "read_only": True}), flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
            return 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps({"status": "ERROR", "message": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
