"""Prepare one note; only a later read-only verification can confirm publication."""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import threading
import uuid
from pathlib import Path
from engine import now, TZ
from rules import BLOCKING_JOB_STATES, LIMITS, compose_caption, validate

MODELS={'gpt-6-astra':'GPT-Astra','gpt-6-sol':'GPT-6','gpt-6.1-sol':'GPT-6.1 Sol'}
DEFAULT_MODEL='gpt-6-astra'
EFFORTS={'medium':'中','high':'高','xhigh':'极高'}
SUCCESS_STATES={'scheduled','published'}
PREPARE_CHECKS={'account','video','fields','schedule_window','ai_declaration'}
VERIFY_VIEWS={'scheduled','reviewing','published','drafts'}

def execution(model=None,reasoning_effort=None):
    model=model or DEFAULT_MODEL;reasoning_effort=reasoning_effort or 'high'
    if model not in MODELS:raise ValueError('请选择 GPT-Astra、GPT-6 或 GPT-6.1 Sol')
    if reasoning_effort not in EFFORTS:raise ValueError('推理强度请选择中、高或极高')
    return dict(driver='Codex',model=model,reasoning_effort=reasoning_effort)

def resolve_codex(config):
    """Desktop updates replace versioned binaries; ignore stale configured paths."""
    for value in [config.get('codex'), shutil.which('codex')]:
        if value and Path(value).is_file():return str(Path(value))
    local=os.environ.get('LOCALAPPDATA')
    if local:
        root=Path(local)/'OpenAI'/'Codex'/'bin'
        candidates=[p for p in root.glob('*/codex.exe') if p.is_file()]
        if candidates:return str(max(candidates,key=lambda p:p.stat().st_mtime))
    return None

