"""Export an ordered video/chapter manifest to Markdown/PDF; no network calls.

Requires Python 3.10+, reportlab, pypdf and caller-supplied embeddable TTF fonts.
"""
from __future__ import annotations

import argparse
import html
import io
import json
import re
import shutil
import tempfile
import unicodedata
import zipfile
from pathlib import Path
from urllib.parse import quote

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable, Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

CORE = Path(__file__).resolve().parents[2]
PAGE_W, PAGE_H = A4
BODY_W = PAGE_W - 96
INK = colors.HexColor('#20252D')
MUTED = colors.HexColor('#657080')
ACCENT = colors.HexColor('#247C86')
TOKEN = re.compile(r'(`[^`\n]+`|\*\*[^\n]+?\*\*|\[[^\]\n]+\]\([^\s)]+\))')


def inline(value, plain=False):
    """Parse a small explicit inline subset, escaping all raw markup."""
    parts = []
    for piece in TOKEN.split(value):
        if piece.startswith('`') and piece.endswith('`'):
            text = piece[1:-1]
            parts.append(text if plain else '<font color="#365B66">' + html.escape(text) + '</font>')
        elif piece.startswith('**') and piece.endswith('**'):
            text = inline(piece[2:-2], plain)
            parts.append(text if plain else '<b>' + text + '</b>')
        elif re.fullmatch(r'\[[^\]\n]+\]\([^\s)]+\)', piece):
            label, url = re.fullmatch(r'\[([^\]]+)\]\(([^)]+)\)', piece).groups()
            text = inline(label, plain)
            if plain or not re.match(r'^(https?://|mailto:)', url, re.I):
                parts.append(text)
            else:
                parts.append('<link href="' + html.escape(url, quote=True) + '" color="#247C86"><u>' + text + '</u></link>')
        else:
            parts.append(piece if plain else html.escape(piece))
    return ''.join(parts)


