"""Summarize comparable video snapshots, without network or warehouse dependencies."""
import argparse
import csv
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import statistics

REQUIRED = {'publication_id', 'captured_at', 'views', 'data_maturity', 'content_origin', 'metric_scope'}


def summarize(rows, threshold=100000, top=3, maturity='mature', origin='original_short_video'):
    if threshold <= 0 or top <= 0:
        raise ValueError('Threshold and top must be positive')
    latest, seen, excluded, scopes = {}, {}, 0, set()
    for row in rows:
        if not REQUIRED <= row.keys():
            raise ValueError('Missing required CSV columns')
        ident = row['publication_id'].strip()
        scope = row['metric_scope'].strip()
        if not ident or not scope:
            raise ValueError('Empty ID or metric scope')
        scopes.add(scope)
        at = datetime.fromisoformat(row['captured_at'])
        if at.utcoffset() is None:
            raise ValueError('Capture timestamp must include timezone')
        if row['data_maturity'] not in ('early', 'mature', 'unknown') or row['content_origin'] not in ('original_short_video', 'live_clip', 'unknown'):
            raise ValueError('Invalid maturity or origin')
        text = row['views'].strip()
        views = int(text) if text else None
        if views is not None and views < 0:
            raise ValueError('Views cannot be negative')
        signature = (views, row['data_maturity'], row['content_origin'], scope)
        key = (ident, at)
        if key in seen and seen[key] != signature:
            raise ValueError('Conflicting snapshots at identical ID/time')
        seen[key] = signature
        if row['data_maturity'] != maturity or (origin != 'all' and row['content_origin'] != origin):
            excluded += 1
            continue
        if ident not in latest or at > latest[ident][0]:
            latest[ident] = (at, views)
    if len(scopes) > 1:
        raise ValueError('Mixed metric scopes; split into comparable input files')
    values = sorted(v[1] for v in latest.values() if v[1] is not None)
    count, total = len(values), sum(values)
    hits = [v for v in values if v >= threshold]
    bands = {'<1000': 0, '1000-9999': 0, '10000-49999': 0, '50000-99999': 0, '>=100000': 0}
    for v in values:
        band = '<1000' if v < 1000 else '1000-9999' if v < 10000 else '10000-49999' if v < 50000 else '50000-99999' if v < 100000 else '>=100000'
        bands[band] += 1
    return {'status': 'STATISTICS_ONLY', 'metric_scope': next(iter(scopes), None),
            'input_rows': len(rows), 'excluded_rows': excluded,
            'eligible_publications': len(latest), 'known_views_count': count,
            'missing_views_count': len(latest) - count,
            'maturity': maturity, 'origin': origin, 'views_total': total,
            'views_mean': statistics.mean(values) if count else None,
            'views_median': statistics.median(values) if count else None,
            'trimmed_median_remove_one_each': statistics.median(values[1:-1]) if count >= 3 else None,
            'trimmed_removed_values': [values[0], values[-1]] if count >= 3 else [],
            'bands': bands, 'breakout_threshold': threshold, 'breakout_count': len(hits),
            'breakout_fraction_known_views': len(hits) / count if count else None,
            'breakout_views_share': sum(hits) / total if total else None,
            'top_requested': top, 'top_actual': min(top, count),
            'top_views_share': sum(values[-top:]) / total if total else None,
            'coverage': 'not_assessed',
            'note': 'Missing values excluded from numeric denominators; no causal or sales inference.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--threshold', type=int, default=100000)
    p.add_argument('--top', type=int, default=3)
    p.add_argument('--maturity', choices=['early', 'mature', 'unknown'], default='mature')
    p.add_argument('--origin', choices=['original_short_video', 'live_clip', 'unknown', 'all'], default='original_short_video')
    args = p.parse_args()
    if args.output.exists() or args.output.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        p.error('Use a new output file outside the Skill directory')
    try:
        data = args.input.read_bytes()
        reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig')))
        if not REQUIRED <= set(reader.fieldnames or []):
            raise ValueError('Missing required CSV columns')
        result = summarize(list(reader), args.threshold, args.top, args.maturity, args.origin)
        result['input_sha256'] = hashlib.sha256(data).hexdigest()
        with args.output.open('x', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(json.dumps({'status': result['status'], 'publications': result['eligible_publications']}))
    except (ValueError, TypeError, OSError) as exc:
        p.exit(2, str(exc) + '\n')


if __name__ == '__main__':
    main()
