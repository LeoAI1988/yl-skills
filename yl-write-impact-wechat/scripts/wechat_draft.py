"""Save one approved WeChat HTML package as one draft. The default is offline."""
import argparse
import base64
import hashlib
import io
import ipaddress
import json
import mimetypes
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup, Comment, NavigableString
from filelock import FileLock, Timeout
from PIL import Image, ImageChops, ImageStat


API = "https://api.weixin.qq.com/cgi-bin/"
CDN = {"mmbiz.qpic.cn", "mmbiz.qlogo.cn", "mmbizurl.cn"}


def call(session, endpoint, token=None, **kwargs):
    params = kwargs.pop("params", {})
    if token:
        params["access_token"] = token
    try:
        response = session.post(API + endpoint, params=params, timeout=(10, 40),
                                allow_redirects=False, **kwargs)
    except requests.RequestException as exc:
        raise ValueError(f"{endpoint}: {type(exc).__name__}") from None
    if response.status_code != 200:
        raise ValueError(f"{endpoint}: HTTP {response.status_code}")
    try:
        data = json.loads(response.content.decode("utf-8-sig"))
    except (UnicodeError, ValueError):
        raise ValueError(f"{endpoint}: 无法读取微信回包") from None
    if not isinstance(data, dict):
        raise ValueError(f"{endpoint}: 回包格式异常")
    code = data.get("errcode", 0)
    if code:
        detail = ""
        if code == 40164:
            match = re.search(r"invalid ip\s+([a-f\d:.]+)", data.get("errmsg", ""), re.I)
            if match:
                addr = ipaddress.ip_address(match[1])
                detail = f"；请将出口 IP {getattr(addr, 'ipv4_mapped', None) or addr} 加入白名单"
        raise ApiError(f"{endpoint}: 微信错误 {code}{detail}")
    return data


class ApiError(ValueError):
    """WeChat returned an explicit error code."""


def cdn_url(url):
    parsed = urlsplit(url)
    return parsed.scheme in ("https", "http") and parsed.hostname in CDN and not parsed.username and parsed.port in (None, 80, 443)


def same_image(session, returned, uploaded, original):
    if not cdn_url(returned) or not cdn_url(uploaded):
        return False
    def resource(url):
        path = urlsplit(url).path
        return re.sub(r"/\d+/?$", "", re.sub(r"^/sz_mmbiz_", "/mmbiz_", path))
    if resource(returned) == resource(uploaded):
        return True
    # WeChat may re-encode an uploaded figure and assign it a different CDN path.
    url = urlsplit(returned)._replace(scheme="https", netloc=urlsplit(returned).hostname).geturl()
    response = session.get(url, timeout=(10, 25), allow_redirects=False)
    if response.status_code != 200:
        return False
    if response.content == original:
        return True
    with Image.open(io.BytesIO(original)) as local, Image.open(io.BytesIO(response.content)) as remote:
        if abs(local.width / local.height - remote.width / remote.height) > 0.02:
            return False
        thumbs = [im.convert("RGB").resize((128, 128), Image.Resampling.LANCZOS) for im in (local, remote)]
        return max(ImageStat.Stat(ImageChops.difference(*thumbs)).mean) < 5


def prepare(args):
    validator = Path(__file__).with_name("validate-wechat-article.mjs")
    cover = (args.md.parent / args.cover).resolve()
    # The approved text is the length baseline for packaging.
    cmd = ["node", str(validator), "--phase", "package", "--md", str(args.md),
           "--html", str(args.html), "--cover", str(cover), "--max-chars", str(args.md.stat().st_size)]
    if args.cta_file:
        cmd.extend(["--cta-file", str(args.cta_file)])
    subprocess.run(cmd, check=True)
    page = BeautifulSoup(args.html.read_text(encoding="utf-8-sig"), "html.parser")
    body = page.select_one("article#article")
    if body is None or body.select_one("h1") is None:
        raise ValueError("排版页缺少正文或标题")
    title = body.h1.get_text().strip()
    body.h1.decompose()
    images = []
    for index, img in enumerate(body.find_all("img")):
        match = re.fullmatch(r"data:(image/(?:jpeg|png));base64,(.+)", img.get("src", ""), re.S)
        if not match:
            raise ValueError("微信正文图请使用本地 PNG 或 JPEG")
        images.append((match[1], base64.b64decode(match[2], validate=True)))
        img["src"] = str(index)
    markup = body.decode_contents().strip()
    if not title or not body.get_text(strip=True) or body.select("script,style,button,iframe,a[download]"):
        raise ValueError("核对排版页的标题、正文与工具栏范围")
    return title, markup, images, cover


def layout(markup):
    """Keep paragraph and image positions while ignoring layout-only markup."""
    soup = BeautifulSoup(markup, "html.parser")
    urls, parts, events = [], [], []

    def finish_text():
        text = re.sub(r"\s+", " ", "".join(parts)).strip()
        if text:
            events.append(("text", text))
        parts.clear()

    def walk(node):
        if isinstance(node, Comment):
            return
        if isinstance(node, NavigableString):
            parts.append(str(node))
        elif node.name == "img":
            finish_text()
            urls.append(node.get("data-src") or node.get("src", ""))
            events.append(("image", len(urls)))
        else:
            block = node.name in {"p", "h1", "h2", "h3", "div", "section", "li", "br", "blockquote"}
            if block:
                finish_text()
            for child in node.children:
                walk(child)
            if block:
                finish_text()

    walk(soup)
    finish_text()
    return events, urls