def parse_markdown(text):
    """Return (kind, value) blocks; reject unsupported constructs explicitly."""
    blocks = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        if not line:
            i += 1
            continue
        if line == '<div align="right">':
            signature = {'lines': [], 'image': None}
            i += 1
            while i < len(lines) and lines[i].strip() != '</div>':
                part = lines[i].strip()
                if part:
                    picture = re.fullmatch(r'<img src="([^"]+)" width="100" alt="[^"]*"\s*/?>', part)
                    paragraph = re.fullmatch(r'<p>(.*?)</p>', part)
                    if picture:
                        source = Path(html.unescape(picture[1]))
                        if not source.is_absolute() or not source.is_file():
                            raise ValueError('Signature image must be an existing absolute local path')
                        signature['image'] = str(source)
                    elif paragraph and '<' not in paragraph[1]:
                        signature['lines'].append(html.unescape(paragraph[1]))
                    else:
                        raise ValueError('Unsupported signature markup: ' + part)
                i += 1
            if i == len(lines) or not signature['lines']:
                raise ValueError('Incomplete signature block')
            blocks.append(('signature', signature))
            i += 1
            continue
        if (re.match(r'^(```|~~~|<|\$\$|!\[|\[\^[^]]+\]:|---$)', line)
                and line not in ('---', '***', '___')):
            raise ValueError(f'Unsupported Markdown at line {i + 1}: {line[:70]}')
        if re.search(r'!\[|\$\$|<\w|</\w|\[\^[^]]+\]|\$[^$\n]+\$', line):
            raise ValueError(f'Images/HTML/math/footnotes need another renderer (line {i + 1})')
        if raw.startswith(('    ', '\t')):
            raise ValueError(f'Indented code or nested list needs another renderer (line {i + 1})')
        if line in ('---', '***', '___'):
            blocks.append(('rule', ''))
        elif line.startswith('|'):
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                if re.search(r'!\[|<\w|</\w|\$\$|\[\^[^]]+\]', lines[i]):
                    raise ValueError(f'Unsupported content in table at line {i + 1}')
                row = [c.strip() for c in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-{3,}:?', c) for c in row):
                    rows.append(row)
                i += 1
            if not rows or not rows[0] or any(len(r) != len(rows[0]) for r in rows):
                raise ValueError('Table column counts differ')
            blocks.append(('table', rows))
            continue
        else:
            match = re.match(r'^(#{1,6})\s+(.+)', line)
            if match:
                blocks.append(('h' + str(len(match[1])), match[2]))
            elif line.startswith('> '):
                blocks.append(('quote', line[2:]))
            elif re.match(r'^[-*+]\s+', line):
                blocks.append(('bullet', re.sub(r'^[-*+]\s+', '', line)))
            else:
                blocks.append(('list' if re.match(r'^\d+[.)]\s+', line) else 'body', line))
        i += 1
    if not blocks or not any(k != 'rule' for k, _ in blocks):
        raise ValueError('Empty lesson Markdown')
    return blocks


def styles():
    base = dict(fontName='Course', fontSize=10.2, leading=16.5,
                textColor=INK, wordWrap='CJK', spaceAfter=6)
    result = {'body': ParagraphStyle('body', **base)}
    for n in range(1, 7):
        size = {1: 21, 2: 13.2, 3: 11.1}.get(n, 10.5)
        result['h' + str(n)] = ParagraphStyle(
            'h' + str(n), parent=result['body'], fontName='CourseBold',
            fontSize=size, leading=size * 1.4, spaceBefore=10 if n > 1 else 0,
            spaceAfter=7, keepWithNext=True)
    result['bullet'] = ParagraphStyle('bullet', parent=result['body'], leftIndent=13, firstLineIndent=-10)
    result['list'] = ParagraphStyle('list', parent=result['body'], leftIndent=14, firstLineIndent=-14)
    result['quote'] = ParagraphStyle('quote', parent=result['body'], borderColor=ACCENT,
                                    borderWidth=0.6, borderPadding=8, spaceBefore=5, spaceAfter=13)
    result['cell'] = ParagraphStyle('cell', parent=result['body'], fontSize=9, leading=14, spaceAfter=0)
    return result


def flowables(blocks, st):
    flow = []
    for kind, value in blocks:
        if kind == 'signature':
            signature_style = ParagraphStyle('signature', parent=st['body'], alignment=2,
                                             fontSize=9, leading=15, textColor=MUTED)
            text = Paragraph('<br/>'.join(html.escape(v) for v in value['lines']), signature_style)
            if value['image']:
                picture = Image(value['image'], width=100, height=130, kind='proportional')
                table = Table([[text, picture]], colWidths=[BODY_W - 115, 105], hAlign='RIGHT')
            else:
                table = Table([[text]], colWidths=[BODY_W], hAlign='RIGHT')
            table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                                       ('LEFTPADDING', (0, 0), (-1, -1), 0),
                                       ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                                       ('TOPPADDING', (0, 0), (-1, -1), 9),
                                       ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
            flow.append(table)
        elif kind == 'rule':
            flow.append(HRFlowable(width='100%', color=colors.HexColor('#DCE2E6'), spaceAfter=10))
        elif kind == 'table':
            cells = [[Paragraph(inline(c), st['cell']) for c in row] for row in value]
            widths = [BODY_W / len(value[0])] * len(value[0])
            table = Table(cells, colWidths=widths, repeatRows=1, hAlign='LEFT')
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E9F2F2')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 7),
                ('RIGHTPADDING', (0, 0), (-1, -1), 7),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('LINEBELOW', (0, 0), (-1, -1), 0.3, colors.HexColor('#DCE2E6')),
            ]))
            flow.extend([table, Spacer(1, 8)])
        else:
            prefix = '• ' if kind == 'bullet' else ''
            flow.append(Paragraph(prefix + inline(value), st[kind]))
    # A step stays together when it fits a page; oversized groups may split.
    grouped = []
    i = 0
    while i < len(flow):
        item = flow[i]
        if isinstance(item, Paragraph) and item.style.name == 'h3':
            # Nesting a standalone h2's keepWithNext around a KeepTogether can
            # leave the section label behind. Put it in the first step group.
            group = ([grouped.pop()] if grouped and isinstance(grouped[-1], Paragraph)
                     and grouped[-1].style.name == 'h2' else []) + [item]
            i += 1
            while i < len(flow) and not (isinstance(flow[i], Paragraph) and flow[i].style.name.startswith('h')):
                group.append(flow[i])
                i += 1
            grouped.append(KeepTogether(group))
        else:
            grouped.append(item)
            i += 1
    return grouped


def render_pdf(dest, flow, title, author, header, numbers=True):
    def decorate(c, doc):
        c.saveState()
        c.setFont('Course', 8)
        c.setFillColor(MUTED)
        # Paragraph wraps long course titles instead of clipping the header.
        p = Paragraph(html.escape(header), ParagraphStyle('header', fontName='Course', fontSize=7.5,
                                                         leading=9, textColor=MUTED, wordWrap='CJK'))
        _, height = p.wrap(BODY_W, 30)
        if height > 27:
            raise ValueError('Course title is too long for page header')
        p.drawOn(c, 48, PAGE_H - 22 - height)
        c.setStrokeColor(ACCENT)
        c.line(48, PAGE_H - 54, PAGE_W - 48, PAGE_H - 54)
        if numbers:
            c.drawRightString(PAGE_W - 48, 28, str(doc.page))
        c.restoreState()
    doc = SimpleDocTemplate(str(dest), pagesize=A4, leftMargin=48, rightMargin=48,
                            topMargin=68, bottomMargin=48, title=title, author=author)
    doc.build(flow, onFirstPage=decorate, onLaterPages=decorate)


