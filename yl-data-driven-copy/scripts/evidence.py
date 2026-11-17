"""Prepare local evidence, compare drafts and retain immutable draft/feedback records."""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import glob
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile


POST_FIELDS = (
    'publication_id', 'title', 'date', 'published_at', 'public', 'mature',
    'content_type', 'views', 'completion_pct', 'three_sec_pct', 'fast_flip_pct',
    'watch_seconds', 'duration_seconds', 'follows', 'shares', 'source',
)
PLAN_FIELDS = (
    'mode', 'account', 'objective', 'parent_sources', 'retained_logic',
    'new_information', 'source_spans', 'product', 'cta', 'snapshot_fingerprint',
)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, data):
    """Replace one derived pointer only after its complete contents are on disk."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encode(data))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def immutable_json(folder, data):
    """Content-addressed writes make identical retries idempotent."""
    raw = encode(data)
    path = Path(folder) / (digest(raw) + '.json')
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('Content hash conflict')
        return path
    atomic_json(path, data)
    return path


@contextmanager
def exclusive_lock(root, name):
    """OS-managed locks release after a crash and serialize related local mutations."""
    lock_dir = root / '.locks'
    lock_dir.mkdir(parents=True, exist_ok=True)
    with (lock_dir / (name + '.lock')).open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def load_config(args):
    profile_path = Path(args.profile or os.environ.get('YL_PROFILE') or
                        Path.home() / '.config/yl-toolbox/profile.json')
    profile = read_json(profile_path) if profile_path.exists() else {}
    configured = profile.get('writing', {}).get('data_driven', {}).get('config_file')
    config_path = Path(args.config or configured or profile_path.parent / 'writing/data-driven.json')
    config = read_json(config_path)
    root = Path(config['work_root']).resolve()
    core = Path(__file__).resolve().parents[2]
    if root == core or core in root.parents:
        raise ValueError('work_root must be outside the generic core')
    return config, root


def latest_json(patterns, date_field=None):
    if isinstance(patterns, str):
        patterns = [patterns]
    paths = sorted({Path(p).resolve() for pattern in patterns for p in glob.glob(pattern)})
    if not paths:
        raise FileNotFoundError('No input matched the configured source patterns')
    choices = []
    for path in paths:
        value = read_json(path)
        if date_field:
            stamp = value
            for field in date_field.split('.'):
                stamp = stamp[field]
            # Captures may contain a time range and a descriptive suffix.
            stamp = re.search(r'20\d{2}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2})?', str(stamp))
            if not stamp:
                raise ValueError('Missing source capture date in ' + str(path))
            stamp = re.sub(r'\D', '', stamp.group()).ljust(12, '0')
        else:
            dates = re.findall(r'20\d{6}', str(path))
            if not dates:
                raise ValueError('A dated source path is required for ' + str(path))
            stamp = max(dates)
        choices.append((stamp, path, value))
    choices.sort(key=lambda row: (row[0], str(row[1])))
    top_date = choices[-1][0]
    same_date = [r for r in choices if r[0] == top_date]
    if len({digest(r[1].read_bytes()) for r in same_date}) > 1:
        raise ValueError('Conflicting sources share the latest capture date. Configure one explicitly.')
    return choices[-1][1:]


def body_from_sales(text):
    """Read the supported sales-manuscript layout without including metric history."""
    if '## 主文本' in text:
        return text.split('## 主文本', 1)[1].split('\n---', 1)[0].split('\n## ', 1)[0].strip()
    first_section = text.split('\n---', 1)[0]
    lines = []
    for line in first_section.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(('# ', '>')):
            continue
        if re.match(r'^(账号 |成交金额|小店播放量|播放量 |小店截图|成交产品|视频号完播)', stripped):
            continue
        lines.append(stripped)
    return '\n\n'.join(lines)


def duration_group(seconds):
    if seconds is None:
        return 'unknown'
    for maximum, label in ((30, '<30s'), (60, '30-59s'), (120, '60-119s')):
        if seconds < maximum:
            return label
    return '>=120s'


def rank_posts(posts):
    ranking_file = Path(__file__).resolve().parents[2] / 'yl-media/scripts/ranking.py'
    spec = importlib.util.spec_from_file_location('yl_copy_ranking', ranking_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cohorts = defaultdict(list)
    for post in posts:
        key = (post['account'], post['date'][:7], duration_group(post.get('duration_seconds')))
        row = dict(post)
        row['ranking_eligible'] = (post.get('public') is True and post.get('mature') is True
                                   and post.get('content_type') == 'video')
        cohorts[key].append(row)
    result = []
    for key, rows in sorted(cohorts.items()):
        ranked = module.rank(rows, rule='3.0-raw-follows')
        count = sum(r['综合评分'] is not None for r in ranked)
        for row in ranked:
            row.update(cohort=list(key), cohort_ranked_n=count)
            result.append(row)
    return result


def prepare(config, root):
    inputs = {}
    warnings = []
    posts, accounts = [], []
    source_texts = {}

    def track(path):
        path = Path(path).resolve()
        inputs[str(path)] = digest(path.read_bytes())
        return path

    for account_config in config['accounts']:
        source, review = latest_json(account_config['review_glob'], 'meta.captured_at')
        track(source)
        account = account_config['account']
        declared_account = review['meta'].get('account')
        if declared_account and account not in declared_account:
            raise ValueError('Configured account disagrees with review metadata')
        accounts.append({'account': account, 'captured_at': review['meta']['captured_at'],
                         'from': review['meta']['from'], 'to': review['meta']['to'],
                         'hit_threshold': review['meta'].get('hit_threshold'),
                         'maturity_hours': review['meta'].get('maturity_hours'),
                         'source': str(source), 'products': review.get('products', [])})
        for record in review['posts']:
            post = {key: record.get(key) for key in POST_FIELDS}
            if not post['publication_id'] or not post['date']:
                raise ValueError('Post is missing its stable ID or publication date')
            post.update(account=account, captured_at=review['meta']['captured_at'])
            posts.append(post)
    keys = [(p['account'], p['publication_id']) for p in posts]
    if len(set(keys)) != len(keys):
        raise ValueError('Duplicate account/publication key')
    posts = rank_posts(posts)
    post_map = {(p['account'], p['publication_id']): p for p in posts}

    sales_source, sales_input = latest_json(config['sales_glob'])
    track(sales_source)
    sales = []
    for record in sales_input:
        manuscript = Path(record['manuscript'])
        entry = {key: record.get(key) for key in
                 ('title', 'account', 'published', 'window', 'manuscript', 'evidence')}
        entry['sales_id'] = digest(encode([entry['account'], entry['published'], str(manuscript)]))[:20]
        entry['amount'] = float(str(record['amount']).replace(',', ''))
        entry['attribution_basis'] = 'recorded_video_sales_snapshot'
        entry['sales_period_type'] = record.get('sales_period_type', 'unknown_or_publication_filter')
        entry['index_source'] = str(sales_source)
        evidence_path = Path(entry['evidence']) if entry['evidence'] else None
        entry['evidence_status'] = 'available' if evidence_path and evidence_path.is_file() else 'missing'
        if entry['evidence_status'] == 'available':
            track(evidence_path)
        entry['body_status'] = 'missing'
        if manuscript.is_file():
            track(manuscript)
            text = manuscript.read_text(encoding='utf-8-sig')
            entry['source_sha256'] = digest(manuscript.read_bytes())
            entry['body'] = body_from_sales(text)
            entry['body_status'] = 'available_requires_context_read'
            if '## 同题参考稿' in text or '两稿仅供参考' in text or '以下两稿' in text:
                entry['body_status'] = 'ambiguous_versions'
            product = re.search(r'成交产品[：:]([^\n]+)', text)
            entry['product'] = product.group(1).strip() if product else None
            source_texts[str(manuscript)] = entry['body']
        else:
            warnings.append({'kind': 'missing_sales_manuscript', 'path': str(manuscript)})
        sales.append(entry)

    transcript_candidates = []
    if config.get('catalog_glob'):
        catalog_source, catalog = latest_json(config['catalog_glob'], 'generated_at')
        track(catalog_source)
        catalog_accounts = defaultdict(set)
        for post in catalog['posts']:
            catalog_accounts[post['publication_id']].add(post['account'])
        for pid, item in catalog.get('transcripts', {}).items():
            path = item.get('source_path')
            if not path:
                continue
            linked_accounts = catalog_accounts[pid]
            candidate = {'publication_id': pid, 'accounts': sorted(linked_accounts),
                         'path': path, 'evidence': item.get('match_evidence'),
                         'status': 'candidate_requires_context_read'}
            if len(linked_accounts) != 1:
                candidate['status'] = 'ambiguous_account'
            elif (next(iter(linked_accounts)), pid) not in post_map:
                candidate['status'] = 'outside_current_snapshot'
            if Path(path).is_file():
                track(path)
                actual = digest(Path(path).read_bytes())
                candidate['source_sha256'] = actual
                if item.get('source_sha256') and item['source_sha256'] != actual:
                    candidate['status'] = 'changed_source_requires_review'
            else:
                candidate['status'] = 'missing_source'
            transcript_candidates.append(candidate)

    links = []
    links_file = config.get('links_file')
    if links_file and Path(links_file).is_file():
        track(links_file)
        links = read_json(links_file)
    verified_paths = {}
    for link in links:
        key = (link['account'], link['publication_id'])
        path = Path(link['path'])
        if link.get('status') == 'rejected':
            for item in transcript_candidates:
                if item['publication_id'] == key[1] and str(path) == item['path']:
                    item.update(status='rejected', review_reason=link['evidence'])
            continue
        if link.get('status') != 'verified' or not link.get('evidence'):
            raise ValueError('Link requires a reviewed status and evidence')
        if not path.is_file() or digest(path.read_bytes()) != link['source_sha256']:
            warnings.append({'kind': 'changed_verified_link', 'path': str(path)})
            continue
        if key in verified_paths and verified_paths[key] != path.resolve():
            raise ValueError('Conflicting verified transcripts for the same publication')
        verified_paths[key] = path.resolve()
        track(path)
        if key in post_map:
            post_map[key]['verified_transcript'] = link
        for sale in sales:
            if sale['sales_id'] == link.get('sales_id'):
                if sale['account'] != key[0] or Path(sale['manuscript']).resolve() != path.resolve():
                    raise ValueError('Sales link disagrees with the account or manuscript')
                sale['current_post_key'] = list(key)
                sale['current_post_available'] = key in post_map
        source_texts[str(path)] = body_from_sales(path.read_text(encoding='utf-8-sig'))

    history = [read_json(p) for p in sorted((root / 'history/drafts').glob('*.json'))]
    feedback = [read_json(p) for p in sorted((root / 'history/feedback').glob('*.json'))]
    feedback_results = []
    for event in feedback:
        key = (event['account'], event['publication_id'])
        post = post_map.get(key)
        feedback_results.append({**event, 'current_metrics': post,
                                 'sales_evidence': [s for s in sales if s.get('current_post_key') == list(key)]})
    track(Path(__file__).resolve().parents[2] / 'yl-media/scripts/ranking.py')
    fingerprint = digest(encode({'inputs': inputs, 'accounts': accounts, 'ranking_rule': '3.0-raw-follows'}))
    packet = {'schema_version': 1, 'snapshot_fingerprint': fingerprint,
              'inputs': inputs, 'accounts': accounts,
              'ranking_rule': '3.0-raw-follows', 'posts': posts, 'sales': sales,
              'transcript_candidates': transcript_candidates,
              'source_texts': source_texts, 'history': history, 'feedback': feedback_results,
              'warnings': warnings,
              'summary': {'posts': len(posts), 'sales_records': len(sales),
                          'sales_single_body': sum(s['body_status'] == 'available_requires_context_read' for s in sales),
                          'sales_ambiguous_body': sum(s['body_status'] == 'ambiguous_versions' for s in sales),
                          'verified_transcript_links': sum('verified_transcript' in p for p in posts),
                          'drafts': len(history), 'feedback_records': len(feedback)}}
    # A history update changes this packet even if the metric fingerprint stays the same.
    packet_path = immutable_json(root / 'evidence', packet)
    atomic_json(root / 'latest.json', {'packet': str(packet_path), 'snapshot_fingerprint': fingerprint,
                                     'prepared_at': now()})
    return {'packet': str(packet_path), **packet['summary'], 'warnings': warnings}


def compact(text):
    return re.sub(r'[^\w\u4e00-\u9fff]', '', text.lower())


def grams(text, length=12):
    value = compact(text)
    return {value[i:i + length] for i in range(max(0, len(value) - length + 1))}


def novelty(root, draft_path, plan_path=None):
    packet = read_json(read_json(root / 'latest.json')['packet'])
    draft = Path(draft_path).read_text(encoding='utf-8-sig')
    target = grams(draft)
    corpus = dict(packet['source_texts'])
    if plan_path:
        for span in read_json(plan_path)['source_spans']:
            source = Path(span['path'])
            if not source.is_file() or digest(source.read_bytes()) != span['sha256']:
                raise ValueError('Novelty source changed or is missing: ' + str(source))
            start, end = span['lines']
            lines = source.read_text(encoding='utf-8-sig').splitlines()
            corpus[str(source) + '#' + str(start) + '-' + str(end)] = '\n'.join(lines[start - 1:end])
    for path in (root / 'history/drafts').glob('*.json'):
        record = read_json(path)
        corpus[record['draft_id']] = record['body']
    scores = []
    for label, body in corpus.items():
        source = grams(body)
        overlap = target & source
        scores.append({'source': label, 'draft_ngram_overlap': round(len(overlap) / max(1, len(target)), 4),
                       'shared_12char_examples': sorted(overlap)[:5]})
    scores.sort(key=lambda r: -r['draft_ngram_overlap'])
    return {'status': 'SEMANTIC_REVIEW_REQUIRED', 'draft': str(draft_path),
            'comparisons': len(scores), 'closest': scores[:8],
            'interpretation': 'Character overlap locates reused language. Review information novelty and author voice in context.'}


def register(root, draft_path, plan_path):
    body = Path(draft_path).read_text(encoding='utf-8-sig')
    if not body.strip():
        raise ValueError('Draft is empty')
    plan = read_json(plan_path)
    missing = [key for key in PLAN_FIELDS if key not in plan]
    if missing or plan.get('mode') not in ('remix', 'new_material'):
        raise ValueError('Missing plan fields or unsupported mode: ' + ', '.join(missing))
    for key in ('parent_sources', 'source_spans', 'retained_logic', 'new_information', 'snapshot_fingerprint'):
        if not plan[key]:
            raise ValueError('Empty evidence field: ' + key)
    if not isinstance(plan['source_spans'], list):
        raise ValueError('source_spans must be a list')
    for span in plan['source_spans']:
        source = Path(span['path'])
        if not source.is_file() or digest(source.read_bytes()) != span['sha256']:
            raise ValueError('Draft source changed or is missing: ' + str(source))
        lines = span['lines']
        line_count = len(source.read_text(encoding='utf-8-sig').splitlines())
        if len(lines) != 2 or not 1 <= lines[0] <= lines[1] <= line_count:
            raise ValueError('Invalid source line range')
    draft_id = digest(body.encode('utf-8'))
    record = {'draft_id': draft_id, 'draft_path': str(Path(draft_path).resolve()),
              'body': body, 'status': 'draft', 'plan': plan}
    path = root / 'history/drafts' / (draft_id + '.json')
    if path.exists():
        if read_json(path)['body'] != body:
            raise ValueError('Draft content hash conflict')
    else:
        atomic_json(path, record)
    return {'draft_id': draft_id, 'record': str(path), 'status': 'draft'}


def feedback(root, event_path):
    event = read_json(event_path)
    required = ('draft_id', 'account', 'publication_id', 'published_draft_sha256', 'evidence')
    if any(not event.get(key) for key in required):
        raise ValueError('Feedback must bind a draft, account, publication and published text evidence')
    known = {read_json(p)['draft_id'] for p in (root / 'history/drafts').glob('*.json')}
    if event['draft_id'] not in known:
        raise ValueError('Unknown draft ID')
    existing = [read_json(p) for p in (root / 'history/feedback').glob('*.json')]
    conflicts = [e for e in existing if (e['account'], e['publication_id']) ==
                 (event['account'], event['publication_id']) and
                 (e['draft_id'], e['published_draft_sha256']) !=
                 (event['draft_id'], event['published_draft_sha256'])]
    if conflicts:
        raise ValueError('Publication already linked to a different draft version')
    key = digest(encode([event['account'], event['publication_id']]))
    path = root / 'history/feedback' / (key + '.json')
    if not path.exists():
        atomic_json(path, {field: event[field] for field in required})
    return {'record': str(path), 'status': 'publication_link_recorded'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'novelty', 'register', 'feedback'))
    parser.add_argument('--profile')
    parser.add_argument('--config')
    parser.add_argument('--draft', type=Path)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--event', type=Path)
    args = parser.parse_args()
    config, root = load_config(args)
    if args.command == 'novelty':
        if args.draft is None:
            parser.error('novelty requires --draft')
        result = novelty(root, args.draft, args.plan)
    else:
        with exclusive_lock(root, 'evidence'):
            if args.command == 'prepare':
                result = prepare(config, root)
            elif args.command == 'register':
                if args.draft is None or args.plan is None:
                    parser.error('register requires --draft and --plan')
                result = register(root, args.draft, args.plan)
            else:
                if args.event is None:
                    parser.error('feedback requires --event')
                result = feedback(root, args.event)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