def verify(session, token, article, record, draft_id):
    title, markup, images, _ = article
    items = call(session, "draft/get", token, json={"media_id": draft_id}).get("news_item", [])
    if len(items) != 1 or items[0].get("title") != title or items[0].get("thumb_media_id") != record.get("cover_id"):
        raise ValueError("草稿标题、篇数或封面与本次记录不符")
    segments, urls = layout(items[0].get("content", ""))
    if segments != layout(markup)[0] or len(urls) != len(images):
        raise ValueError("回读的正文、结尾或插图位置有差异")
    for url, uploaded, (_, data) in zip(urls, record["image_urls"], images, strict=True):
        if not same_image(session, url, uploaded, data):
            raise ValueError("微信回读的正文图与原图不符")


def existing_drafts(session, token, title):
    matches = []
    offset = 0
    while True:
        result = call(session, "draft/batchget", token, json={"offset": offset, "count": 20, "no_content": 1})
        rows = result.get("item", [])
        if not rows and offset < result["total_count"]:
            raise ValueError("草稿列表分页不完整，请稍后核对")
        for row in rows:
            if any(item.get("title") == title for item in row["content"]["news_item"]):
                matches.append(row["media_id"])
        offset += len(rows)
        if not rows or offset >= result["total_count"]:
            return matches


def save(session, token, appid, article, receipt):
    title, markup, images, cover = article
    data = cover.read_bytes()
    fingerprint = hashlib.sha256()
    for part in [appid.encode(), title.encode(), markup.encode(), data, *(image for _, image in images)]:
        fingerprint.update(hashlib.sha256(part).digest())
    key = fingerprint.hexdigest()
    record = json.loads(receipt.read_text(encoding="utf-8")) if receipt.exists() else {"key": key, "image_urls": []}
    if record["key"] != key:
        raise ValueError("账号或定稿已有变化，请用原回执定位旧稿后按本次要求处理")
    def persist():
        tmp = receipt.with_suffix(receipt.suffix + ".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(receipt)

    draft_id = record.get("draft_id")
    if not draft_id:
        matches = existing_drafts(session, token, title)
        if record.get("pending") or matches:
            # Only an exact prior submission may be reattached automatically.
            if len(matches) != 1 or not record.get("cover_id") or len(record["image_urls"]) != len(images):
                raise ValueError("有同题草稿或上次提交结果待核对，请按回执核对草稿箱后续办")
            draft_id = matches[0]
            verify(session, token, article, record, draft_id)
        else:
            for mime, binary in images[len(record["image_urls"]):]:
                name = "figure" + mimetypes.guess_extension(mime)
                url = call(session, "media/uploadimg", token, files={"media": (name, binary, mime)})["url"]
                if not cdn_url(url):
                    raise ValueError("微信未返回正文素材地址")
                record["image_urls"].append(url)
                persist()
            if not record.get("cover_id"):
                response = call(session, "material/add_material", token, params={"type": "image"},
                                files={"media": (cover.name, data, mimetypes.guess_type(cover.name)[0])})
                record["cover_id"] = response["media_id"]
                persist()
            body = BeautifulSoup(markup, "html.parser")
            for img, url in zip(body.find_all("img"), record["image_urls"], strict=True):
                img["src"] = url
            payload = {"title": title, "content": str(body), "thumb_media_id": record["cover_id"]}
            record["pending"] = True
            persist()
            try:
                draft_id = call(session, "draft/add", token, json={"articles": [payload]})["media_id"]
            except ApiError:
                record.pop("pending")
                persist()
                raise
        record["draft_id"] = draft_id
        record.pop("pending", None)
        persist()
    if record.pop("verified", None):
        persist()
    verify(session, token, article, record, draft_id)
    record["verified"] = True
    persist()
    return draft_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("md", "html", "cover"):
        parser.add_argument("--" + flag, required=True, type=Path)
    parser.add_argument("--cta-file", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    article = prepare(args)
    print(f"本地成品已核对：{article[0]}，独立封面 1 张，正文图 {len(article[2])} 张")
    if not args.save:
        return
    receipt = args.receipt or args.md.with_suffix(".wechat-draft.json")
    appid, secret = os.getenv("WECHAT_APP_ID"), os.getenv("WECHAT_APP_SECRET")
    if not appid or not secret:
        raise ValueError("请通过当前进程安全提供 WECHAT_APP_ID 和 WECHAT_APP_SECRET")
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(receipt) + ".lock", timeout=0), requests.Session() as session:
        token = call(session, "stable_token", json={"grant_type": "client_credential", "appid": appid,
                                                    "secret": secret, "force_refresh": False})["access_token"]
        save(session, token, appid, article, receipt)
        print(f"草稿已保存并回读：{article[0]}")


if __name__ == "__main__":
    try:
        main()
    except Timeout:
        sys.exit("同一回执正在处理中，请等当前任务完成后再回读")
    except (KeyError, ValueError, OSError, requests.RequestException, subprocess.CalledProcessError) as exc:
        sys.exit(str(exc))
