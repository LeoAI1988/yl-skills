"""Read registered local evidence; build a privacy-safe, repeatable analytics view.

Never fetches a platform, alters a source, or changes captured-at to import time.
Output is staged and validated before atomically replacing individual artifacts.
"""
from __future__ import annotations
import sys
sys.dont_write_bytecode=True
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import re
import importlib.util

CST = timezone(timedelta(hours=8))
ATTR_NOTE = '视频成交为平台短窗口内记录的参考值，不代表累计成交；不能与小店全店已付相加。具体归因窗口长度未确认。'

def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def number(value):
    if value is None or value == '' or isinstance(value, bool):
        return None
    try:
        n = float(value)
        return int(n) if math.isfinite(n) and n.is_integer() else n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None

def iso(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, CST).isoformat()
    return datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone(CST).isoformat()

def percentage(value):
    n = number(value)
    return None if n is None else n * 100

def clean_transcript(value, content_type):
    if content_type == 'image':
        return {'status': 'not_applicable', 'full': '', 'reason': '图文作品，无视频逐字稿'}
    if not value or not value.get('full'):
        return {'status': 'missing', 'full': '', 'reason': '全文待补充'}
    out = {'status': value.get('status') or 'matched', 'full': value['full']}
    op = value.get('opening')
    if op:
        out['opening'] = {k: op.get(k) for k in ['text', 'start', 'end', 'exact', 'label']}
    return out

def raw_metrics(raw, content_type, normalized=None):
    normalized = normalized or {}
    metrics = {
        'views': number(raw.get('readCount', normalized.get('views'))),
        'likes': number(raw.get('likeCount')),
        'comments': number(raw.get('commentCount')),
        'shares': number(raw.get('forwardCount', normalized.get('shares'))),
        'favorites': None,
        'recommendations': number(raw.get('favCount')),
        'follows': number(raw.get('followCount', normalized.get('follows'))),
        'completionPct': percentage(raw['fullPlayRate']) if 'fullPlayRate' in raw else number(normalized.get('completion_pct')),
        'threeSecPct': (100-percentage(raw['fastFlipRate'])) if number(raw.get('fastFlipRate')) is not None else number(normalized.get('three_sec_pct')),
        'watchSeconds': number(raw.get('avgPlayTimeSec', normalized.get('watch_seconds'))),
        'durationSeconds': number(raw.get('len', normalized.get('duration_seconds'))),
        'fastFlipPct': percentage(raw.get('fastFlipRate')),
        'forwardTimeline': number(raw.get('forwardSnsCount')),
        'forwardChat': number(raw.get('forwardAllChatCount')),
        'ringSetCount': number(raw.get('ringsetCount')),
        'snsCoverCount': number(raw.get('snscoverCount')),
        'statusReferenceCount': number(raw.get('statusrefCount')),
        'forwardAggregationCount': number(raw.get('forwardAggregationCount')),
        'yesterdayViews': number(raw.get('yesterdayReadCount')),
        'wecomLinkClicks': number(raw.get('wecomLinkClickCount')),
        'wecomContactAdds': number(raw.get('wecomContactAddCount')),
        'wecomLinkClickUv': number(raw.get('wecomLinkClickUv')),
        'wecomContactAddUv': number(raw.get('wecomContactAddUv')),
    }
    if content_type != 'video':
        for k in ['completionPct', 'threeSecPct', 'watchSeconds', 'durationSeconds', 'fastFlipPct']:
            metrics[k] = None
    return metrics

def checked_time(value, label):
    if not isinstance(value, str):
        raise ValueError(f'{label}: timestamp must be a timezone-aware string')
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None or dt > datetime.now(CST) + timedelta(minutes=5):
        raise ValueError(f'{label}: missing timezone or future capture time')
    return dt.astimezone(CST).isoformat()

def reject_private(value):
    forbidden = {'buyer', 'buyer_nick', 'buyerInfo', 'acceptInfo', 'phone', 'address', 'recipient', 'customer_note',
                 'customerNotes', 'openid', 'aid', 'cookie', 'cookies', 'authorization', 'access_token', 'token'}
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in {x.lower() for x in forbidden}:
                raise ValueError('Capture contains prohibited customer or credential fields')
            reject_private(child)
    elif isinstance(value, list):
        for child in value:
            reject_private(child)

