"""Read-only Getnote connector. Ends at a mandatory semantic handoff, not completion."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'yl-knowledge/scripts'))
from knowledge import load_profile, profile_path, state_path, atomic_json, read_json, register, sha

BASE = 'https://openapi.biji.com'

def request(endpoint, params):
    headers = {'Authorization': os.environ.get('GETNOTE_API_KEY', ''),
               'X-Client-ID': os.environ.get('GETNOTE_CLIENT_ID', '')}
    if not all(headers.values()):
        raise ValueError('Missing GETNOTE_API_KEY or GETNOTE_CLIENT_ID; values never logged')
    for attempt in range(3):
        req = urllib.request.Request(BASE+endpoint+'?'+urllib.parse.urlencode(params), headers=headers, method='GET')
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise ValueError('Getnote HTTP error '+str(exc.code)) from None
            delay = float(exc.headers.get('Retry-After', '10' if exc.code == 429 else '5'))
            if not 0 <= delay <= 60:
                raise ValueError('Rate limit requires later retry; preserve incomplete state')
            time.sleep(delay)
            continue
        except (TimeoutError, urllib.error.URLError):
            if attempt == 2: raise ValueError('Getnote network failure; incomplete inventory') from None
            time.sleep(5); continue
        if payload.get('success') is False or payload.get('error'):
            error = payload.get('error') or {}
            code = str(error.get('code', payload.get('code', 'unknown')))
            if code == '10202' and attempt < 2:
                limit = payload.get('rate_limit') or error.get('rate_limit') or {}
                delay = float(limit.get('retry_after', 10))
                if not 0 <= delay <= 60: raise ValueError('Rate limit; retry in a later run')
                time.sleep(delay); continue
            raise ValueError('Getnote API error code='+code+' request_id='+str(payload.get('request_id','')))
        data = payload.get('data')
        if not isinstance(data, dict): raise ValueError('Unexpected Getnote data envelope')
        return data
    raise ValueError('Getnote retries exhausted')

def pages(endpoint, params, keys):
    result = []
    for page in range(1, 10001):
        data = request(endpoint, {**params, 'page': page})
        rows = next((data[k] for k in keys if isinstance(data.get(k), list)), None)
        if rows is None or type(data.get('has_more')) is not bool:
            raise ValueError('Unexpected pagination schema; cannot treat as empty library')
        result.extend(rows)
        if not data['has_more']: return result
        if not rows: raise ValueError('Empty page with has_more; inventory incomplete')
    raise ValueError('Pagination limit reached; incomplete inventory')

def primary(note):
    candidates = [('audio.original', (note.get('audio') or {}).get('original')),
                  ('web_page.content', (note.get('web_page') or {}).get('content')),
                  ('content', note.get('content')),
                  ('audio.transcript', (note.get('audio') or {}).get('transcript'))]
    for field, text in candidates:
        if isinstance(text, str) and text.strip(): return field, text
    return 'missing', ''

def sync(cfg, root):
    names = cfg.get('sources',{}).get('getnote',{}).get('libraries', [])
    if not names: raise ValueError('Choose Getnote library names in personal profile')
    folder = state_path(cfg, root).parent/'getnote'
    old_path = folder/'inventory.json'
    old = read_json(old_path) if old_path.exists() else {'notes': {}}
    libraries = pages('/open/api/v1/resource/knowledge/list', {}, ['list','knowledge_list','topics'])
    memberships = {}
    for name in names:
        matches = [r for r in libraries if r.get('name',r.get('title')) == name]
        if len(matches) != 1: raise ValueError('Library name missing or ambiguous: '+name)
        topic_id = str(matches[0].get('id',matches[0].get('topic_id','')))
        if not topic_id: raise ValueError('Library ID missing')
        rows = pages('/open/api/v1/resource/knowledge/notes', {'topic_id':topic_id}, ['list','notes','note_list'])
        for row in rows:
            nid = str(row.get('id',row.get('note_id','')))
            if not nid: raise ValueError('Note ID missing')
            entry = memberships.setdefault(nid, {'libraries': [], 'updated_at': str(row.get('updated_at',row.get('update_time','')))})
            entry['libraries'].append(name)
    new_state = {'notes': {}, 'target_libraries': names, 'inventory_complete': True}
    changed = unchanged = 0
    missing = []
    excluded = []
    for nid, meta in memberships.items():
        sid = 'getnote:'+nid
        if sid in cfg.get('excluded_source_ids', []) or nid in cfg.get('excluded_source_ids', []):
            excluded.append(nid)
            new_state['notes'][nid] = {**meta, 'present_in_targets': True, 'excluded_by_profile': True}
            continue
        previous = old['notes'].get(nid)
        if previous and meta['updated_at'] and previous.get('updated_at') == meta['updated_at'] and previous.get('path') and Path(previous['path']).is_file():
            # Re-register unchanged text so interrupted downstream processing remains visible.
            register(cfg, root, previous['path'], sid, 'getnote')
            new_state['notes'][nid] = {**previous, **meta, 'present_in_targets': True}
            unchanged += 1
            continue
        note = request('/open/api/v1/resource/note/detail', {'id':nid,'image_quality':'original'}).get('note')
        if not isinstance(note, dict): raise ValueError('Note detail missing')
        field, body = primary(note)
        if not body:
            missing.append(nid)
            new_state['notes'][nid] = {**meta, 'present_in_targets': True, 'text_missing': True}
            continue
        digest = sha(body.encode('utf-8'))
        file = folder/'originals'/nid/(digest+'.md')
        if not nid.isdigit(): raise ValueError('Unexpected Getnote ID shape')
        file.parent.mkdir(parents=True, exist_ok=True)
        if not file.exists(): file.write_bytes(body.encode('utf-8'))
        elif sha(file.read_bytes()) != digest: raise ValueError('Original version hash mismatch')
        safe = {'id':nid, 'title':note.get('title',''), 'content':note.get('content',''),
                'audio':{k:(note.get('audio') or {}).get(k) for k in ('original','transcript')},
                'web_page':{'content':(note.get('web_page') or {}).get('content')},
                'primary_field':field, 'libraries':meta['libraries']}
        meta_hash=sha(json.dumps(safe,ensure_ascii=False,sort_keys=True).encode('utf-8'))
        meta_path=file.parent/'metadata'/(meta_hash+'.json')
        if not meta_path.exists(): atomic_json(meta_path,safe)
        result = register(cfg, root, file, sid, 'getnote')
        new_state['notes'][nid] = {**meta, 'path':str(file), 'sha256':digest,
                                   'primary_field':field, 'title':note.get('title',''),
                                   'present_in_targets':True}
        changed += result['status'] != 'unchanged'
        unchanged += result['status'] == 'unchanged'
    for nid, meta in old['notes'].items():
        if nid not in memberships: new_state['notes'][nid] = {**meta, 'present_in_targets':False}
    new_state['missing_text_ids'] = missing
    atomic_json(old_path, new_state)
    return {'status':'needs_semantic_processing', 'current_notes':len(memberships),
            'changed':changed, 'unchanged':unchanged, 'missing_text_ids':missing, 'excluded_ids':excluded,
            'next':'yl-knowledge full pipeline; inventory is not distillation completion'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--profile');a=p.parse_args()
    try:
        cfg,root=load_profile(profile_path(a.profile));out=sync(cfg,root)
        print(json.dumps(out,ensure_ascii=False,indent=2));return 2 if out['missing_text_ids'] else 0
    except (ValueError,OSError,KeyError) as exc:
        print(json.dumps({'status':'INCOMPLETE','error':str(exc)},ensure_ascii=False));return 2

if __name__=='__main__':sys.exit(main())
