"""Launch the installed Codex executor; never drive a browser through private APIs."""
import datetime as dt
import json
import shutil
import subprocess
import threading
import uuid
from pathlib import Path
from engine import now, TZ

MODELS={'gpt-6-astra':'GPT-Astra','gpt-6.1-sol':'GPT-6.1 Sol'}
DEFAULT_MODEL='gpt-6-astra'
EFFORTS={'medium':'中','high':'高','xhigh':'极高'}

def execution(model=None,reasoning_effort=None):
    model=model or DEFAULT_MODEL
    reasoning_effort=reasoning_effort or 'high'
    if model not in MODELS:raise ValueError('请选择 GPT-Astra 或 GPT-6.1 Sol')
    if reasoning_effort not in EFFORTS:raise ValueError('推理强度请选择中、高或极高')
    return dict(driver='Codex',model=model,reasoning_effort=reasoning_effort)

class Runner:
    def __init__(self,store):
        self.s=store;self.process=None;self.active=None;self.cancel=False
        jobs=self.s.get('jobs',[]);assets=self.s.get('assets',[])
        for j in jobs:
            if j['state'] in ['running','stopping']:
                j.update(state='attention',message='上次执行中断，请先核对平台结果')
                for a in assets:
                    if a['id'] in j['items'] and a['state'] in ['queued','uploading']:a['state']='unknown'
        self.s.set('jobs',jobs);self.s.set('assets',assets)
    def health(self):
        path=self.s.config.get('codex') or shutil.which('codex')
        return dict(available=bool(path and Path(path).is_file()),message='使用本机Codex和Chrome，执行时核对账号与浏览器连接',running=self.active,default=execution(),models=[{'id':k,'name':v} for k,v in MODELS.items()],reasoning_efforts=[{'id':k,'name':v} for k,v in EFFORTS.items()])
    def start(self,slots,model=None,reasoning_effort=None):
        with self.s.lock:
            executor=execution(model,reasoning_effort)
            if self.active or any(j['state'] in ['running','stopping'] for j in self.s.get('jobs',[])):raise ValueError('已有任务运行，或上次任务需先核验结果')
            if not self.health()['available']:raise ValueError('未找到本机Codex，请先安装并登录')
            assets={a['id']:a for a in self.s.get('assets')};rows=[x for x in self.s.get('plan') if x['slot'] in slots]
            if not rows or len(rows)!=len(set(slots)):raise ValueError('请选择有效的排期')
            self.s.unique_assets([assets[r['asset_id']] for r in rows])
            for r in rows:
                at=dt.datetime.strptime(r['at'],'%Y-%m-%d %H:%M').replace(tzinfo=TZ);a=assets[r['asset_id']]
                if not now()+dt.timedelta(hours=2,minutes=5)<=at<=now()+dt.timedelta(days=14):raise ValueError('本批存在不满足提前2小时或超过14天的时刻，请调整排期')
                if a['state']!='ready':raise ValueError('有作品已提交或待核验，请勿重复启动')
                if not Path(a['video']).is_file():raise ValueError('视频文件已移动：'+a['name'])
            jobid=uuid.uuid4().hex[:12];folder=self.s.root/'jobs'/jobid;folder.mkdir(parents=True)
            manifest={'job_id':jobid,'account':self.s.config.get('account'),'timezone':'Asia/Shanghai','executor':executor,'authorized_by':'用户在工作台点击开始自动发布并确认了本批明细','items':[dict(**r,asset=assets[r['asset_id']]) for r in rows]}
            (folder/'queue.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
            job=dict(id=jobid,state='running',created_at=now().isoformat(),count=len(rows),message='正在连接Codex并核对抖音账号…',items=[r['asset_id'] for r in rows],folder=str(folder),results=[],executor=executor)
            jobs=self.s.get('jobs',[]);jobs.insert(0,job);self.s.set('jobs',jobs)
            for r in rows:assets[r['asset_id']]['state']='queued'
            self.s.set('assets',list(assets.values()));self.active=jobid;self.cancel=False
            threading.Thread(target=self.run,args=(job,folder),daemon=True).start();return job
    def update(self,id,**patch):
        with self.s.lock:
            jobs=self.s.get('jobs');j=next(j for j in jobs if j['id']==id);j.update(patch);self.s.set('jobs',jobs)
    def prompt(self,folder,mode='publish'):
        skill=Path(__file__).resolve().parents[2]/'SKILL.md'
        if mode=='verify':
            return f'''只读核对抖音工作台上次批次。先读取 {skill}、{folder/'queue.json'} 和已有 progress.json/result.json。
仅用cua_repl当前宿主浏览器工具，核对清单账号、实际视频、作品ID、指定发布时间与平台状态。禁止上传、提交、改期、删除、创建草稿或其它平台修改。相同文案不同录制不能当作匹配。
把逐条结果保存到 {folder/'result.json'}，结构为 {{"items":[{{"asset_id":"清单ID","state":"scheduled|published|reviewing|failed|unknown","at":"清单原定时间","platform_id":"真实ID或空","evidence":"本目录截图绝对路径","note":"实际核验结论"}}]}}。
只有连续画面和实际后台记录对应才确认成功，保存包含时间与状态的截图。只有已完整检查定时、审核、公开作品且确认未提交的条目才用failed，并写 verified_absent:true。证据不足用unknown。不要使用Superpowers或子代理。'''
        return f'''请执行抖音工作台的这一个用户授权批次。读取 {skill} 和 {folder/'queue.json'}。
本次仅处理清单内视频与指定时刻。用户已在本地界面确认此批公开定时发布。不得扩展到其他素材或时刻，不使用Superpowers，不创建子代理。
所有浏览器操作只使用当前宿主提供的cua_repl及其文档。先核对账号、实际已发及定时队列，避免重复。相同文案不同次录制可发布；疑似同次录制必须比较实际连续画面。已记录核验结果可复用但先检查平台新增记录。
使用指定封面、标题和5个标签。标题为空时先读取实际视频顶部标题；用户允许无标题时截取正文原句，禁止自造标题。每条settings为本次配置。自动合集必须选择实际已有合集。公开/保存权限/原创/位置/声明/活动分别核对。找不到原创入口如实记明，不用其他声明替代。
定时已过或不满足当前平台窗口则停止该条，不改为立即发布。验证码、登录或必须用户参与的权限操作，保存页面截图并停止，报告需要用户处理。不要绕过。
每条提交前把progress.json中该项标为uploading；提交后回读后台标题、时刻和状态，并保存带周围页面信息的截图到本任务文件夹。只有后台明确显示定时发布中或已公开发布才标为scheduled或published；审核中标为reviewing，未提交标为failed，提交结果不明标为unknown。中断后不得盲目重传。
每条更新 {folder/'progress.json'}，格式{{"items":[{{"asset_id":"...","state":"scheduled|published|reviewing|failed|unknown|uploading","at":"YYYY-MM-DD HH:MM","platform_id":"真实ID或空","evidence":"本任务文件夹内截图绝对路径","note":"简短事实"}}]}}，数组保留本批所有已处理条目。不要写到工作台数据库。
任务结束将同样结构写到 {folder/'result.json'}。无浏览器工具或无法完成时写具体失败原因，不编造成功。最终中文简要总结。'''
    def command(self,job,folder):
        exe=self.s.config.get('codex') or shutil.which('codex')
        saved=job.get('executor',{});executor=execution(saved.get('model'),saved.get('reasoning_effort'))
        return [exe,'exec','--model',executor['model'],'-c',f'model_reasoning_effort="{executor["reasoning_effort"]}"','--json','--skip-git-repo-check','-C',str(folder),'--output-last-message',str(folder/'summary.txt'),'-']

    def run(self,job,folder,mode='publish'):
        try:
            args=self.command(job,folder)
            with (folder/'events.jsonl').open('w',encoding='utf-8') as log,(folder/'errors.log').open('w',encoding='utf-8') as err:
                self.process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,text=True,encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                if self.cancel:self.process.terminate()
                else:self.process.stdin.write(self.prompt(folder,mode));self.process.stdin.close()
                for line in self.process.stdout:
                    log.write(line);log.flush()
                    try:
                        e=json.loads(line);item=e.get('item',{})
                        if item.get('type')=='agent_message':self.update(job['id'],message=item.get('text','')[:600])
                    except (ValueError,KeyError):pass
                    self.ingest(job,folder,False)
                code=self.process.wait()
            self.ingest(job,folder,True)
            results=next(j for j in self.s.get('jobs') if j['id']==job['id']).get('results',[])
            success=len(results)==job['count'] and all(r['state'] in ['scheduled','published'] for r in results)
            self.update(job['id'],state='completed' if success else 'attention',message='本批已在抖音后台核验完成' if success else '本批有作品需要核对，请查看逐条结果；不要重复提交。',exit_code=code)
        except Exception as e:
            self.update(job['id'],state='attention',message='执行未完成：'+str(e));self.ingest(job,folder,True)
        finally:self.active=None;self.process=None
    def ingest(self,job,folder,final):
        result=folder/'result.json' if (folder/'result.json').exists() else folder/'progress.json'
        try:items=json.loads(result.read_text(encoding='utf-8-sig')).get('items',[])
        except (OSError,ValueError):items=[]
        with self.s.lock:
            assets=self.s.get('assets');allowed=set(job['items']);good=[];seen=set()
            manifest=json.loads((folder/'queue.json').read_text(encoding='utf-8'))
            expected={r['asset_id']:r['at'] for r in manifest['items']}
            for item in items:
                if item.get('asset_id') not in allowed:continue
                if item['asset_id'] in seen:
                    for previous in good:
                        if previous['asset_id']==item['asset_id']:previous.update(state='unknown',note='结果出现重复条目，需核对')
                    continue
                seen.add(item['asset_id']);item=dict(item)
                state=item.get('state','unknown');evidence=Path(item.get('evidence') or '.')
                if item.get('verified_absent') is True and (not evidence.is_file() or evidence.suffix.lower() not in ['.png','.jpg','.jpeg','.webp'] or not evidence.resolve().is_relative_to(folder.resolve())):item['verified_absent']=False
                if state in ['scheduled','published','reviewing'] and (not evidence.is_file() or evidence.suffix.lower() not in ['.png','.jpg','.jpeg','.webp'] or not evidence.resolve().is_relative_to(folder.resolve())):state='unknown';item['note']='缺少有效后台凭证，需人工核验'
                if state in ['scheduled','published','reviewing'] and item.get('at')!=expected[item['asset_id']]:state='unknown';item['note']='后台结果时间与指定排期不一致，需核对'
                if item.get('platform_id') and not str(item['platform_id']).isdigit():state='unknown';item['note']='平台作品ID格式异常，需核对'
                if state not in ['scheduled','published','reviewing','failed','unknown','uploading']:state='unknown'
                item['state']=state;good.append(item)
            for item in good:
                a=next(a for a in assets if a['id']==item['asset_id']);a.update(state=item['state'],scheduled_at=item.get('at',''),platform_id=item.get('platform_id',''))
            if final:
                for a in assets:
                    if a['id'] in allowed and a['state'] in ['queued','uploading']:
                        a['state']='unknown';good=[x for x in good if x['asset_id']!=a['id']]+[dict(asset_id=a['id'],state='unknown',note='执行结束未取得明确结果，先核对平台队列')]
            self.s.set('assets',assets);self.update(job['id'],results=good)
    def stop(self):
        if self.active:
            self.cancel=True;self.update(self.active,state='stopping',message='正在停止；已提交的作品须保留并核对')
            if self.process:self.process.terminate()

    def verify(self,ident):
        with self.s.lock:
            if self.active:raise ValueError('请等当前任务完成')
            job=next(j for j in self.s.get('jobs') if j['id']==ident)
            self.active=ident;self.cancel=False;self.update(ident,state='running',message='只读核对平台结果，不会上传或提交')
            threading.Thread(target=self.run,args=(job,Path(job['folder']),'verify'),daemon=True).start()

    def release(self,ident):
        with self.s.lock:
            if self.active:raise ValueError('请等当前任务完成')
            jobs=self.s.get('jobs');j=next(j for j in jobs if j['id']==ident);released=0
            assets=self.s.get('assets')
            for r in j.get('results',[]):
                if r.get('state')=='failed' and r.get('verified_absent') is True:
                    a=next(a for a in assets if a['id']==r['asset_id'])
                    if a['state']=='failed':a['state']='ready';released+=1
            self.s.set('assets',assets)
            if not released:raise ValueError('没有已核实未提交的作品；请先点“核对平台结果”')
            return {'released':released}
