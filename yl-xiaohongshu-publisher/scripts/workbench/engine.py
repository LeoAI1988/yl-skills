"""Local publishing inventory and queue. Source media are always read-only."""
import datetime as dt
import hashlib
import json
import re
import sqlite3
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path
from rules import DEFAULTS, LIMITS, BLOCKING_JOB_STATES, annotations, validate, normalize_tags

TZ = dt.timezone(dt.timedelta(hours=8))
VIDEO = {'.mp4', '.mov', '.m4v', '.webm'}
IMAGES = {'.png', '.jpg', '.jpeg', '.webp'}
SKIP = {'素材原件', '母带', '待对应素材', '旧版', '备份', '.git', 'node_modules'}

def now(): return dt.datetime.now(TZ)
def times(count,start_time='10:00',end_time='20:00'):
    count=int(count)
    if not 1 <= count <= 10: raise ValueError('本地每日规划数量必须为1—10条，这不是平台额度')
    def minutes(value):
        if not isinstance(value,str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]0',value):raise ValueError('请选择有效时间，分钟须为00、10、20、30、40或50')
        h,m=map(int,value.split(':'));return h*60+m
    start,end=minutes(start_time),minutes(end_time)
    if end<=start:raise ValueError('最晚发布时间必须晚于最早发布时间（同一天内）')
    if count==1:return [start_time]
    if end-start<(count-1)*10:raise ValueError(f'每天{count}条至少需要{(count-1)*10}分钟，请扩大时间段或减少条数')
    segments=count-1;steps=(end-start)//10
    values=[start+10*((2*steps*i+segments)//(2*segments)) for i in range(count)]
    return [f'{m//60:02}:{m%60:02}' for m in values]

def matching_tags(title, body, pool, seed):
    text=(title+' '+body).lower()
    aliases={'Codex':['codex','工作台'], 'WorkBuddy':['workbuddy','预制菜'], '知识库':['知识','原子','表达资产','建模'], '数字资产':['资产','复利','基建','沉淀'], '录音卡':['录音','记录','语料'], '自媒体':['自媒体','公众号','爆款','文案'], '短视频':['视频','剪辑','拍摄'], '获客':['客户','获客','成交','销售'], 'AI员工':['员工','老板','团队','企业'], '智能体':['智能体','自动化'], 'agent':['agent','智能体'], 'OpenAI':['openai','gpt','codex'], 'Anthropic':['anthropic','claude']}
    ranked=[]
    for raw in pool:
        try:tag=normalize_tags([raw])[0]
        except ValueError:continue
        words=aliases.get(tag,[tag.lower()]);score=sum(8 for w in words if w.lower() in text)
        score+=12 if tag.lower() in title.lower() else 0
        if score and tag.casefold() not in {t.casefold() for _,t in ranked}:ranked.append((score,tag))
    return [t for _,t in sorted(ranked,key=lambda x:(-x[0],x[1]))[:10]]

def source_title(video):
    """Only use unambiguous, name-bound manuscripts, never a nearby clip's title."""
    candidates=[];body=''
    for path in sorted(video.parent.glob('*.md')):
        if path.stem!=video.stem and not any(path.stem.startswith(video.stem+s) for s in ['-','_']):continue
        content=path.read_text(encoding='utf-8-sig',errors='replace')
        if not body:body=content[:20000]
        explicit=re.findall(r'^\s*(?:[-*]\s*)?(?:\*\*)?(?:发布标题|原始标题|成片标题|视频顶部标题)(?:\*\*)?\s*[:：]\s*(.+?)\s*$',content,re.M)
        values=[v.strip().strip('*').strip().strip('「」“”') for v in explicit]
        if not values:
            first=content.splitlines()[0].lstrip('#').strip() if content else ''
            if first and not any(x in first for x in ['审查','归档','修改方案','最终版']):values=[first]
        candidates.extend((v,path.name) for v in values if v)
    unique={value for value,_ in candidates}
    if len(unique)==1:
        value=next(iter(unique));return value,'原稿：'+next(p for v,p in candidates if v==value),body
    return '',('多个原稿标题不一致，请核对' if unique else '待核对视频顶部标题'),body

class Store:
    def __init__(self, config):
        if config.get('platform')!='xiaohongshu':raise ValueError('配置必须明确platform=xiaohongshu，不能复用其他平台配置')
        self.config=config;self.root=Path(config['data_dir'])
        self.lock=threading.RLock();self.db=self.root/'workbench.sqlite3'
        if self.db.exists():
            self._check_platform();return
        # Validate imports and serialize before creating any database file.
        initial=self.seed()
        initial.update(platform='xiaohongshu',app='yl-xiaohongshu-workbench',plan=[],jobs=[],preferences={'count':1,'start_date':(now().date()+dt.timedelta(days=1)).isoformat(),'start_time':'10:00','end_time':'20:00'})
        rows=[(key,json.dumps(value,ensure_ascii=False)) for key,value in initial.items()]
        self.root.mkdir(parents=True,exist_ok=True)
        try:
            # Exclusive creation also prevents overwriting a concurrently created store.
            with self.db.open('xb'):pass
        except FileExistsError:
            self._check_platform();return
        try:
            with self.connect() as c:
                c.execute('BEGIN')
                c.execute('CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
                c.executemany('INSERT INTO kv VALUES (?,?)',rows)
        except BaseException:
            self.db.unlink(missing_ok=True)
            raise
    def _check_platform(self):
        # Never open an existing unverified database in write mode.
        try:
            c=sqlite3.connect(self.db.resolve().as_uri()+'?mode=ro',uri=True,timeout=30)
            try:values={key:json.loads(value) for key,value in c.execute('SELECT key,value FROM kv')}
            finally:c.close()
        except (sqlite3.Error,ValueError) as exc:
            raise ValueError('数据库缺少可验证的平台标记或结构无效；未做任何数据写入') from exc
        if values.get('platform')!='xiaohongshu' or values.get('app','yl-xiaohongshu-workbench')!='yl-xiaohongshu-workbench':
            raise ValueError('数据库未标记为小红书或属于其他平台；请先核实数据目录，禁止自动迁移')
        if not {'assets','folders','plan','jobs','preferences'}<=values.keys():
            raise ValueError('小红书数据库初始化不完整；禁止自动覆盖')
    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.db,timeout=30)
        try:
            with c:yield c
        finally:c.close()
    def get(self,key,default=None):
        with self.connect() as c:r=c.execute('SELECT value FROM kv WHERE key=?',(key,)).fetchone()
        return json.loads(r[0]) if r else default
    def set(self,key,value):
        with self.connect() as c:c.execute('INSERT OR REPLACE INTO kv VALUES (?,?)',(key,json.dumps(value,ensure_ascii=False)))
    def seed(self):
        p=Path(self.config.get('import_plan',''))
        if not p.is_file():return {'assets':[],'folders':[]}
        old=json.loads(p.read_text(encoding='utf-8'));assets=[]
        if old.get('platform')!='xiaohongshu':raise ValueError('导入计划必须明确标注platform=xiaohongshu，不能沿用其他平台的发布历史')
        for r in old.get('rows',[]):
            # An imported file is not proof of an actual platform submission.
            assets.append(dict(id=r['id'],video=r['video'],name=Path(r['video']).name,title=r.get('title',''),title_source=r.get('title_source',''),body='',caption=r.get('caption',''),cover=r.get('cover',''),date=r['date'],date_basis=r.get('date_basis','沿用素材清单日期，待核实'),duration=r.get('duration',0),bytes=Path(r['video']).stat().st_size if Path(r['video']).exists() else 0,tags=r.get('tags',[]),settings={**DEFAULTS,**{k:v for k,v in r.get('settings',{}).items() if k in DEFAULTS}},state='excluded' if r.get('disposition')=='excluded' else 'ready',dedup='导入记录，需核对小红书后台',dedup_evidence='',platform_id='',scheduled_at='',folder=str(Path(r['video']).parent),selected=False))
        return {'assets':assets,'folders':self.config.get('initial_folders',[])}
    def preferences(self):
        return {'count':1,'start_time':'10:00','end_time':'20:00',**self.get('preferences',{})}
    def account(self):
        return self.preferences().get('account',self.config.get('account','')).strip()
    def set_account(self,value):
        if not isinstance(value,str) or not value.strip() or len(value)>120:raise ValueError('请填写已核实的小红书账号名称或账号ID')
        with self.lock:
            if any(j['state'] in BLOCKING_JOB_STATES for j in self.get('jobs',[])):raise ValueError('先核对并结束当前作品，再修改预期账号')
            pref=self.preferences();pref['account']=value.strip();self.set('preferences',pref)
            return {'account':pref['account']}
    def schedule_policy(self):
        policy=self.config.get('schedule_policy',{})
        lead=int(policy.get('lead_minutes',self.config.get('schedule_lead_minutes',60)));window=int(policy.get('window_days',self.config.get('schedule_window_days',14)))
        if lead<1 or window<1 or lead>=window*24*60:raise ValueError('本地定时预检窗口配置无效')
        return dict(lead_minutes=lead,window_days=window,verified=False,note='本地预检参考值；上传前须核实当前小红书后台的定时能力和窗口')
    def snapshot(self):
        with self.lock:
            plan=self.get('plan',[])
            assets=[{**a,'caption':a.get('caption',''),**annotations(a)} for a in self.get('assets',[])]
            return dict(dedup_status=self.get('dedup_status',{}),dedup_groups=self.get('dedup_groups',[]),dedup_busy=getattr(self,'dedup_busy',False),assets=assets,folders=self.get('folders',[]),plan=plan,plan_revision=self.plan_revision(plan),preparation_revision=self.preparation_revision(),preferences=self.preferences(),jobs=self.get('jobs',[]),account=self.account(),preparation_defaults={'ai_declaration':self.config.get('ai_declaration_default','unknown')},tag_pool=self.config.get('tag_pool',[]),collections=self.config.get('collections',[]),limits=LIMITS,schedule_policy=self.schedule_policy(),mode='batch_publish',server_time=now().isoformat())
    @staticmethod
    def plan_revision(rows):return hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
    def preparation_revision(self):
        with self.lock:
            fields=['id','title','caption','tags','settings','video','cover','state','sha256','name','duration']
            assets=sorted(({key:asset.get(key) for key in fields} for asset in self.get('assets',[])),key=lambda asset:asset['id'])
            payload=dict(plan=self.get('plan',[]),account=self.account(),assets=assets)
            return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()
    @staticmethod
    def unique_assets(assets):
        ids=[a['id'] for a in assets];paths=[str(Path(a['video']).resolve()).casefold() for a in assets]
        hashes=[a['sha256'] for a in assets if a.get('sha256')]
        if len(ids)!=len(set(ids)) or len(paths)!=len(set(paths)) or len(hashes)!=len(set(hashes)):
            raise ValueError('同一视频不能重复排期，请移动已排期的视频')
    def check_revision(self,rows,expected):
        if expected is not None and expected!=self.plan_revision(rows):raise ValueError('发布列表已更新，请刷新后重试，避免覆盖其他调整')
    def probe(self,path):
        try:
            result=subprocess.run([self.config['ffprobe'],'-v','error','-show_entries','format=duration','-of','json',str(path)],capture_output=True,text=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            return float(json.loads(result.stdout)['format']['duration'])
        except Exception:return 0
    def scan(self,folder):
        root=Path(folder.strip().strip('"')).expanduser().resolve()
        if not root.is_dir():raise ValueError('找不到这个文件夹，请检查完整地址')
        paths=[]
        for base,dirs,files in __import__('os').walk(root,followlinks=False):
            dirs[:]=[d for d in dirs if d not in SKIP and not Path(base,d).is_symlink() and not getattr(Path(base,d),'is_junction',lambda:False)()]
            for name in files:
                f=Path(base,name)
                if f.suffix.lower() in VIDEO and not f.is_symlink():paths.append(f)
        with self.lock:
            assets=self.get('assets');known={str(Path(a['video']).resolve()).casefold():a for a in assets}
            added=[]
            for p in paths:
                if str(p).casefold() in known:continue
                # A version suffix denotes revisions of this named output only.
                match=re.search(r'[_-]v(\d+)$',p.stem,re.I)
                if match:
                    stem=p.stem[:match.start()];versions=[x for x in paths if x.parent==p.parent and re.match(re.escape(stem)+r'[_-]v\d+$',x.stem,re.I)]
                    if p!=max(versions,key=lambda x:int(re.search(r'v(\d+)$',x.stem,re.I)[1])):continue
                ident='V-'+hashlib.sha256(str(p).casefold().encode()).hexdigest()[:12]
                title,source,body=source_title(p)
                prefix=re.match(r'\d+[-_]\d+',p.name);covers=[x for x in p.parent.iterdir() if x.suffix.lower() in IMAGES and ('封面' in x.name or 'cover' in x.name.lower())]
                if prefix:covers=[x for x in covers if x.name.startswith(prefix[0])]
                elif len([x for x in paths if x.parent==p.parent])>1:covers=[x for x in covers if x.stem.startswith(p.stem)]
                cover=str(max(covers,key=lambda x:x.stat().st_mtime)) if covers else ''
                a=dict(id=ident,video=str(p),name=p.name,title=title,title_source=source,body=body,caption='',cover=cover,date=dt.datetime.fromtimestamp(p.stat().st_mtime,TZ).date().isoformat(),date_basis='文件修改日期，未确认为拍摄日期',duration=self.probe(p),bytes=p.stat().st_size,tags=matching_tags(title or p.stem,body,self.config.get('tag_pool',[]),ident),settings=dict(DEFAULTS),state='ready',dedup='发布前核对实际视频',dedup_evidence='',folder=str(root),selected=False)
                same_size=[x for x in assets if x.get('bytes')==a['bytes'] and Path(x['video']).is_file()]
                if same_size:
                    with p.open('rb') as f:a['sha256']=hashlib.file_digest(f,'sha256').hexdigest()
                    for other in same_size:
                        # Retain a recorded submission digest if its source was replaced.
                        with Path(other['video']).open('rb') as f:current_sha=hashlib.file_digest(f,'sha256').hexdigest()
                        if other['state'] not in {'scheduled','published','reviewing','history','duplicate'} or not other.get('sha256'):other['sha256']=current_sha
                        if a['sha256']==other['sha256']:
                            a.update(state='excluded',dedup='相同视频文件',dedup_evidence='与 '+other['id']+' 文件字节完全一致',duplicate_of=other['id'],dedup_signature=[str(p.resolve()).casefold(),p.stat().st_size,p.stat().st_mtime_ns]);break
                assets.append(a);added.append(a)
            self.set('assets',assets);folders=self.get('folders')
            if str(root) not in folders:folders.append(str(root));self.set('folders',folders)
            return {'added':len(added),'found':len(paths)}
    def edit(self,ident,patch):
        return self.edit_many([{'id':ident,'patch':patch}])[0]
    def edit_many(self,items,expected=None):
        """Validate the entire batch before a single database write."""
        with self.lock:
            if expected is not None and expected!=self.preparation_revision():raise ValueError('内容或排期已变化，请重新打开批量设置后保存')
            if not isinstance(items,list) or not items:raise ValueError('请选择要设置的作品')
            ids=[item['id'] for item in items]
            if len(ids)!=len(set(ids)):raise ValueError('同一作品不能重复设置')
            assets=self.get('assets');byid={a['id']:a for a in assets};updated={}
            for item in items:
                ident=item['id'];patch=item['patch']
                if ident not in byid:raise ValueError('作品已变化，请刷新')
                a=dict(byid[ident])
                if a['state']!='ready':raise ValueError('这条作品已锁定，不能修改')
                for key in ['title','caption','cover','selected','tags','settings']:
                    if key not in patch:continue
                    value=patch[key]
                    if key=='cover' and value and (not Path(value).is_file() or Path(value).suffix.lower() not in IMAGES):raise ValueError('封面文件不存在或格式不支持')
                    if key=='settings':value={**a.get('settings',DEFAULTS),**value}
                    if key=='title' and value!=a.get('title'):
                        a['title_source_original']=a.get('title_source_original') or a.get('title_source','')
                        a['title_source']='手动确认标题；原始出处：'+(a['title_source_original'] or '未提供')
                    a[key]=value
                a.update(validate(a));updated[ident]=a
            self.set('assets',[updated.get(a['id'],a) for a in assets])
            return [{**updated[i],**annotations(updated[i])} for i in ids]
    def arrange(self,ids,start_date,count,start_time=None,end_time=None):
        with self.lock:
            if any(x['state'] in BLOCKING_JOB_STATES for x in self.get('jobs',[])):raise ValueError('当前作品尚待手工提交或核验，请先完成当前流程')
            pref=self.preferences();start_time=pref['start_time'] if start_time is None else start_time;end_time=pref['end_time'] if end_time is None else end_time
            day=dt.date.fromisoformat(start_date);hours=times(count,start_time,end_time);assets=self.get('assets');byid={a['id']:a for a in assets}
            if not ids or len(set(ids))!=len(ids):raise ValueError('请先选择视频，且不能重复选择')
            chosen=[byid[i] for i in ids]
            if any(a['state']!='ready' for a in chosen):raise ValueError('已发布或已锁定的视频不能重复排期')
            preserved=[dict(r) for r in self.get('plan',[]) if r['asset_id'] in byid and byid[r['asset_id']]['state']!='ready']
            self.unique_assets(chosen+[byid[r['asset_id']] for r in preserved])
            occupied={r['at'] for r in preserved}
            chosen.sort(key=lambda a:(a['date'],a['id']))
            plan=preserved;i=0
            while i<len(chosen):
                if day > now().date()+dt.timedelta(days=365):raise ValueError('开始日期过远')
                for hm in hours:
                    at=dt.datetime.fromisoformat(day.isoformat()+'T'+hm).replace(tzinfo=TZ)
                    if at<now()+dt.timedelta(minutes=self.schedule_policy()['lead_minutes']):continue
                    if at.strftime('%Y-%m-%d %H:%M') in occupied:continue
                    if i>=len(chosen):break
                    plan.append(dict(slot=hashlib.sha256((at.isoformat()+chosen[i]['id']).encode()).hexdigest()[:14],asset_id=chosen[i]['id'],at=at.strftime('%Y-%m-%d %H:%M')));i+=1
                day+=dt.timedelta(days=1)
            plan.sort(key=lambda r:r['at'])
            self.set('plan',plan);self.set('preferences',{**pref,'count':int(count),'start_date':start_date,'start_time':start_time,'end_time':end_time});return plan
    def update_plan(self,rows,expected=None):
        with self.lock:
            if any(x['state'] in BLOCKING_JOB_STATES for x in self.get('jobs',[])):raise ValueError('当前作品尚待手工提交或核验，排期已锁定')
            current=self.get('plan',[]);self.check_revision(current,expected)
            assets={x['id']:x for x in self.get('assets')};ids=[r['asset_id'] for r in rows];slots=[r['at'] for r in rows]
            if len(ids)!=len(set(ids)) or len(slots)!=len(set(slots)) or len(rows)!=len({r['slot'] for r in rows}):raise ValueError('同一视频或同一时刻不能重复使用')
            previous={r['slot']:r for r in current}
            for r in rows:
                if r['asset_id'] not in assets:raise ValueError('视频不可排期')
                if assets[r['asset_id']]['state']!='ready' and previous.get(r['slot'])!=r:raise ValueError('已提交条目不能修改')
                dt.datetime.strptime(r['at'],'%Y-%m-%d %H:%M')
            if any(r not in rows and assets[r['asset_id']]['state']!='ready' for r in previous.values()):raise ValueError('不能移除已提交条目')
            self.unique_assets([assets[r['asset_id']] for r in rows])
            self.set('plan',sorted(rows,key=lambda r:r['at']))

    def replace_video(self,slot,ident,expected):
        with self.lock:
            rows=self.get('plan',[]);self.check_revision(rows,expected)
            if any(r['asset_id']==ident and r['slot']!=slot for r in rows):raise ValueError('这条视频已在发布列表中，请拖动调整位置，不能重复选择')
            row=next((r for r in rows if r['slot']==slot),None)
            if row is None:raise ValueError('发布时间已变化，请刷新')
            assets={a['id']:a for a in self.get('assets')}
            if assets[row['asset_id']]['state']!='ready':raise ValueError('已提交条目不能换片')
            row['asset_id']=ident;self.update_plan(rows,expected)

    def move_video(self,source,target,placement,expected):
        with self.lock:
            rows=sorted(self.get('plan',[]),key=lambda r:r['at']);self.check_revision(rows,expected)
            if placement not in ['before','after']:raise ValueError('移动位置无效')
            assets={a['id']:a for a in self.get('assets')}
            movable=[r for r in rows if assets[r['asset_id']]['state']=='ready']
            slots=[r['slot'] for r in movable]
            if source not in slots or target not in slots:raise ValueError('已提交或处理中条目不能移动')
            if source==target:return
            ids=[r['asset_id'] for r in movable];source_id=ids[slots.index(source)];target_id=ids[slots.index(target)]
            ids.remove(source_id);dest=ids.index(target_id)+(placement=='after');ids.insert(dest,source_id)
            for row,ident in zip(movable,ids):row['asset_id']=ident
            self.update_plan(rows,expected)

    def select(self,ids,selected):
        with self.lock:
            assets=self.get('assets')
            for a in assets:
                if a['id'] in ids and a['state']=='ready':a['selected']=bool(selected)
            self.set('assets',assets)

    def remove_folder(self,folder):
        with self.lock:self.set('folders',[p for p in self.get('folders') if p!=folder])