class Runner:
    def __init__(self,store):
        self.s=store;self.process=None;self.active=None;self.cancel=False
        jobs=self.s.get('jobs',[]);assets=self.s.get('assets',[])
        for job in jobs:
            if job['state'] in ['running','stopping']:
                job.update(state='attention',message='上次执行中断，请先只读核对平台；不要重复上传')
                if job.get('batch'):
                    for result in job.get('results',[]):
                        a=next(a for a in assets if a['id']==result['asset_id'])
                        if result['state']=='queued' and result['asset_id']!=job.get('current_asset_id'):
                            result.update(state='not_started',note='执行中断前尚未轮到本篇；未上传');a['state']='ready'
                        elif result['state']=='preparing':
                            result.update(state='not_uploaded',note='本地匹配意外中断；尚未上传');a['state']='ready'
                        elif result['state'] in ['queued','connecting','checking','uploading','filling','submitting','verifying']:
                            result.update(state='unknown',note='执行意外中断，需要核对当前篇，不能直接重传')
                            if not result.get('previous_confirmed'):a['state']='unknown'
                    continue
                for asset in assets:
                    if asset['id'] in job['items'] and asset['state'] in ['queued','uploading','awaiting_manual']:asset['state']='unknown'
        self.s.set('jobs',jobs);self.s.set('assets',assets)
    def health(self):
        path=resolve_codex(self.s.config)
        return dict(available=bool(path and Path(path).is_file()),message='整批确认，逐条提交并核验；异常即停',running=self.active,mode='batch_publish',batch_supported=True,default=execution(),models=[{'id':k,'name':v} for k,v in MODELS.items()],reasoning_efforts=[{'id':k,'name':v} for k,v in EFFORTS.items()])
    def _attempt(self,job,manifest,mode):
        folder=Path(job['folder'])/'attempts'/uuid.uuid4().hex[:12];folder.mkdir(parents=True)
        context={**manifest,'mode':mode,'attempt_started_at':now().isoformat()}
        (folder/'queue.json').write_text(json.dumps(context,ensure_ascii=False,indent=2),encoding='utf-8')
        job.update(mode=mode,attempt_folder=str(folder),attempt_started_at=context['attempt_started_at']);return folder
    def start(self,slots,model=None,reasoning_effort=None,expected_revision=None,mode='prepare',auto_prepare=False):
        if mode=='batch_publish':
            from batch_runner import BatchPublisher
            return BatchPublisher(self).start(slots,execution(model,reasoning_effort),expected_revision,auto_prepare)
        if mode!='prepare':raise ValueError('执行模式无效')
        with self.s.lock:
            if getattr(self.s,'dedup_busy',False):raise ValueError('本地查重中，请等完成后再发布')
            executor=execution(model,reasoning_effort)
            if not expected_revision or expected_revision!=self.s.preparation_revision():raise ValueError('准备明细已变化或缺少确认版本，请重新打开确认页核对后再准备')
            if self.active or any(j['state'] in BLOCKING_JOB_STATES for j in self.s.get('jobs',[])):raise ValueError('当前作品尚待手工提交或核验；完成并核验后才能准备下一条')
            if not self.s.account():raise ValueError('请先核实小红书当前登录账号，并在工作台填写预期账号')
            if not isinstance(slots,list) or len(slots)!=1:raise ValueError('每次只能准备一条作品，不能批量托管发布')
            if not self.health()['available']:raise ValueError('未找到本机Codex，请先安装并登录')
            assets={a['id']:a for a in self.s.get('assets')};rows=[r for r in self.s.get('plan') if r['slot']==slots[0]]
            if len(rows)!=1:raise ValueError('请选择有效的单条排期')
            row=rows[0];asset=assets[row['asset_id']]
            if asset['state']!='ready':raise ValueError('作品已锁定或待核验，请勿重复准备')
            from dedup import require_unchanged
            require_unchanged(asset)
            normalized=validate(asset,for_execution=True)
            at=dt.datetime.strptime(row['at'],'%Y-%m-%d %H:%M').replace(tzinfo=TZ);policy=self.s.schedule_policy();current=now()
            if not current+dt.timedelta(minutes=policy['lead_minutes'])<=at<=current+dt.timedelta(days=policy['window_days']):raise ValueError(f"该时刻不满足本地预检窗口（提前{policy['lead_minutes']}分钟至{policy['window_days']}天）；请调整，后台仍需现场确认")
            if not Path(asset['video']).is_file():raise ValueError('视频文件已移动：'+asset['name'])
            if asset.get('cover') and not Path(asset['cover']).is_file():raise ValueError('封面文件已移动，请重新选择')
            # Never send a source manuscript, source path, or review body to the executor.
            publish_asset={k:asset[k] for k in ['id','video','name','cover','duration'] if k in asset}
            publish_asset.update(normalized,composed_caption=compose_caption(normalized['caption'],normalized['tags']))
            jobid=uuid.uuid4().hex[:12];root=self.s.root/'jobs'/jobid;root.mkdir(parents=True)
            manifest=dict(job_id=jobid,platform='xiaohongshu',account=self.s.account(),timezone='Asia/Shanghai',executor=executor,limits=LIMITS,schedule_policy=policy,authorized_by='用户确认仅准备本条表单，最后提交必须由用户在小红书操作',items=[dict(**row,asset=publish_asset)])
            (root/'queue.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
            job=dict(id=jobid,state='running',created_at=now().isoformat(),count=1,message='正在核对小红书账号并准备本条表单…',items=[asset['id']],folder=str(root),results=[],executor=executor)
            folder=self._attempt(job,manifest,'prepare');jobs=self.s.get('jobs',[]);jobs.insert(0,job);self.s.set('jobs',jobs)
            asset.update(normalized,state='queued');self.s.set('assets',list(assets.values()));self.active=jobid;self.cancel=False
            threading.Thread(target=self.run,args=(job,folder,'prepare'),daemon=True).start();return job
    def update(self,ident,**patch):
        with self.s.lock:
            jobs=self.s.get('jobs');job=next(j for j in jobs if j['id']==ident);job.update(patch);self.s.set('jobs',jobs)
    def prompt(self,folder,mode='prepare'):
        skill=Path(__file__).resolve().parents[2]/'SKILL.md'
        common=f'''先读取 {skill} 和 {folder/'queue.json'}。仅处理小红书指定账号和清单的一条视频。所有浏览器操作只用当前宿主cua_repl及其文档，不使用Superpowers或子代理。
禁止私有API、Cookie提取、指纹/stealth伪装、验证码绕过、随机拟人及规避平台检测。不得声称可以避免平台风控。遇到登录、验证码、风险提示或权限障碍即停止，保存证据，不重试绕过。
evidence必须是本次目录 {folder} 内新截图绝对路径，保留后台周围页面、账号与对应时间状态。account写实际看到的账号，observed_at用带时区ISO时间。不可凭本地清单推断成功，平台ID必须从后台取得，通常24位十六进制。
更新 {folder/'progress.json'}，结束写 {folder/'result.json'}，格式{{"items":[{{"asset_id":"清单ID","state":"状态","at":"清单原定时间","account":"实际账号","observed_at":"ISO时间","evidence":"本目录截图绝对路径","note":"实际观察"}}]}}。不要修改工作台数据库。无工具/证据就说明实际原因。最终中文说明用户下一步。'''
        if mode=='verify':return common+'''
本次只读核对用户手工提交后的结果。禁止上传、编辑、提交、改期、删除、创建/保存草稿或其他平台修改。先核对账号，再比较连续画面确认同一次录制；同文案不是同一视频。读取定时、审核、已发布、草稿列表，匹配真实作品ID、指定时间与状态。
state=scheduled|published|reviewing|failed|unknown。scheduled/published/reviewing须另写platform_id、platform_at（后台实际显示时间，应对应原定时刻）、match_basis="continuous_frames_and_record"，截图须对应。不得复制清单原定时间充当platform_at。
仅在所有列表均查过、确认未提交且没有草稿残留、用户已关闭或手工放弃先前编辑页时返回failed和verified_absent:true，另写checked_views:["scheduled","reviewing","published","drafts"]和editor_closed:true。仍有编辑页、草稿或证据不足一律unknown，不能解锁重传。'''
        return common+'''
权限仅prepare_single：核对、上传一条并填表，最后由用户提交。绝对禁止点击发布、确认发布、定时提交、保存草稿，也禁止通过快捷键或其他途径提交。工作台“准备”确认不授权平台发布。等待用户期间不得准备下一条。
上传前先核对账号和定时/审核/已发布/草稿列表，以实际连续画面避免重复；先确认本账号支持视频定时发布并验证时刻在后台允许窗口内。清单的提前60分钟至14天只是可配置本地参考，须当场核实。窗口不符、定时不可用、疑似重复或计数超限即停止，不得改为立即发布。
标题只用asset.title，正文只用asset.caption和tags，最终文本对照asset.composed_caption。不得读取/粘贴审查稿或原稿。话题0至10个，使用真实话题入口选择相关话题，不硬凑。标题本地UTF16保守20，正文含话题合计1000，还须检查实际网页计数，不得截断或删词。
按settings核对公开/仅自己可见，collection为空不加合集，非空只能选择已有指定合集；默认不加位置、活动，不开放下载。页面无下载选项应记明不支持，不能编造设置成功。没有原创、章节、热点等抖音选项。contains_ai必须使用平台真实AI声明；none表示用户确认视频、图像、正文均未使用AI生成、合成、润色或辅助创作，不表示规避标签；unknown必须停止。若平台要求额外文字声明而caption没有，暂停请用户编辑并重新计数，不得自行撰写。缺少所需AI声明入口时停止，保留平台自动AI标识与水印。
准备好后截图并返回state=awaiting_manual，checks中account/video/fields/schedule_window/ai_declaration各为实际核对后的true。请用户到小红书最后检查并提交，再回本地只读核验。不得返回scheduled/published，不得声称已建定时发布。准备过程可用uploading，不能完成用unknown。平台自行自动保存要如实报告，不主动保存草稿。
'''
    def command(self,job,folder):
        exe=resolve_codex(self.s.config)
        if not exe:raise ValueError('未找到本机 Codex，请检查安装')
        saved=job.get('executor',{});executor=execution(saved.get('model'),saved.get('reasoning_effort'))
        current=next((j for j in self.s.get('jobs',[]) if j['id']==job['id']),job)
        browser_thread=current.get('browser_thread_id')
        if browser_thread:
            uuid.UUID(browser_thread)
            return [exe,'exec','resume',browser_thread,'--model',executor['model'],'-c',f'model_reasoning_effort="{executor["reasoning_effort"]}"','--json','--skip-git-repo-check','--output-last-message',str(folder/'summary.txt'),'-']
        return [exe,'exec','--model',executor['model'],'-c',f'model_reasoning_effort="{executor["reasoning_effort"]}"','--json','--skip-git-repo-check','-C',str(folder),'--output-last-message',str(folder/'summary.txt'),'-']

    def resume(self,ident):
        from batch_runner import BatchPublisher
        return BatchPublisher(self).resume(ident)
    def run(self,job,folder,mode='prepare'):
        try:
            args=self.command(job,folder)
            with (folder/'events.jsonl').open('w',encoding='utf-8') as log,(folder/'errors.log').open('w',encoding='utf-8') as err:
                self.process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,text=True,encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                if self.cancel:self.process.terminate()
                else:self.process.stdin.write(self.prompt(folder,mode));self.process.stdin.close()
                for line in self.process.stdout:
                    log.write(line);log.flush()
                    try:
                        item=json.loads(line).get('item',{})
                        if item.get('type')=='agent_message':self.update(job['id'],message=item.get('text','')[:600])
                    except (ValueError,KeyError):pass
                    self.ingest(job,folder,False,mode)
                code=self.process.wait()
            self.ingest(job,folder,True,mode);self.finish(job,mode,code)
        except Exception as exc:
            self.update(job['id'],state='attention',message='执行未完成：'+str(exc));self.ingest(job,folder,True,mode)
        finally:self.active=None;self.process=None
    def finish(self,job,mode,code=0):
        results=next(j for j in self.s.get('jobs') if j['id']==job['id']).get('results',[])
        state='attention';message='结果尚未核实，请只读核对；不要重复上传。'
        if len(results)==1:
            result=results[0]
            if mode=='prepare' and result['state']=='awaiting_manual':state='awaiting_manual';message='表单已准备，等待你到小红书核对并最后提交；之后点击只读核验。'
            elif mode=='verify' and result['state'] in SUCCESS_STATES:state='completed';message='用户提交后的作品已在小红书后台核验；可以准备下一条。'
            elif mode=='verify' and result['state']=='reviewing':state='completed';message='已核实用户提交，平台仍在审核中，尚未确认公开；可以准备下一条。'
            elif mode=='verify' and result.get('verified_absent') is True:state='verified_absent';message='已核实未提交且编辑页已关闭，可恢复本条待准备状态。'
        self.update(job['id'],state=state,message=message,exit_code=code)
    @staticmethod
    def _proof(item,folder,manifest):
        try:
            path=Path(item.get('evidence') or '')
            if not path.is_absolute() or not path.resolve().is_relative_to(folder.resolve()) or not path.is_file():return False
            with path.open('rb') as stream:header=stream.read(16)
            if not (header.startswith(b'\x89PNG\r\n\x1a\n') or header.startswith(b'\xff\xd8\xff') or (header.startswith(b'RIFF') and header[8:12]==b'WEBP')):return False
            observed=dt.datetime.fromisoformat(item.get('observed_at',''));started=dt.datetime.fromisoformat(manifest['attempt_started_at'])
            return bool(item.get('account')==manifest['account'] and observed.tzinfo is not None and started<=observed<=now()+dt.timedelta(minutes=5))
        except (OSError,ValueError,TypeError,KeyError):return False
    def ingest(self,job,folder,final,mode=None):
        manifest=json.loads((folder/'queue.json').read_text(encoding='utf-8'));mode=mode or manifest['mode']
        if mode!=manifest['mode']:raise ValueError('核验模式与执行记录不一致')
        path=folder/'result.json' if (folder/'result.json').exists() else folder/'progress.json'
        try:
            items=json.loads(path.read_text(encoding='utf-8-sig')).get('items',[])
            if not isinstance(items,list):items=[]
        except (OSError,ValueError,AttributeError):items=[]
        with self.s.lock:
            assets=self.s.get('assets');allowed=set(job['items']);good=[];seen=set();expected={r['asset_id']:r['at'] for r in manifest['items']}
            for raw in items:
                if not isinstance(raw,dict) or raw.get('asset_id') not in allowed:continue
                item=dict(raw);ident=item['asset_id']
                if ident in seen:
                    for previous in good:
                        if previous['asset_id']==ident:previous.update(state='unknown',verified_absent=False,note='结果出现重复条目，需重新核对')
                    continue
                seen.add(ident);state=item.get('state','unknown');valid=self._proof(item,folder,manifest);failure=''
                if state in ['scheduled','published','reviewing']:
                    if mode!='verify':failure='准备阶段不能认定已经发布；须由用户提交后另行只读核验'
                    elif not valid:failure='缺少本次账号与时间对应的后台截图凭证'
                    elif item.get('at')!=expected[ident] or item.get('platform_at')!=expected[ident]:failure='后台时间与指定排期不一致'
                    elif not re.fullmatch(r'[0-9a-fA-F]{24}',str(item.get('platform_id',''))):failure='缺少有效的小红书后台作品ID'
                    elif item.get('match_basis')!='continuous_frames_and_record':failure='缺少同次录制画面与后台记录的匹配依据'
                elif state=='awaiting_manual':
                    checks=item.get('checks',{})
                    if mode!='prepare' or not valid or item.get('at')!=expected[ident] or not isinstance(checks,dict) or not all(checks.get(k) is True for k in PREPARE_CHECKS):failure='表单准备凭证或逐项核对不完整'
                elif state not in ['failed','unknown','uploading']:failure='返回状态无效'
                if failure:state='unknown';item['note']=failure
                item['verified_absent']=bool(state=='failed' and mode=='verify' and valid and item.get('verified_absent') is True and item.get('editor_closed') is True and isinstance(item.get('checked_views'),list) and all(isinstance(v,str) for v in item['checked_views']) and VERIFY_VIEWS<=set(item['checked_views']))
                if final and state=='uploading':state='unknown';item['note']='执行结束未取得准备或核验结果'
                item['state']=state;item['verified_mode']=mode;good.append(item)
            if final:
                for ident in allowed-seen:good.append(dict(asset_id=ident,state='unknown',verified_absent=False,verified_mode=mode,note='执行结束未取得明确结果；先只读核对平台与编辑页'))
            for item in good:
                asset=next(a for a in assets if a['id']==item['asset_id']);confirmed=item['state'] in SUCCESS_STATES|{'reviewing'}
                asset.update(state=item['state'],scheduled_at=item.get('platform_at','') if confirmed else '',platform_id=item.get('platform_id','') if confirmed else '')
            self.s.set('assets',assets);self.update(job['id'],results=good)
    def stop(self):
        if self.active:
            self.cancel=True;self.update(self.active,state='stopping',message='正在停止；随后需只读核对平台与仍打开的编辑页')
            if self.process:self.process.terminate()
    def verify(self,ident):
        if next(j for j in self.s.get('jobs') if j['id']==ident).get('batch'):
            from batch_runner import BatchPublisher
            return BatchPublisher(self).verify(ident)
        with self.s.lock:
            if self.active:raise ValueError('请等当前任务完成')
            if not self.health()['available']:raise ValueError('未找到本机Codex，请先安装并登录')
            jobs=self.s.get('jobs');job=next(j for j in jobs if j['id']==ident)
            if job['state'] not in ['awaiting_manual','attention','verified_absent','completed']:raise ValueError('这条任务不需要重复核验')
            if any(j['id']!=ident and j['state'] in BLOCKING_JOB_STATES for j in jobs):raise ValueError('请先结束当前锁定任务')
            manifest=json.loads((Path(job['folder'])/'queue.json').read_text(encoding='utf-8'));folder=self._attempt(job,manifest,'verify')
            job.update(state='running',results=[],message='只读核对用户提交后的结果，不会上传、编辑或提交');self.s.set('jobs',jobs)
            self.active=ident;self.cancel=False;threading.Thread(target=self.run,args=(job,folder,'verify'),daemon=True).start();return job
    def release(self,ident):
        with self.s.lock:
            if self.active:raise ValueError('请等当前任务完成')
            jobs=self.s.get('jobs');job=next(j for j in jobs if j['id']==ident);released=0
            if job['state']!='verified_absent':raise ValueError('先只读核验确认无提交和草稿且编辑页已关闭')
            assets=self.s.get('assets')
            for result in job.get('results',[]):
                if result.get('state')=='failed' and result.get('verified_absent') is True and result.get('verified_mode')=='verify':
                    asset=next(a for a in assets if a['id']==result['asset_id'])
                    if asset['state']=='failed':asset['state']='ready';released+=1
            if not released:raise ValueError('没有已核实未提交的作品；请先只读核对平台结果')
            job.update(state='released',message='已恢复待准备；再次准备前仍需核对平台新增记录')
            self.s.set('assets',assets);self.s.set('jobs',jobs);return {'released':released}
