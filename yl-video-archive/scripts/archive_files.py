"""Hash-verified local archive and explicit, resumable scoped cleanup."""
from pathlib import Path
from collections import Counter
import argparse,hashlib,json,os,shutil,stat,sys

ROLES={'final_video','cover','review','mother','published_marker'}
def load(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def dump(p,data):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');os.replace(tmp,p)
def digest(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def linked(p):
 try:s=p.lstat();return stat.S_ISLNK(s.st_mode) or bool(getattr(s,'st_file_attributes',0)&0x400)
 except FileNotFoundError:return False
def root_path(value):
 p=Path(value).expanduser().absolute()
 if not p.is_dir() or p.parent==p or linked(p):raise ValueError('Workspace must be an existing, non-root real directory')
 return p.resolve()
def safe(root,value):
 p=Path(value).expanduser();p=p.absolute() if p.is_absolute() else root/p
 if '..' in p.parts or not p.is_relative_to(root) or p==root:raise ValueError('Path is outside workspace or is workspace root')
 current=root
 for part in p.relative_to(root).parts:
  current=current/part
  if linked(current):raise ValueError('Linked archive input/output is not allowed')
 if not p.resolve().is_relative_to(root):raise ValueError('Resolved path escaped workspace')
 return p
def outside_cleanup(p,roots):
 if any(p==r or p.is_relative_to(r) for r in roots):raise ValueError('Preserved file or record is inside cleanup')
def record(root,path,plan):
 p=safe(root,path);outside_cleanup(p,[Path(r) for r in plan['cleanup_roots']])
 if any(str(p) in (x['source'],x['target']) for x in plan['files']):raise ValueError('Record cannot replace an archive asset')
 return p
def checked(p,expected):
 if not p.is_file() or digest(p)!=expected:raise ValueError('File missing or changed: '+str(p))
def inventory(path):
 entries=[]
 def walk(p):
  s=p.lstat();rel=p.relative_to(path).as_posix()
  if linked(p):entries.append([rel,'link',s.st_size,s.st_mtime_ns]);return
  if stat.S_ISDIR(s.st_mode):
   entries.append([rel,'dir'])
   for c in sorted(p.iterdir()):walk(c)
  else:entries.append([rel,'file',s.st_size,s.st_mtime_ns])
 if path.exists():walk(path)
 encoded=json.dumps(entries,ensure_ascii=False,separators=(',',':')).encode('utf-8')
 return {'path':str(path),'files':sum(x[1]=='file' for x in entries),'bytes':sum(x[2] for x in entries if x[1]=='file'),'links':sum(x[1]=='link' for x in entries),'snapshot':hashlib.sha256(encoded).hexdigest()}
def plan(args):
 raw=load(args.manifest);root=root_path(raw['workspace_root']);rows=raw['files'];groups={};sources=set();targets=set();files=[]
 if not isinstance(rows,list) or not rows:raise ValueError('No archive files')
 archive_type=raw.get('archive_type','standard');course_refs=[]
 if archive_type not in {'standard','course_slices'}:raise ValueError('Unknown archive_type')
 if archive_type=='course_slices':
  if any(x.get('role')=='mother' for x in rows):raise ValueError('Course slices reuse existing course sources; do not archive mother copies')
  refs=raw.get('course_source_references',[])
  if not isinstance(refs,list) or not refs:raise ValueError('Course slices need existing course_source_references')
  for value in refs:
   ref=Path(value).expanduser()
   if not ref.is_absolute() or not ref.is_file() or linked(ref):raise ValueError('Course source reference must be an existing regular absolute file')
   course_refs.append({'path':str(ref.resolve()),'sha256':digest(ref)})
 for entry in rows:
  x=dict(entry);role=x.get('role');item=x.get('item_id')
  if role not in ROLES or not isinstance(item,str) or not item:raise ValueError('Invalid role or item_id')
  a=safe(root,x['source']);b=safe(root,x['target'])
  if not a.is_file() or b.is_dir():raise ValueError('Invalid source or target type')
  h=digest(a)
  if x.get('sha256') and x['sha256']!=h:raise ValueError('Source differs from selected version')
  if b.exists() and b!=a and digest(b)!=h:raise ValueError('Target collision; choose a distinct version/name')
  if str(b) in targets:raise ValueError('Duplicate target')
  if role=='mother' and (not x.get('capture_date') or not x.get('date_basis')):raise ValueError('Mother needs capture_date and date_basis')
  if role=='published_marker' and raw.get('status',{}).get('published') is not True:raise ValueError('Publication evidence status is missing')
  groups.setdefault(item,Counter())[role]+=1;sources.add(str(a));targets.add(str(b));x.update(source=str(a),target=str(b),sha256=h,bytes=a.stat().st_size);files.append(x)
 for counts in groups.values():
  if counts['final_video']!=1 or counts['review']!=1 or counts['cover']>1:raise ValueError('Each item needs one final, one review, and at most one cover')
  if not counts['cover'] and not raw.get('no_cover_reason'):raise ValueError('Record why this batch has items without covers')
 final_parents={x['item_id']:Path(x['target']).parent for x in files if x['role']=='final_video'}
 for x in files:
  if x['role']=='mother' and not Path(x['target']).is_relative_to(final_parents[x['item_id']]):raise ValueError('Mother must be inside its corresponding final-video directory')
 for x in files:
  if x['target'] in sources and x['source']!=x['target']:raise ValueError('Source/target chains and cycles are not allowed')
 cleanup=[safe(root,v) for v in raw.get('cleanup_roots',[])]
 for i,p in enumerate(cleanup):
  if p.exists() and not p.is_dir():raise ValueError('Cleanup root must be a directory')
  if any(p==q or p.is_relative_to(q) or q.is_relative_to(p) for q in cleanup[:i]):raise ValueError('Duplicate or nested cleanup roots')
  outside_cleanup(Path(__file__).resolve(),[p])
 preserved=[]
 for value in raw.get('protected_paths',[]):
  p=safe(root,value);outside_cleanup(p,cleanup)
  if not p.is_file():raise ValueError('Protected path must be a file')
  if str(p) in sources or str(p) in targets:raise ValueError('Protected file cannot also be an archive operation')
  preserved.append({'path':str(p),'sha256':digest(p)})
 for x in files:outside_cleanup(Path(x['target']),cleanup)
 for x in course_refs:outside_cleanup(Path(x['path']),cleanup)
 result={'schema_version':1,'workspace_root':str(root),'files':files,'protected_paths':preserved,'cleanup_roots':list(map(str,cleanup)),'status':raw.get('status',{}),'manifest_path':str(safe(root,args.manifest))}
 result.update(archive_type=archive_type,course_source_references=course_refs)
 outside_cleanup(Path(result['manifest_path']),cleanup);out=record(root,args.output,result);result['plan_path']=str(out);dump(out,result)
 print(json.dumps({'state':'PLANNED','items':len(groups),'files':len(files),'cleanup':len(cleanup)},ensure_ascii=False))
def verify_receipt(receipt):
 p=receipt['plan'];root=root_path(p['workspace_root']);roots=[safe(root,r) for r in p['cleanup_roots']]
 for x in p['files']:
  target=safe(root,x['target']);outside_cleanup(target,roots);checked(target,x['sha256'])
 for x in p['protected_paths']:checked(safe(root,x['path']),x['sha256'])
 for x in p.get('course_source_references',[]):checked(Path(x['path']),x['sha256'])
 return root,p
def apply(args):
 p=load(args.plan);root=root_path(p['workspace_root']);rp=record(root,args.receipt,p);receipt=load(rp) if rp.exists() else {'state':'ARCHIVING','plan':p,'completed':[]}
 if receipt['plan']!=p:raise ValueError('Receipt belongs to a different plan')
 record(root,p['plan_path'],p);record(root,p['manifest_path'],p)
 for x in p['protected_paths']:checked(safe(root,x['path']),x['sha256'])
 prior_state=receipt['state'];ordered=sorted(p['files'],key=lambda x:x['role']=='mother')
 for x in ordered:
  a=safe(root,x['source']);b=safe(root,x['target']);key=x['target']
  if a.exists():checked(a,x['sha256'])
  elif not b.exists():raise ValueError('Selected source missing before archive')
  if not b.exists():
   b.parent.mkdir(parents=True,exist_ok=True);temp=b.with_name(b.name+'.archive-part')
   if temp.exists():raise ValueError('Existing partial file; inspect it before retry')
   try:
    if x['role']=='mother' and a.stat().st_dev==b.parent.stat().st_dev:
     os.rename(a,b);checked(b,x['sha256'])
    else:
     shutil.copy2(a,temp);checked(temp,x['sha256']);os.replace(temp,b)
   except BaseException:
    if temp.exists():temp.unlink()
    raise
  checked(b,x['sha256'])
  if x['role']=='mother' and a!=b and a.exists():checked(a,x['sha256']);a.unlink()
  if key not in receipt['completed']:receipt['completed'].append(key)
  receipt['state']='ARCHIVING';dump(rp,receipt)
 verify_receipt(receipt);receipt['state']='ARCHIVED_AND_CLEANED' if prior_state=='ARCHIVED_AND_CLEANED' else 'ARCHIVED_VERIFIED';dump(rp,receipt);print(json.dumps({'state':receipt['state'],'files':len(p['files']),'status':p['status']},ensure_ascii=False))
def verify(args):
 receipt=load(args.receipt);_,p=verify_receipt(receipt);print(json.dumps({'state':'FILES_VERIFIED','files':len(p['files']),'status':p['status']},ensure_ascii=False))
def purge(root,p):
 if not p.is_relative_to(root) or p==root or not p.parent.resolve().is_relative_to(root):raise ValueError('Unsafe cleanup path')
 if linked(p):
  if os.name=='nt' and not p.is_symlink() and stat.S_ISDIR(p.lstat().st_mode):os.rmdir(p)
  elif p.is_symlink():p.unlink()
  elif p.is_dir():os.rmdir(p)
  else:p.unlink()
 elif p.is_dir():
  for c in p.iterdir():purge(root,c)
  p.rmdir()
 else:
  s=p.stat()
  if not s.st_mode&stat.S_IWRITE:p.chmod(s.st_mode|stat.S_IWRITE)
  p.unlink()
def cleanup(args):
 rp=Path(args.receipt);receipt=load(rp);root,p=verify_receipt(receipt);record(root,rp,p)
 if receipt['state'] not in {'ARCHIVED_VERIFIED','ARCHIVED_AND_CLEANED','CLEANUP_IN_PROGRESS','CLEANUP_INCOMPLETE'}:raise ValueError('Archive has not finished; do not clean process files')
 for name in ['plan_path','manifest_path']:record(root,p[name],p)
 roots=[safe(root,v) for v in p['cleanup_roots']];current=[inventory(v) for v in roots]
 if not args.apply:
  receipt['cleanup_precheck']=current;dump(rp,receipt);print(json.dumps({'dry_run':True,'roots':current},ensure_ascii=False));return
 if receipt.get('cleanup_precheck')!=current:raise ValueError('Run a fresh cleanup precheck; directory snapshot differs')
 receipt['state']='CLEANUP_IN_PROGRESS';dump(rp,receipt)
 try:
  for folder in roots:
   if folder.exists():purge(root,folder)
 except BaseException as error:
  receipt['state']='CLEANUP_INCOMPLETE';receipt['cleanup_error']=str(error);dump(rp,receipt);raise
 verify_receipt(receipt);receipt['state']='ARCHIVED_AND_CLEANED';receipt.pop('cleanup_error',None);dump(rp,receipt);print(json.dumps({'state':receipt['state'],'status':p['status']},ensure_ascii=False))
def main():
 parser=argparse.ArgumentParser(description=__doc__);subs=parser.add_subparsers(dest='command',required=True)
 q=subs.add_parser('plan');q.add_argument('--manifest',required=True);q.add_argument('--output',required=True)
 q=subs.add_parser('apply');q.add_argument('--plan',required=True);q.add_argument('--receipt',required=True)
 q=subs.add_parser('verify');q.add_argument('--receipt',required=True)
 q=subs.add_parser('cleanup');q.add_argument('--receipt',required=True);q.add_argument('--apply',action='store_true')
 args=parser.parse_args()
 try:globals()[args.command](args)
 except (ValueError,OSError,KeyError,TypeError) as error:print(json.dumps({'error':str(error)},ensure_ascii=False),file=sys.stderr);return 1
 return 0
if __name__=='__main__':raise SystemExit(main())