def normalized(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFC', text))


def check_coverage(pdf, blocks):
    reader = PdfReader(pdf)
    text = normalized(''.join(p.extract_text() or '' for p in reader.pages))
    position = 0
    for kind, value in blocks:
        values = (value['lines'] if kind == 'signature' else
                  [c for row in value for c in row] if kind == 'table' else [value])
        for v in values:
            expected = normalized(inline(v, plain=True))
            if not expected:
                continue
            found = text.find(expected, position)
            if found < 0:
                raise ValueError(f'PDF text missing/out of order: {pdf.name}: {v[:70]}')
            position = found + len(expected)
    return len(reader.pages)


def safe_name(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip(' .')
    if not value or re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', value, re.I):
        raise ValueError('Invalid output filename')
    return value[:100].rstrip(' .')


def required_text(obj, key):
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip() or '\n' in value or '\r' in value:
        raise ValueError('Expected nonempty single-line string: ' + key)
    return value.strip()


def export(args):
    manifest = args.manifest.resolve()
    out, work = args.output_dir.resolve(), args.work_dir.resolve()
    for folder in (out, work):
        if folder == CORE or CORE in folder.parents:
            raise ValueError('Output/work directory must be outside the Skill core')
    if out == work or out in work.parents or work in out.parents:
        raise ValueError('Output/work directories must be separate')
    data = json.loads(manifest.read_text(encoding='utf-8-sig'))
    title = required_text(data, 'title')
    author, date = data.get('author', ''), data.get('date', '')
    if not isinstance(author, str) or not isinstance(date, str):
        raise ValueError('author/date must be strings')
    if not isinstance(data.get('lessons'), list) or not data['lessons']:
        raise ValueError('Manifest needs at least one lesson')
    records, seen = [], set()
    protected = {manifest, args.font.resolve(), args.bold_font.resolve()}
    for item in data['lessons']:
        lesson_id, label = required_text(item, 'id'), required_text(item, 'title')
        if lesson_id.casefold() in seen:
            raise ValueError('Duplicate lesson ID: ' + lesson_id)
        seen.add(lesson_id.casefold())
        source = (manifest.parent / required_text(item, 'markdown')).resolve()
        raw = source.read_bytes()
        blocks = parse_markdown(raw.decode('utf-8-sig'))
        base = safe_name(lesson_id + '_' + label)
        records.append(dict(id=lesson_id, title=label, source=source, raw=raw,
                            blocks=blocks, md=base + '.md', pdf=base + '.pdf'))
        protected.add(source)
    index = '00_阅读导航.md'
    combined = safe_name(title + '_合集') + '.pdf'
    bundle = safe_name(title + '_资料包') + '.zip'
    targets = [out / name for r in records for name in (r['md'], r['pdf'])]
    targets += [out / index, work / 'export-report.json']
    if not args.no_combined:
        targets.append(out / combined)
    if args.bundle:
        targets.append(out / bundle)
    if len({str(p).casefold() for p in targets}) != len(targets):
        raise ValueError('Output filenames collide')
    passthrough = {out / r['md'] for r in records if out / r['md'] == r['source']}
    for p in targets:
        if p in passthrough:
            continue
        if p.is_symlink() or p in protected or (p.exists() and any(p.samefile(src) for src in protected if src.exists())):
            raise ValueError('Refusing to overwrite an input: ' + str(p))
        if p.exists() and (p.is_dir() or not args.overwrite):
            raise ValueError('Output already exists: ' + str(p))
    pdfmetrics.registerFont(TTFont('Course', str(args.font), subfontIndex=0))
    pdfmetrics.registerFont(TTFont('CourseBold', str(args.bold_font), subfontIndex=0))
    pdfmetrics.registerFontFamily('Course', normal='Course', bold='CourseBold', italic='Course', boldItalic='CourseBold')
    st = styles()
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='course-export-', dir=work) as temp:
        stage = Path(temp)
        for r in records:
            (stage / r['md']).write_bytes(r['raw'])
            render_pdf(stage / r['pdf'], flowables(r['blocks'], st), r['title'], author, title)
            r['pages'] = check_coverage(stage / r['pdf'], r['blocks'])
        if not args.no_combined:
            # The TOC itself may span any number of pages. Page count stabilizes
            # once the actual page-number labels have been laid out.
            front_pages = 0
            for _ in range(8):
                flow = [Paragraph(inline(title), st['h1'])]
                if author or date:
                    flow.append(Paragraph(html.escape(' · '.join(v for v in (author, date) if v)), st['body']))
                flow.extend([Paragraph('阅读导航', st['h2']), Spacer(1, 8)])
                start = front_pages + 1
                for r in records:
                    r['start_page'] = start
                    flow.append(Paragraph(inline(f"{r['id']}　{r['title']}　·　第 {start} 页"), st['body']))
                    start += r['pages']
                render_pdf(stage / 'front.pdf', flow, title, author, title, numbers=False)
                count = len(PdfReader(stage / 'front.pdf').pages)
                if count == front_pages:
                    break
                front_pages = count
            else:
                raise ValueError('TOC pagination did not stabilize')
            writer = PdfWriter()
            writer.append(str(stage / 'front.pdf'), import_outline=False)
            for r in records:
                writer.append(str(stage / r['pdf']), import_outline=False)
                writer.add_outline_item(r['id'] + ' ' + r['title'], r['start_page'] - 1)
            overlay = io.BytesIO()
            c = canvas.Canvas(overlay, pagesize=A4)
            for number in range(1, len(writer.pages) + 1):
                c.setFillColor(colors.white)
                c.rect(PAGE_W - 102, 19, 58, 23, fill=1, stroke=0)
                c.setFillColor(MUTED)
                c.setFont('Course', 8)
                c.drawRightString(PAGE_W - 48, 28, str(number))
                c.showPage()
            c.save()
            overlay.seek(0)
            pages = PdfReader(overlay).pages
            for page, stamp in zip(writer.pages, pages):
                page.merge_page(stamp)
            writer.add_metadata({'/Title': title, '/Author': author})
            writer.write(str(stage / combined))
            reader = PdfReader(stage / combined)
            if len(reader.pages) != front_pages + sum(r['pages'] for r in records):
                raise ValueError('Combined page count differs')
            outlines = reader.outline
            if len(outlines) != len(records):
                raise ValueError('Combined bookmark count differs')
            for r, bookmark in zip(records, outlines):
                if reader.get_destination_page_number(bookmark) != r['start_page'] - 1:
                    raise ValueError('Combined bookmark destination differs')
            check_coverage(stage / combined, [block for r in records for block in r['blocks']])
        nav = ['# ' + title, '', '按章节阅读，对照原视频回看关键内容。', '']
        for r in records:
            label = (r['id'] + ' ' + r['title']).replace('[', '\\[').replace(']', '\\]')
            nav.append(f"- {label}：[Markdown](<{quote(r['md'])}>) · [PDF](<{quote(r['pdf'])}>)")
        if not args.no_combined:
            nav.extend(['', f'[打开 PDF 合集](<{quote(combined)}>)'])
        (stage / index).write_text('\n'.join(nav) + '\n', encoding='utf-8')
        names = [name for r in records for name in (r['md'], r['pdf'])] + [index]
        if not args.no_combined:
            names.append(combined)
        if args.bundle:
            with zipfile.ZipFile(stage / bundle, 'w', zipfile.ZIP_DEFLATED) as z:
                for name in names:
                    z.write(stage / name, name)
            with zipfile.ZipFile(stage / bundle) as z:
                if z.testzip() or set(z.namelist()) != set(names):
                    raise ValueError('Bundle verification failed')
            names.append(bundle)
        # Publish only after every lesson has passed file-level checks.
        out.mkdir(parents=True, exist_ok=True)
        for name in names:
            if out / name not in passthrough:
                shutil.copyfile(stage / name, out / name)
        report = dict(title=title, lessons=[{k: r[k] for k in ('id', 'title', 'md', 'pdf', 'pages')} for r in records],
                      files=names, text_coverage='passed', combined_bookmarks='not_requested' if args.no_combined else 'passed',
                      visual_review='pending', source_markdown='preserved')
        (work / 'export-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return dict(lessons=len(records), files=len(names), output=str(out), visual_review='pending')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', required=True, type=Path)
    p.add_argument('--output-dir', required=True, type=Path)
    p.add_argument('--work-dir', required=True, type=Path)
    p.add_argument('--font', required=True, type=Path)
    p.add_argument('--bold-font', required=True, type=Path)
    p.add_argument('--bundle', action='store_true')
    p.add_argument('--no-combined', action='store_true')
    p.add_argument('--overwrite', action='store_true')
    args = p.parse_args()
    try:
        print(json.dumps(export(args), ensure_ascii=False))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        p.error(str(exc))


if __name__ == '__main__':
    main()
