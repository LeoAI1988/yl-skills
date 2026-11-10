"""Selected, provenance-preserving, incremental text sync; no local mutation."""
import argparse,collections,hashlib,json,re,time,urllib.request,urllib.error
from pathlib import Path
import yaml
LOADER=getattr(yaml,'CSafeLoader',yaml.SafeLoader)
def sha(data):return hashlib.sha256(data).hexdigest()
def metadata(p,text):
    side=Path(str(p)+'.asset.yml')
    m=yaml.load(side.read_text(encoding='utf-8-sig'),Loader=LOADER) if side.exists() else yaml.load(text.split('---',2)[1],Loader=LOADER) if text.startswith('---') and len(text.split('---',2))==3 else {}
    return m if isinstance(m,dict) else {}
def reason(p,rel,text,m,category,cfg):
    if p.is_symlink() or any(part.startswith('.') for part in Path(rel).parts):return 'hidden_or_link'
    if re.search(r'备份|历史版本|文件历史|私人档案|私聊|工作台草稿|回收站|(^|/)(backup|archive|temp)(/|$)',rel,re.I):return 'private_or_history'
    if any(re.search(x,rel,re.I) for x in cfg.get('exclude_patterns',[])):return 'configured_exclusion'
    if any(x in text for x in cfg.get('deny_ids',[])):return 'excluded_source_id'
    if str(m.get('privacy','')).lower() in ('p2','p3','private','secret'):return 'private_metadata'
    if re.search(r'(?:sk-[a-zA-Z0-9]{24,}|-----BEGIN .*PRIVATE KEY-----|(?:client_secret|api_key|access_token|密码)\s*[:=：]\s*[\w/+.-]{12,}|(?<![A-Za-z0-9])1[3-9]\d{9}(?![A-Za-z0-9])|(?<![A-Za-z0-9])\d{17}[\dXx](?![A-Za-z0-9]))',text):return 'sensitive_pattern_review'
    if category=='works':
        if m.get('ownership')!='user_owned':return 'ownership_not_user'
        if m.get('content_status') not in ('copied_verified','published','final_unpublished','course_transcript_text_reviewed','archived_final_video_text','final_confirmed'):return 'not_confirmed_body'
    if category=='atoms':
        if m.get('v2_status')=='retired':return 'retired'
        if m.get('writing_status') in ('research_only','reference_only'):return 'external_reference'
        a=str(m.get('authorship',''))
        if m.get('writing_status')!='user_adopted' and (re.search('外部|混合|未明|unknown|他人|书目|历史提示词|工具备忘',a) or not a):return 'attribution_requires_review'
        if re.search('内部计划|经营计划|经营分析|书信|个人价值反思',a):return 'private_business_or_personal'
    if category=='expressions' and re.search('社群|私聊',rel):return 'private_conversation_aggregate'
    return ''
def collect(cfg):
    root=Path(cfg['root']).resolve();docs=[];skipped=[]
    for entry in cfg['roots']:
        base=(root/entry['path']).resolve();base.relative_to(root)
        if not base.is_dir():raise RuntimeError('Configured source is missing: '+str(base))
        for p in sorted(base.rglob('*.md')):
            if not p.resolve().is_relative_to(root):skipped.append({'path':str(p),'reason':'outside_root'});continue
            rel=p.relative_to(root).as_posix();raw=p.read_bytes();text=raw.decode('utf-8-sig');m=metadata(p,text)
            why=reason(p,rel,text,m,entry['category'],cfg)
            if why:skipped.append({'path':rel,'reason':why});continue
            h=sha(text.encode());title=next((x.lstrip('# ').strip() for x in text.splitlines() if x.startswith('# ')),p.stem)
            docs.append({'id':sha(rel.encode()),'hash':h,'title':title[:300],'source':rel,'category':entry['category'],'text':text,'meta':{'source_sha256':sha(raw),'metadata':m}})
    if not docs:raise RuntimeError('Selection is empty; refusing to clear the cloud service.')
    return docs,skipped
def request(creds,path,body=None):
    base=creds['base'].rstrip('/');u=urllib.parse.urlsplit(base)
    if u.scheme!='https' or u.username or u.password or u.query or u.fragment:raise RuntimeError('A clean HTTPS service URL is required.')
    headers={'Authorization':'Bearer '+creds['admin_token'],'Content-Type':'application/json'}
    req=urllib.request.Request(base+path,data=None if body is None else json.dumps(body,ensure_ascii=False,default=str).encode(),headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=120) as r:return json.load(r)
    except urllib.error.HTTPError as e:raise RuntimeError('Cloud HTTP '+str(e.code)+'; re-read manifest before retrying.') from None
def run(cfg,mode):
    docs,skipped=collect(cfg);creds=json.loads(Path(cfg['credentials_file']).read_text(encoding='utf-8-sig'))
    remote=request(creds,'/admin/manifest');old={x['id']:x['hash'] for x in remote['documents']};new={x['id']:x['hash'] for x in docs}
    changed=[d for d in docs if old.get(d['id'])!=d['hash']]
    result={'mode':mode,'at':time.strftime('%Y-%m-%d %H:%M:%S'),'included':len(docs),'categories':dict(collections.Counter(d['category'] for d in docs)),'new':sum(d['id'] not in old for d in changed),'modified':sum(d['id'] in old for d in changed),'removed':len(set(old)-set(new)),'skipped':dict(collections.Counter(x['reason'] for x in skipped)),'bytes':sum(len(d['text'].encode()) for d in docs),'uploaded':False}
    folder=Path(cfg['state_dir']);folder.mkdir(parents=True,exist_ok=True)
    (folder/'selection.json').write_text(json.dumps({'included':[{k:v for k,v in d.items() if k not in ('text','meta')} for d in docs],'excluded':skipped},ensure_ascii=False,indent=2),encoding='utf-8')
    if mode=='sync':
        if changed or set(old)!=set(new) or remote.get('indexing_pending',0):result['receipt']=request(creds,'/admin/sync',{'base_revision':remote['revision'],'manifest':[{'id':d['id'],'hash':d['hash']} for d in docs],'changed':changed})
        check=request(creds,'/admin/manifest')
        if {x['id']:x['hash'] for x in check['documents']}!=new:raise RuntimeError('Cloud manifest verification failed.')
        if check.get('indexing_pending',0):raise RuntimeError('Text is synchronized; cloud semantic index is still incomplete. Retry sync to resume.')
        result.update(uploaded=bool(changed),verified=True,revision=check['revision'])
    (folder/('latest-'+mode+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False));return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('mode',choices=['plan','sync']);a=p.parse_args();run(json.loads(Path(a.config).read_text(encoding='utf-8-sig')),a.mode)