def archive_capture(root, config, job_dir):
    """Validate before storing immutable evidence. Orphans never enter the active registry."""
    job = job_dir.resolve(strict=True)
    result_path = job/'result.json'
    if result_path.resolve(strict=True).parent != job or result_path.is_symlink():
        raise ValueError('Invalid capture result path')
    result = read_json(result_path)
    if result.get('kind') != 'capture' or result.get('account') != config['account']:
        raise ValueError('Capture kind or account does not match this workbench')
    if result.get('status') not in ('complete', 'partial'):
        raise ValueError('Capture was not completed or partial')
    completed_at = checked_time(result.get('capturedAt'), 'result.capturedAt')
    evidence = result.get('evidence') or {}
    if evidence.get('readOnly') is not True or not str(evidence.get('source') or '').strip():
        raise ValueError('Capture must identify the actual read-only collection method')
    evidence_at = checked_time(evidence.get('completedAt'), 'evidence.completedAt')
    if datetime.fromisoformat(evidence_at) > datetime.fromisoformat(completed_at) + timedelta(minutes=5):
        raise ValueError('Evidence completion is later than the result')
    coverage = result.get('coverage')
    if not isinstance(coverage, list):
        raise ValueError('Capture coverage is required')
    files = result.get('files')
    if not isinstance(files, dict) or not files.get('posts'):
        raise ValueError('Nonempty posts evidence is required')
    allowed = {'posts', 'accountDaily', 'orders', 'attribution'}
    if set(files)-allowed:
        raise ValueError('Unknown capture layer')
    payloads, metadata = {}, {}
    for layer, relative in files.items():
        if not isinstance(relative, str) or not relative or '\\' in relative or Path(relative).is_absolute() or '..' in Path(relative).parts or ':' in relative:
            raise ValueError('Evidence files must use job-relative paths')
        file = (job/relative).resolve(strict=True)
        if not file.is_file() or not file.is_relative_to(job) or (job/relative).is_symlink() or file.stat().st_size > 64*1024*1024:
            raise ValueError('Evidence path is outside the job or invalid')
        doc = read_json(file)
        reject_private(doc)
        root_fields={'posts':{'account','captured_at','total','posts','source'},
                     'orders':{'account','captured_at','total_orders','orders','source'},
                     'accountDaily':{'account','captured_at','range','fans_trend','new_post_total_data','source'},
                     'attribution':{'account','captured_at','rows','source'}}
        if not isinstance(doc,dict) or set(doc)-root_fields[layer]:
            raise ValueError('Capture must contain only the documented business fields')
        if doc.get('account') != config['account']:
            raise ValueError(f'{layer}: evidence account mismatch')
        captured_at = checked_time(doc.get('captured_at'), layer+'.captured_at')
        if datetime.fromisoformat(captured_at) > datetime.fromisoformat(completed_at) + timedelta(minutes=5):
            raise ValueError('Layer capture is later than the result')
        if abs((datetime.fromisoformat(completed_at)-datetime.fromisoformat(captured_at)).total_seconds()) > 24*3600:
            raise ValueError('New capture evidence must be from this collection, not relabelled old files')
        layer_coverage = [c for c in coverage if c.get('layer') == layer]
        if len(layer_coverage) != 1 or layer_coverage[0].get('status') not in ('complete','partial') or not str(layer_coverage[0].get('reason') or '').strip():
            raise ValueError(f'{layer}: explicit coverage and reason required')
        c = layer_coverage[0]
        if type(c.get('checkedCount')) is not int or c['checkedCount'] < 0 or (c.get('expectedCount') is not None and (type(c['expectedCount']) is not int or c['expectedCount'] < 0)):
            raise ValueError('Coverage counts must be nonnegative integers or unknown expectedCount')
        if layer == 'posts':
            rows = doc.get('posts')
            if not isinstance(rows, list) or not rows:
                raise ValueError('Empty post capture cannot replace current data')
            ids = []
            for row in rows:
                allowed_post={'objectId','createTime','visibleType','status','title','shortTitle','len','mediaType','readCount','likeCount','commentCount',
                              'forwardCount','favCount','fullPlayRate','avgPlayTimeSec','fastFlipRate','followCount','forwardSnsCount','forwardAllChatCount',
                              'ringsetCount','snscoverCount','statusrefCount','forwardAggregationCount','yesterdayReadCount','wecomLinkClickCount',
                              'wecomContactAddCount','wecomLinkClickUv','wecomContactAddUv'}
                if not isinstance(row,dict) or set(row)-allowed_post or any(isinstance(v,(dict,list)) for v in row.values()):
                    raise ValueError('Post evidence contains undocumented or nested fields')
                pid = row.get('objectId')
                if not isinstance(pid, str) or not re.fullmatch(r'[0-9]+', pid):
                    raise ValueError('Publication IDs must be exact decimal strings')
                ids.append(pid)
                stamp = number(row.get('createTime'))
                if stamp is None or stamp <= 0 or stamp > datetime.fromisoformat(captured_at).timestamp()+900:
                    raise ValueError('Invalid publication time')
                if row.get('mediaType') not in (2,4,None) or row.get('visibleType') not in (1,3,None):
                    raise ValueError('Unknown content/visibility value: use null until verified')
                for key in ['readCount','likeCount','commentCount','forwardCount','favCount','avgPlayTimeSec','followCount','len']:
                    if row.get(key) is not None and (number(row[key]) is None or number(row[key]) < 0):
                        raise ValueError('Invalid nonnegative post metric')
                for key in ['fullPlayRate','fastFlipRate']:
                    if row.get(key) is not None and (number(row[key]) is None or not 0 <= number(row[key]) <= 1):
                        raise ValueError('Rate metrics must be fractions in [0,1]')
            if len(set(ids)) != len(ids):
                raise ValueError('Duplicate publication IDs in capture')
            if c.get('checkedCount') != len(rows):
                raise ValueError('Post coverage count does not match evidence')
            complete = c['status'] == 'complete'
            if complete and not (type(c.get('expectedCount')) is int and c['expectedCount'] == len(rows) == doc.get('total')
                                 and evidence.get('paginationExhausted') is True and evidence.get('includesHidden') is True):
                raise ValueError('Complete capture requires exact counts, exhausted pagination and hidden works')
            if result['status'] == 'complete' and not complete:
                raise ValueError('Partial post coverage cannot be declared complete')
        elif layer == 'orders':
            rows = doc.get('orders')
            if not isinstance(rows, list):
                raise ValueError('orders must be a list')
            order_ids = []
            for order in rows:
                allowed_order={'order_id','status','status_str','is_pay_done','create_time','create_date','pay_time','pay_date','pay_ts',
                               'order_price_fen','pay_price_fen','merchant_receive_fen','refund_fen','refund_count','products'}
                if not isinstance(order,dict) or set(order)-allowed_order:
                    raise ValueError('Order evidence contains undocumented customer fields')
                if not isinstance(order.get('order_id'), str) or not order['order_id']:
                    raise ValueError('Order IDs must be strings')
                order_ids.append(order['order_id'])
                if not isinstance(order.get('products'), list) or not order['products']:
                    raise ValueError('Order products are required')
                if any(not isinstance(p.get('product_id'),str) or not p['product_id'] for p in order['products']):
                    raise ValueError('Product IDs must be strings')
                if any(set(p)-{'title','product_id','sku','cnt','price_fen','sale_channel','account_name','content_name'} for p in order['products']):
                    raise ValueError('Order product evidence contains undocumented fields')
                if not isinstance(order.get('is_pay_done'),bool):
                    raise ValueError('Order payment status must be an explicit boolean')
                if number(order.get('pay_price_fen')) is None or number(order['pay_price_fen']) < 0:
                    raise ValueError('Order amount must be explicit nonnegative fen')
            if len(order_ids) != len(set(order_ids)) or c.get('checkedCount') != len(rows):
                raise ValueError('Order identity or coverage mismatch')
        elif layer == 'accountDaily':
            rng = doc.get('range') or {}
            days = (date.fromisoformat(rng['end'])-date.fromisoformat(rng['start'])).days+1
            if days < 1 or days > 3660:
                raise ValueError('Invalid account daily date range')
            for key in ['fans_trend','new_post_total_data']:
                if doc.get(key, {}).get('errCode') != 0 or not isinstance(doc[key].get('data'),dict):
                    raise ValueError('Account daily layer did not return successful data')
            for values in [doc['fans_trend']['data'].get('total'),doc['new_post_total_data']['data'].get('totalData',{}).get('browse')]:
                if not isinstance(values,list) or len(values) != days:
                    raise ValueError('Account daily arrays must align with the full date range')
            if c.get('checkedCount') != days:
                raise ValueError('Account daily coverage mismatch')
        elif layer == 'attribution':
            rows = doc.get('rows')
            if not isinstance(rows,list) or c.get('checkedCount') != len(rows):
                raise ValueError('Attribution coverage mismatch')
            for row in rows:
                if not isinstance(row.get('publication_id'),str) or not isinstance(row.get('product_id'),str):
                    raise ValueError('Attribution needs verified string publication and product IDs')
                if row.get('scope') != 'platform_window_reference' or not row.get('evidence'):
                    raise ValueError('Attribution scope and evidence required')
                if any(number(row.get(k)) is None or number(row[k]) < 0 for k in ['orders','amount']):
                    raise ValueError('Attribution requires explicit nonnegative values')
        if c['status'] == 'complete' and c.get('expectedCount') != c.get('checkedCount'):
            raise ValueError('Complete coverage requires checked and expected counts to match')
        if result['status'] == 'complete' and c['status'] != 'complete':
            raise ValueError('A partial included layer cannot be declared complete')
        payloads[layer] = file.read_bytes()
        metadata[layer] = {'file': layer+'.json', 'capturedAt': captured_at, 'sha256': hashlib.sha256(payloads[layer]).hexdigest()}
    identity = {'account': config['account'], 'completedAt': completed_at, 'files': metadata}
    capture_id = 'capture-'+hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
    manifest = {'id': capture_id, 'account':config['account'], 'capturedAt':completed_at, 'status':result['status'],
                'coverage':coverage, 'evidence':{k:evidence.get(k) for k in ['source','readOnly','completedAt','paginationExhausted','includesHidden']}, 'files':metadata}
    dest = root/'data'/'captures'/capture_id
    if dest.exists():
        if read_json(dest/'manifest.json') != manifest:
            raise ValueError('Immutable capture identity conflict')
    else:
        dest.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.capture-stage-',dir=dest.parent) as tmp:
            stage=Path(tmp)
            for layer,blob in payloads.items():
                (stage/metadata[layer]['file']).write_bytes(blob)
            (stage/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
            # Move a fully validated immutable directory; abandoned imports are not registered.
            os.replace(stage,dest)
    return capture_id

def build(root, config, capture_ids=None):
    if not capture_ids:
        now=datetime.now(CST).isoformat()
        summary={'account':config['account'],'postCount':0,'latestPostCount':0,'latestCapturedAt':None,'latestCaptureStatus':'not_available','liveRefreshAvailable':False}
        result={'schemaVersion':1,'importedAt':now,'captures':[],'coverage':[{'item':'作品采集','status':'not_available','reason':'尚未采集；不会自动创建平台任务。'}],'posts':[],'products':[],'attribution':[],'summary':summary,'accountDaily':[]}
        return result,{}, {'importedAt':now,'captureIds':[]}
    docs={}
    events = []
    for capture_id in capture_ids or []:
        if not re.fullmatch(r'capture-[a-f0-9]{24}', capture_id):
            raise ValueError('Invalid registered capture ID')
        folder=root/'data'/'captures'/capture_id
        entry=read_json(folder/'manifest.json')
        layers={}
        for layer,meta in entry['files'].items():
            file=folder/meta['file']
            if hashlib.sha256(file.read_bytes()).hexdigest() != meta['sha256']:
                raise ValueError('Immutable captured evidence has changed')
            layers[layer]=read_json(file)
        events.append({'manifest':entry,'layers':layers})
    post_sources = [{'id':e['manifest']['id'],'document':e['layers']['posts'],
                     'status':next(c['status'] for c in e['manifest']['coverage'] if c['layer']=='posts'),
                     'coverage':next(c for c in e['manifest']['coverage'] if c['layer']=='posts')} for e in events]
    post_sources.sort(key=lambda s:iso(s['document']['captured_at']))
    latest=post_sources[-1]['document']
    # Optional layers each retain their own collection date. Partial updates merge by identity/date.
    order_sources=[e['layers']['orders'] for e in events if 'orders' in e['layers']]
    order_sources.sort(key=lambda d:iso(d['captured_at']))
    order_rows={}
    for document in order_sources:
        for row in document['orders']:
            order_rows[str(row['order_id'])]={**row,'captured_at':iso(document['captured_at'])}
    docs['orders']={**(order_sources[-1] if order_sources else {'captured_at':None}),'orders':list(order_rows.values())}
    account_sources=[e['layers']['accountDaily'] for e in events if 'accountDaily' in e['layers']]
    account_sources.sort(key=lambda d:iso(d['captured_at']))
    latest_at = iso(latest['captured_at'])
    import_at = datetime.now(CST).isoformat()
    posts = {}
    conflicts = []

    def add_post(pid, title, published, visibility, content_type, metrics, captured, source_id, long_title=''):
        if not isinstance(pid, str) or not pid:
            raise ValueError('Platform IDs must be nonempty strings')
        snapshot = {'captureId': source_id, 'capturedAt': captured, 'metricScope': 'lifetime', 'visibility': visibility, 'metrics': metrics}
        if pid in posts:
            p = posts[pid]
            if p['publishedAt'] != published:
                conflicts.append({'publication_id': pid, 'field': 'publishedAt', 'reason': '采集之间发布时间不一致，保留原始观察'})
            if any(s['capturedAt']==captured and s['metrics']==metrics and s['visibility']==visibility for s in p['snapshots']):
                return
            p['snapshots'].append(snapshot)
            if captured < p['latestCapturedAt']:
                return
        else:
            p = posts[pid] = {'id': pid, 'publication_id': pid, 'origin': 'historical', 'snapshots': [], 'topic': '待归类'}
            p['snapshots'].append(snapshot)
        p.update(title=title, description=long_title, publishedAt=published, visibility=visibility,
                 contentType=content_type, contentOrigin='unknown', latestCapturedAt=captured, metrics=metrics)

    latest_ids = set()
    for source in post_sources:
        source_ids=set()
        captured=iso(source['document']['captured_at'])
        for raw in source['document']['posts']:
            pid = raw['objectId']
            if not isinstance(pid, str):
                raise ValueError('Latest publication ID was not preserved as string')
            if pid in source_ids:
                raise ValueError('Duplicate publication in capture')
            source_ids.add(pid)
            if pid in posts and any(s['capturedAt']==captured and s['metrics'] != raw_metrics(raw,{4:'video',2:'image'}.get(raw.get('mediaType'),'unknown')) for s in posts[pid]['snapshots']):
                raise ValueError('Conflicting post metrics at the same capture timestamp')
            ct = {4: 'video', 2: 'image'}.get(raw.get('mediaType'), 'unknown')
            add_post(pid, raw.get('shortTitle') or raw.get('title') or '未命名作品', iso(raw['createTime']),
                     {1: 'public', 3: 'hidden'}.get(raw.get('visibleType'), 'unknown'), ct,
                     raw_metrics(raw, ct), captured, source['id'], raw.get('title', ''))
        latest_ids=source_ids
    for p in posts.values():
        p['captureStatus'] = 'latest' if p['id'] in latest_ids else 'not_in_latest_capture'
        p['captureNote'] = '' if p['id'] in latest_ids else '后一次采集中未返回；保留此前记录，当前状态待核。'
        p['transcript'] = clean_transcript(p.get('transcript'), p['contentType'])
        p['snapshots'].sort(key=lambda s: s['capturedAt'])

    # Exclude customer names, contacts, addresses, raw orders, and notes from every generated file.
    product_map = {}
    orders = []
    multi_product = 0
    for order in docs['orders']['orders']:
        items = order.get('products') or []
        if len(items) != 1:
            multi_product += 1
            continue
        item = items[0]
        pid = str(item['product_id'])
        product_map[pid] = {'product_id': pid, 'label': item.get('title') or pid}
        amount_fen = number(order.get('pay_price_fen'))
        if amount_fen is None:
            raise ValueError('Order amount unavailable; refusing to replace valid history')
        stamp = iso(order['pay_ts']) if order.get('pay_ts') else str(order.get('create_time') or '')
        orders.append({'order_id': str(order['order_id']), 'product_id': pid, 'product': product_map[pid]['label'],
                       'time': stamp, 'paid_at': stamp if order.get('pay_ts') else None, 'amount': amount_fen / 100,
                       'paid': bool(order.get('is_pay_done')), 'status': order.get('status_str') or '未知',
                       'channel': item.get('sale_channel') or '未标注', 'refund_amount': number(order['refund_fen'])/100 if number(order.get('refund_fen')) is not None else None,
                       'capturedAt':order.get('captured_at',(iso(docs['orders']['captured_at']) if docs['orders']['captured_at'] else None))})
    if len({o['order_id'] for o in orders}) != len(orders):
        raise ValueError('Duplicate order IDs')

    attribution=[]
    unmatched=[]
    attribution_map={}
    for event in sorted(events,key=lambda e:e['manifest']['capturedAt']):
        document=event['layers'].get('attribution')
        if not document:
            continue
        for row in document['rows']:
            pid=row['publication_id']; product_id=row['product_id']
            if pid not in posts:
                unmatched.append({'publication_id':pid,'reason':'归因作品未在已验证作品记录中'})
                continue
            if product_id not in product_map:
                product_map[product_id]={'product_id':product_id,'label':row.get('product') or product_id}
            value={'publication_id':pid,'product_id':product_id,'product':product_map[product_id]['label'],
                   'orders':row['orders'],'amount':row['amount'],'scope':'platform_window_reference','isReference':True,
                   'note':ATTR_NOTE,'capturedAt':iso(document['captured_at']),'observedDate':iso(document['captured_at'])[:10],
                   'evidence':row['evidence']}
            key=(pid,product_id)
            old=attribution_map.get(key)
            if not old or value['observedDate'] >= old.get('observedDate',''):
                attribution_map[key]=value
    attribution=list(attribution_map.values())
    for p in posts.values():
        p['attribution'] = [a for a in attribution if a['publication_id'] == p['id']]

    account = account_sources[-1] if account_sources else {'captured_at':None}
    a_from=min((d['range']['start'] for d in account_sources),default=min(p['publishedAt'][:10] for p in posts.values()))
    a_to=max((d['range']['end'] for d in account_sources),default=latest_at[:10])
    daily_by_date={}
    account_map = {'views': 'browse', 'likes': 'like', 'comments': 'comment', 'shares': 'forward', 'recommendations': 'fav', 'follows': 'follow',
                   'ringSetCount': 'ringset', 'snsCoverCount': 'snscover', 'statusReferenceCount': 'statusref', 'forwardAggregationCount': 'forwardAggregation'}
    def index_value(values, index):
        return number(values[index]) if isinstance(values, list) and index < len(values) else None
    for document in account_sources:
        a_total=document['new_post_total_data']['data']['totalData']
        fans=document['fans_trend']['data']
        start=document['range']['start']; end=document['range']['end']
        days=(date.fromisoformat(end)-date.fromisoformat(start)).days+1
        for i in range(days):
            row = {'date': (date.fromisoformat(start) + timedelta(days=i)).isoformat(), 'capturedAt': iso(document['captured_at']), 'metricScope': 'account_daily'}
            row.update({dest: index_value(a_total.get(src), i) for dest, src in account_map.items()})
            row.update({dest: index_value(fans.get(src), i) for dest, src in {'fansAdded': 'add', 'fansLost': 'reduce', 'fansNet': 'netAdd', 'fansTotal': 'total'}.items()})
            daily_by_date[row['date']]=row
    daily=[]
    first_day=date.fromisoformat(a_from)
    for i in range((date.fromisoformat(a_to)-first_day).days+1):
        day=(first_day+timedelta(days=i)).isoformat()
        missing={'date':day,'capturedAt':None,'metricScope':'account_daily',
                 **{key:None for key in [*account_map,'fansAdded','fansLost','fansNet','fansTotal']}}
        daily.append(daily_by_date.get(day,missing))

    current = [p for p in posts.values() if p['captureStatus'] == 'latest']
    paid = [o for o in orders if o['paid']]
    platform_paid = [o for o in paid if not str(o['channel']).startswith('私域')]
    coverage = [
        {'item': '历史作品', 'status': 'partial', 'reason': f'{len(post_sources)} 个采集批次按发布 ID 合并为 {len(posts)} 条；最近采集 {len(current)} 条，另有 {len(posts)-len(current)} 条仅留历史观察，当前状态待核。'},
        {'item': '最新平台数据', 'status': post_sources[-1]['status'], 'reason': f'作品最近采集于 {latest_at}。'+(post_sources[-1]['coverage']['reason'] if post_sources[-1]['coverage'] else '此前本地快照；重新载入本地资料不会更新平台数据。')},
        {'item': '账号每日数据', 'status': 'complete' if all(row['views'] is not None and row['fansTotal'] is not None for row in daily) else 'partial', 'reason': f'{a_from} 至 {a_to}，每日实际流量与作品累计量分别保存；采集于 {((iso(account['captured_at']) if account['captured_at'] else None) if account['captured_at'] else '未采集')}。'},
        {'item': '逐条留存与受众', 'status': 'partial', 'reason': '已有完播、三秒与均观看；未取得每条留存曲线、曝光及完整受众细分，未知保留空值。'},
        {'item': '商品成交归因', 'status': 'partial', 'reason': ATTR_NOTE + f'已取得 {len(attribution)} 条视频参考归因。'},
        {'item': '小店成交采集', 'status': 'partial', 'reason': f'最近取得订单于 {((iso(docs['orders']['captured_at']) if docs['orders']['captured_at'] else None) if docs['orders']['captured_at'] else '未采集')}；订单与作品分别保留自己的采集时间。'},
        {'item': '正文', 'status': 'partial', 'reason': f'{sum(bool(p["transcript"].get("full")) for p in posts.values())} 条有全文；其余保持待补充或图文不适用。'},
    ]
    if multi_product:
        coverage.append({'item': '多商品订单', 'status': 'partial', 'reason': f'{multi_product} 条待分摊，未计入统计。'})
    if unmatched:
        coverage.append({'item': '归因身份', 'status': 'partial', 'reason': f'{len(unmatched)} 条无法唯一对应，未计入作品归因。'})
    captures=[]
    for event in events:
        entry=event['manifest']
        for layer,meta in entry['files'].items():
            cov=next(c for c in entry['coverage'] if c['layer']==layer)
            captures.append({'id':entry['id'],'layer':layer,'capturedAt':meta['capturedAt'],'count':cov['checkedCount'],
                             'status':cov['status'],'reportedCount':cov.get('expectedCount')})
    def known_sum(values):
        known=[v for v in values if v is not None]
        return sum(known) if known else None
    summary = {
        'account': config['account'], 'postCount': len(posts), 'latestPostCount': len(current), 'historicalOnlyCount': len(posts)-len(current),
        'videoCount': sum(p['contentType']=='video' for p in posts.values()), 'imageCount': sum(p['contentType']=='image' for p in posts.values()),
        'hiddenCount': sum(p['visibility']=='hidden' for p in posts.values()), 'latestHiddenCount': sum(p['visibility']=='hidden' for p in current),
        'latestCapturedAt': latest_at, 'views': known_sum(p['metrics']['views'] for p in current),
        'follows': known_sum(p['metrics']['follows'] for p in current),
        'metricScope': '最近同批次作品累计数据；未返回历史作品不计入合计',
        'accountDailyViews': sum(d['views'] for d in daily if d['views'] is not None) if account_sources else None, 'accountDailyFrom': a_from, 'accountDailyTo': a_to,
        'accountFollowers': daily[-1]['fansTotal'], 'paidOrders': len(platform_paid) if order_sources else None,
        'paidAmount': float(sum((Decimal(str(o['amount'])) for o in platform_paid), Decimal(0))) if order_sources else None,
        'privateAmount': float(sum((Decimal(str(o['amount'])) for o in paid if str(o['channel']).startswith('私域')), Decimal(0))),
        'salesCapturedAt': (iso(docs['orders']['captured_at']) if docs['orders']['captured_at'] else None), 'attributedVideoCount': len(attribution),
        'attributionNote': ATTR_NOTE, 'freshness': 'captured' if events else 'historical', 'liveRefreshAvailable': False,
        'latestCaptureStatus':post_sources[-1]['status'], 'accountDailyCapturedAt':(iso(account['captured_at']) if account['captured_at'] else None),
    }
    result = {'schemaVersion': 1, 'importedAt': import_at, 'captures': captures, 'coverage': coverage,
              'posts': sorted(posts.values(), key=lambda p: p['publishedAt'], reverse=True), 'products': list(product_map.values()),
              'attribution': attribution, 'summary': summary, 'accountDaily': daily,
              'attributionReferences': {'products': [], 'trade': {}},
              'conflicts': conflicts, 'unmatchedAttribution': unmatched,
              'metricNotes': {'recommendations': '原字段 favCount，沿用既有视频号推荐口径；未另取得收藏数。', 'threeSecPct': '由 100% 减快速划走率得到，保留项目既有口径。'}}

    review_posts = []
    for p in current:
        age_hours = (datetime.fromisoformat(latest_at)-datetime.fromisoformat(p['publishedAt'])).total_seconds()/3600
        m = p['metrics']
        review_posts.append({'publication_id': p['id'], 'title': p['title'], 'date': p['publishedAt'][:10], 'published_at': p['publishedAt'],
                             'public': p['visibility']=='public', 'mature': age_hours >= 48, 'content_type': p['contentType'],
                             'views': m['views'], 'completion_pct': m['completionPct'], 'three_sec_pct': m['threeSecPct'],
                             'watch_seconds': m['watchSeconds'], 'duration_seconds': m['durationSeconds'],
                             'follows': m['follows'], 'shares': m['shares'], 'topic': p['topic']})
    review_to=latest_at[:10]
    review_from=min(p['publishedAt'][:10] for p in posts.values())
    first=date.fromisoformat(review_from);span=(date.fromisoformat(review_to)-first).days+1
    segments=[]
    for i in range(min(3,span)):
        lo=first+timedelta(days=i*span//min(3,span));hi=first+timedelta(days=(i+1)*span//min(3,span)-1)
        segments.append([lo.isoformat(),hi.isoformat()])
    missing_calendar=[]
    if post_sources[-1]['status'] != 'complete':
        start=date.fromisoformat(review_from)
        missing_calendar=[(start+timedelta(days=i)).isoformat() for i in range((date.fromisoformat(review_to)-start).days+1)]
    eligible_ids = {p['publication_id'] for p in review_posts if p['public'] and p['mature'] and review_from <= p['date'] <= review_to}
    review = {
        'meta': {'account': config['account'], 'from': review_from, 'to': review_to, 'captured_at': latest_at, 'generated_at': import_at,
                 'refresh_note': f'基于 {latest_at[:10]} 已采集资料重新整理。全部历史作品和隐藏作品在“数据跟踪”查看；效果榜按最近采集的公开成熟作品计算。每日真实流量与各条累计播放不混用。',
                 'include_customer_details': False, 'maturity_hours': 48, 'hit_threshold': 30000,
                 'calendar_missing_dates':missing_calendar,
                 'calendar_scope':'all_known_publications',
                 'segments': segments,
                 'account_views': sum(p['metrics']['views'] for p in current if p['visibility']=='public' and p['metrics']['views'] is not None),
                 'account_followers': daily[-1]['fansTotal'], 'account_captured_at': f'截至 {a_to}；采集于 {((iso(account['captured_at']) if account['captured_at'] else None) if account['captured_at'] else '未采集')}',
                 'attribution_note': ATTR_NOTE, 'orders_from': a_from, 'orders_to': a_to,
                 'sales_chart_product_ids': list(product_map)[:2]},
        'posts': review_posts, 'products': list(product_map.values()),
        'calendar_posts': [{k:p[k] for k in ['id','publishedAt','contentType','visibility','captureStatus','metrics']} for p in posts.values()],
        'orders': [o for o in orders if a_from <= str(o.get('paid_at') or o['time'])[:10] <= a_to],
        'attribution': [a for a in attribution if a['publication_id'] in eligible_ids],
        'transcripts': {p['id']: p['transcript'] for p in current},
        'analysis': ['本次由已保存采集生成；发布时间之后的累计观察时长不同，阶段变化不能直接证明内容效果的因果变化。', ATTR_NOTE],
        'coverage': coverage,
    }
    manifest={'importedAt':import_at,'captureIds':capture_ids or []}
    return result, review, manifest



def render_local_review(config, review, analytics, output):
    """Reuse shared rankings and 14-chapter design; calendar covers all known publications.

    The shared renderer intentionally analyzes public mature posts. Its calendar uses
    that same public filter, so this account-level workbench supplies a separate local
    calendar, without changing the shared Skill or expanding the effect-ranking sample.
    """
    spec=importlib.util.spec_from_file_location('yl_workbench_shared_dashboard',config['dashboardScript'])
    dashboard=importlib.util.module_from_spec(spec);spec.loader.exec_module(dashboard)
    stats=dashboard.summarize(review)
    start=date.fromisoformat(review['meta']['from']);end=date.fromisoformat(review['meta']['to'])
    latest=analytics['summary']['latestCapturedAt']
    full_latest=analytics['summary']['latestCaptureStatus']=='complete'
    calendar=[]
    for offset in range((end-start).days+1):
        day=(start+timedelta(days=offset)).isoformat()
        group=[p for p in review['calendar_posts'] if p['publishedAt'][:10]==day]
        historical=any(p['captureStatus']!='latest' for p in group)
        partial=not full_latest or historical or day==latest[:10]
        count=len(group)
        videos=[p for p in group if p['contentType']=='video']
        images=[p for p in group if p['contentType']=='image']
        same_capture=all(p['captureStatus']=='latest' and p['metrics']['views'] is not None for p in videos)
        calendar.append({'date':day,'count':count if count or not partial else None,'known_count':count,
                         'videos':len(videos) if count or not partial else None,'images':len(images) if count or not partial else None,
                         'unknown':len(group)-len(videos)-len(images) if count or not partial else None,
                         'views':sum(p['metrics']['views'] for p in videos) if same_capture and not partial else None,
                         'hidden':sum(p['visibility']=='hidden' for p in group),'historical':historical,'covered':not partial,
                         'publication_ids':[p['id'] for p in group]})
    stats['daily']=calendar
    stats['active_days']=sum(r['known_count']>0 for r in calendar)
    stats['zero_dates']=[r['date'] for r in calendar if r['covered'] and r['count']==0]
    stats['missing_days']=sum(not r['covered'] for r in calendar)
    stats['calendar_scope']='全部已采集作品，含隐藏、旧观察和未满成熟期作品；效果榜仍只用最近采集的公开成熟作品'
    stats['calendar_known_publications']=sum(r['known_count'] for r in calendar)
    parts=['<h2 id="s四">四、每日发布与播放</h2>']
    parts.append('<div class="note">发布节奏统计全部已采集作品，包含隐藏作品、历史记录和未满成熟期作品。仅留旧观察或本轮覆盖不完整的日期显示已知条数并标待核；不能据此判断停更。效果排行仍只统计最近采集的公开成熟作品。</div>')
    cards=[('自然日',len(calendar)),('已知有发布',stats['active_days']),('已核零发布',len(stats['zero_dates'])),('覆盖待核',stats['missing_days'])]
    parts.append('<div class="cadence-summary">'+''.join(f'<div><small>{label}</small><b>{value}</b></div>' for label,value in cards)+'</div>')
    parts.append('<h3>逐日发布格 · 包含全部已采集作品</h3><div class="calendar">')
    for row in calendar:
        css='missing' if not row['covered'] else 'zero' if row['count']==0 else 'published'
        value=(f'已知 {row["known_count"]} 条' if row['known_count'] else '待核') if not row['covered'] else f'{row["count"]} 条'
        detail=(f'视频 {row["videos"]} / 图文 {row["images"]}'+(f' · 隐藏 {row["hidden"]}' if row['hidden'] else '')) if row['known_count'] else ('未记录发布' if row['covered'] else '采集缺口')
        if not row['covered'] and row['known_count']:
            detail+=' · 覆盖待核'
        parts.append(f'<div class="day {css}" title="{row["date"]}"><small>{row["date"][5:]}</small><b>{value}</b><small>{detail}</small></div>')
    parts.append('</div><div class="note">已核零发布日期：'+('、'.join(d[5:] for d in stats['zero_dates']) or '无')+'。仅覆盖完整且全部已采集记录均未发现发布时记 0；采集当日只观察到采集时刻，未覆盖日期不补零。</div>')
    width=1260;n=len(calendar);step=width/max(n,1)
    maxn=max((r['known_count'] for r in calendar),default=1) or 1
    maxv=max((r['views'] or 0 for r in calendar),default=1) or 1
    parts.append('<h3>已知发布数量与作品累计播放</h3><div class="chart"><svg viewBox="0 0 1320 290" role="img" aria-label="全部已采集作品的连续自然日发布节奏">')
    points=[]
    for i,row in enumerate(calendar):
        x=40+i*step;hv=(row['videos'] or 0)/maxn*180;hi=(row['images'] or 0)/maxn*180
        parts.append(f'<rect x="{x:.1f}" y="{230-hv:.1f}" width="{step*.62:.1f}" height="{hv:.1f}" fill="#ffd400"><title>{row["date"]} 已知视频 {row["videos"]}，图文 {row["images"]}</title></rect>')
        parts.append(f'<rect x="{x:.1f}" y="{230-hv-hi:.1f}" width="{step*.62:.1f}" height="{hi:.1f}" fill="#9a85ef"/>')
        if row['covered'] and row['count']==0:
            parts.append(f'<circle cx="{x:.1f}" cy="230" r="3" fill="#ff6b72"/><text x="{x:.1f}" y="220" font-size="10" fill="#ff6b72">0</text>')
        if row['views'] is not None:
            points.append(f'{x:.1f},{230-row["views"]/maxv*180:.1f}')
        elif points:
            parts.append('<polyline points="'+' '.join(points)+'" fill="none" stroke="#4aa8ff" stroke-width="2"/>');points=[]
        if i%7==0 or i==n-1:
            parts.append(f'<text x="{x:.1f}" y="255" font-size="11" fill="#9aa3ad">{row["date"][5:]}</text>')
    parts.append('<polyline points="'+' '.join(points)+'" fill="none" stroke="#4aa8ff" stroke-width="2"/></svg></div>')
    parts.append('<div class="note">黄柱＝已知视频，紫柱＝已知图文，包含隐藏作品。蓝线仅显示同一最近采集批次且当日覆盖完整的视频累计播放；旧观察和缺口断线。蓝线不是当天新增播放，账号每日真实流量请在数据跟踪查看。</div>')
    parts.append('<details><summary>逐日明细（全部已采集作品）</summary><div class="table-wrap"><table><thead><tr><th>日期</th><th>已知发布</th><th>视频</th><th>图文</th><th>隐藏</th><th>覆盖</th></tr></thead><tbody>')
    for row in calendar:
        count=str(row['known_count']) if row['known_count'] or row['covered'] else '待核'
        cells=[row['date'],'<strong class="key">'+count+'</strong>',str(row['videos']) if row['videos'] is not None else '—',str(row['images']) if row['images'] is not None else '—',str(row['hidden']) if row['known_count'] or row['covered'] else '—','本次覆盖' if row['covered'] else '覆盖待核']
        parts.append('<tr>'+''.join('<td>'+v+'</td>' for v in cells)+'</tr>')
    parts.append('</tbody></table></div></details>')
    # The shared two-product comparison needs two actual products. Empty installs
    # and one-product accounts show the missing comparison, never synthetic goods.
    if len(review['meta'].get('sales_chart_product_ids',[])) < 2:
        dashboard.sales_chart=lambda *_: '<div class="note">尚未取得两个可对比商品的成交数据；不生成双商品比较图。</div>'
    html=dashboard.render(review,stats)
    html,replaced=re.subn(r'<h2 id="s四">.*?(?=<h2 id="s五">)',lambda _:''.join(parts),html,count=1,flags=re.S)
    if replaced != 1:
        raise ValueError('Shared dashboard chapter boundary changed; local calendar was not installed')
    output.write_text(html,encoding='utf8')
    output.with_suffix('.stats.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--ingest', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if root.is_relative_to(Path(__file__).resolve().parents[3]):
        raise ValueError('Runtime data must stay outside the Skill core')
    config = read_json(root/'analytics-config.json')
    data = root/'data'; data.mkdir(exist_ok=True)
    lock = data/'.analytics-import.lock'
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SystemExit('已有本地导入在运行；旧数据保持可用。')
    try:
        os.write(fd, str(os.getpid()).encode())
        registry_file=data/'capture-index.json'
        registry=read_json(registry_file) if registry_file.exists() else {'schemaVersion':1,'captures':[]}
        capture_ids=list(registry['captures'])
        capture_id=None
        added=False
        if args.ingest:
            capture_id=archive_capture(root,config,args.ingest)
            if capture_id not in capture_ids:
                capture_ids.append(capture_id); added=True
        result, review, manifest = build(root, config,capture_ids)
        with tempfile.TemporaryDirectory(prefix='.analytics-stage-', dir=data) as tmp:
            stage = Path(tmp)
            for name, value in [('analytics.json', result), ('review-input.json', review), ('analytics-sources.json', manifest),('capture-index.json',{'schemaVersion':1,'captures':capture_ids})]:
                (stage/name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
            if result['posts']:
                render_local_review(config,review,result,stage/'review.html')
            else:
                (stage/'review.html').write_text('<!doctype html><meta charset=utf-8><h2>尚未采集作品</h2><p>配置 WorkBuddy 后进行只读采集。</p>',encoding='utf8')
                (stage/'review.stats.json').write_text('{}',encoding='utf8')
            html = (stage/'review.html').read_text(encoding='utf8')
            if '<h2' not in html or len(result['posts']) != len({p['id'] for p in result['posts']}):
                raise ValueError('Generated artifacts did not pass validation')
            # Keep old bytes until every generated artifact is ready. Roll back partial commit failures.
            names = ['analytics.json', 'review-input.json', 'review.html', 'review.stats.json', 'analytics-sources.json','capture-index.json']
            old = {name: (data/name).read_bytes() if (data/name).exists() else None for name in names}
            changed = []
            try:
                for name in names:
                    os.replace(stage/name, data/name); changed.append(name)
            except Exception:
                for name in changed:
                    if old[name] is not None:
                        recovery=stage/(name+'.recovery'); recovery.write_bytes(old[name]); os.replace(recovery, data/name)
                    else:
                        (data/name).unlink(missing_ok=True)
                raise
        print(json.dumps({'ok': True, 'postCount': len(result['posts']), 'latestPostCount': result['summary']['latestPostCount'], 'latestCapturedAt': result['summary']['latestCapturedAt'], 'importedAt': result['importedAt'], 'mode': 'capture-ingest' if args.ingest else 'local-history', 'captureId':capture_id,'added':added,'captureStatus':result['summary']['latestCaptureStatus']}, ensure_ascii=False))
    finally:
        os.close(fd)
        lock.unlink(missing_ok=True)

if __name__ == '__main__':
    main()
