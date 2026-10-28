"""A frozen batch, executed serially with per-item receipts and bounded waits."""
import datetime as dt
import base64
import hashlib
import copy
import json
import queue
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from engine import now, TZ
from rules import BLOCKING_JOB_STATES, LIMITS, compose_caption, validate

ACCEPTED={'scheduled','published','reviewing'}
VERIFIED=ACCEPTED|{'duplicate'}
RECOVERABLE_CONNECTION={'browser_connection_unverified_after_upload','browser_connection_lost','browser_connection_unstable'}
CONTINUE=VERIFIED|{'duplicate_pending','item_failed'}
STAGES={'preparing','connecting','checking','choosing','uploading','filling','submitting','verifying'}
MUTATING={'uploading','filling','submitting','verifying'}

def save_browser_images(event,folder):
    """Persist actual tool screenshots; never treat them alone as submission proof."""
    if event.get('type')!='mcp_tool_call' or event.get('status')!='completed':return
    result=event.get('result') or {}
    if not isinstance(result,dict):return
    for block in result.get('content',[]):
        if not isinstance(block,dict):continue
        extension={'image/jpeg':'jpg','image/png':'png','image/webp':'webp'}.get(block.get('mimeType'))
        if block.get('type')!='image' or not extension:continue
        encoded=block.get('data','')
        if not isinstance(encoded,str) or len(encoded)>14_000_000:continue
        try:raw=base64.b64decode(encoded,validate=True)
        except (ValueError,TypeError):continue
        valid=raw.startswith(b'\xff\xd8\xff') if extension=='jpg' else raw.startswith(b'\x89PNG\r\n\x1a\n') if extension=='png' else raw.startswith(b'RIFF') and raw[8:12]==b'WEBP'
        if valid:
            try:(folder/('browser-shot-'+hashlib.sha256(raw).hexdigest()[:16]+'.'+extension)).write_bytes(raw)
            except OSError:pass

class BatchPublisher:
    def __init__(self,runner):self.r=runner;self.s=runner.s

    def resume(self,ident):
        """Continue a freshly inspected original upload without re-selecting it."""
        with self.s.lock:
            if self.r.active or getattr(self.s,'dedup_busy',False):raise ValueError('请等当前任务结束')
            jobs=self.s.get('jobs',[]);job=next(j for j in jobs if j['id']==ident)
            if not job.get('batch') or job['state']!='attention':raise ValueError('只能恢复已核对原上传页的暂停批次')
            if any(j['id']!=ident and j['state'] in BLOCKING_JOB_STATES for j in jobs):raise ValueError('请先处理其他未完成任务')
            result=next(r for r in job['results'] if r['asset_id']==job['current_asset_id'])
            if not (result.get('state')=='unknown' and result.get('reason_code') in RECOVERABLE_CONNECTION and result.get('upload_started') is True and result.get('submission_started') is False):raise ValueError('本篇不满足原页恢复条件，不能自动重传')
            old=Path(result['attempt_folder']);check=json.loads((old/'recovery-check.json').read_text(encoding='utf-8-sig'))
            observed=dt.datetime.fromisoformat(check.get('observed_at',''))
            if observed.tzinfo is None or not now()-dt.timedelta(minutes=30)<=observed<=now():raise ValueError('原页核对已过期，请重新只读核对')
            manifest=json.loads((Path(job['folder'])/'queue.json').read_text(encoding='utf-8'))
            assets={a['id']:a for a in self.s.get('assets',[])};first=assets[result['asset_id']]
            proof={**check,'evidence':str(old/'recovery-check.jpg')}
            if not (check.get('connection_ok') is True and check.get('upload_complete') is True and check.get('page_status')=='editor_upload_complete' and check.get('account')==manifest['account']==self.s.account() and check.get('file')==first['name'] and self.r._proof(proof,old,dict(account=manifest['account'],attempt_started_at=job['attempt_started_at'])) and str(check.get('tab_id','')).isdigit()):raise ValueError('缺少本篇原上传页与账号对应的新核对凭证')
            status={r['asset_id']:r['state'] for r in job['results']};items=[]
            for item in manifest['items']:
                asset_id=item['asset_id']
                if asset_id!=result['asset_id'] and status.get(asset_id)!='not_started':continue
                prepared=Path(job['folder'])/'prepared'/(asset_id+'.json')
                if manifest.get('auto_prepare') and prepared.is_file():
                    resolved_item=json.loads(prepared.read_text(encoding='utf-8'))
                    if any(resolved_item.get(k)!=item.get(k) for k in ['slot','asset_id','at']):raise ValueError('自动匹配记录与冻结排期不一致')
                    item=resolved_item
                a=assets[asset_id]
                if a['state']!=('unknown' if asset_id==result['asset_id'] else 'ready'):raise ValueError('作品状态已变化，不能恢复重复发布')
                from dedup import require_unchanged
                require_unchanged(a)
                expected=item['asset'];normalized=validate(a,for_execution=True)
                if any(value!=expected[key] for key,value in normalized.items()):raise ValueError('原批次发布内容已变化，不能静默恢复')
                if any(a.get(k)!=expected.get(k) for k in ['video','cover','name']):raise ValueError('原批次素材已变化，不能恢复')
                row=next((r for r in self.s.get('plan',[]) if r['slot']==item['slot']),None)
                if not row or row['asset_id']!=asset_id or row['at']!=item['at']:raise ValueError('原批次排期已变化，不能恢复')
                items.append(item)
            if not items or items[0]['asset_id']!=result['asset_id']:raise ValueError('原批次顺序不匹配')
            started=json.loads((old/'events.jsonl').read_text(encoding='utf-8').splitlines()[0]);thread=started.get('thread_id','');uuid.UUID(thread)
            job.setdefault('recovery_history',[]).append(dict(result=result,check=check,at=now().isoformat()))
            job.update(state='running',mode='batch_publish',browser_thread_id=thread,resume_existing_asset=result['asset_id'],resume_tab_id=str(check['tab_id']),message='原视频已上传完成，沿用原编辑页继续；不会重复上传',last_activity_at=now().isoformat())
            wanted={x['asset_id'] for x in items}
            for row in job['results']:
                if row['asset_id'] in wanted:
                    row.update(state='queued',note='等待沿原批次继续处理');assets[row['asset_id']]['state']='queued'
            self.s.set('jobs',jobs);self.s.set('assets',list(assets.values()));self.r.active=job['id'];self.r.cancel=False
            threading.Thread(target=self.run,args=(job,manifest,items,'batch_publish'),daemon=True).start()
            return job

    def start(self,slots,executor,revision,auto_prepare=False):
        with self.s.lock:
            if getattr(self.s,'dedup_busy',False):raise ValueError('本地查重中，请等完成后再发布')
            if not revision or revision!=self.s.preparation_revision():raise ValueError('发布明细已变化，请重新打开整批确认页')
            if self.r.active or any(j['state'] in BLOCKING_JOB_STATES for j in self.s.get('jobs',[])):raise ValueError('还有结果不明或正在执行的任务，请先处理，避免重复提交')
            if not self.s.account():raise ValueError('请先填写预期账号')
            if not isinstance(slots,list) or not slots or len(slots)!=len(set(slots)):raise ValueError('请选择不重复的排期')
            if not self.r.health()['available']:raise ValueError('未找到本机 Codex')
            rows=sorted([r for r in self.s.get('plan') if r['slot'] in slots],key=lambda r:r['at'])
            if len(rows)!=len(slots):raise ValueError('排期已变化，请刷新')
            assets={a['id']:a for a in self.s.get('assets')};items=[];policy=self.s.schedule_policy();current=now()
            self.s.unique_assets([assets[row['asset_id']] for row in rows])
            for row in rows:
                a=assets[row['asset_id']]
                if a['state']!='ready':raise ValueError('作品已锁定或已提交：'+a['name'])
                from dedup import require_unchanged, signature
                if not auto_prepare:require_unchanged(a)
                normalized=validate({**a,'title':''} if auto_prepare else a,for_execution=not auto_prepare)
                if auto_prepare:normalized['title']=a.get('title','')
                at=dt.datetime.strptime(row['at'],'%Y-%m-%d %H:%M').replace(tzinfo=TZ)
                if not current+dt.timedelta(minutes=policy['lead_minutes'])<=at<=current+dt.timedelta(days=policy['window_days']):raise ValueError('排期不在本地预检窗口，请调整：'+row['at'])
                if not auto_prepare and not Path(a['video']).is_file():raise ValueError('视频文件不存在：'+a['name'])
                if not auto_prepare and a.get('cover') and not Path(a['cover']).is_file():raise ValueError('封面文件不存在：'+a['name'])
                public={k:a[k] for k in ['id','video','name','cover','duration'] if k in a}
                public.update(normalized,composed_caption=compose_caption(normalized['caption'],normalized['tags']))
                item=dict(**row,asset=public)
                if auto_prepare:
                    item['preparation_signature']=signature(a['video']) if Path(a['video']).is_file() else None
                    item['preparation_cover_signature']=signature(a['cover']) if a.get('cover') and Path(a['cover']).is_file() else None
                items.append(item)
            ident=uuid.uuid4().hex[:12];folder=self.s.root/'jobs'/ident;folder.mkdir(parents=True)
            manifest=dict(job_id=ident,platform='xiaohongshu',account=self.s.account(),timezone='Asia/Shanghai',executor=executor,limits=LIMITS,schedule_policy=policy,auto_prepare=bool(auto_prepare),preparation_policy='逐篇在上传前从本视频与对应原稿匹配源内标题、已有封面或本片原帧；保留手工设置，缺可靠来源单独跳过，不改变账号/排期/正文' if auto_prepare else '',authorized_by='用户确认整批指定内容及排期，授权依次上传、提交和只读核验；重复项单独隔离，其余继续；登录风控或提交不明即停，不自动重传',items=items)
            (folder/'queue.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
            stamp=now().isoformat()
            job=dict(id=ident,batch=True,state='running',mode='batch_publish',created_at=stamp,updated_at=stamp,last_activity_at=stamp,count=len(items),items=[x['asset_id'] for x in items],folder=str(folder),executor=executor,current_index=1,current_asset_id=items[0]['asset_id'],stage='connecting',message='正在启动整批发布，按排期顺序执行',results=[dict(asset_id=x['asset_id'],state='queued',note='尚未开始') for x in items])
            for item in items:assets[item['asset_id']]['state']='queued'
            self.s.set('assets',list(assets.values()));jobs=self.s.get('jobs',[]);jobs.insert(0,job);self.s.set('jobs',jobs)
            self.r.active=ident;self.r.cancel=False
            threading.Thread(target=self.run,args=(job,manifest,items,'batch_publish'),daemon=True).start()
            return job

    def set_result(self,job,result):
        with self.s.lock:
            jobs=self.s.get('jobs');saved=next(j for j in jobs if j['id']==job['id'])
            previous=next((r for r in saved['results'] if r['asset_id']==result['asset_id']),{})
            confirmed=previous if previous.get('state') in ACCEPTED else previous.get('previous_confirmed')
            if confirmed and result['state'] not in ACCEPTED:
                result={**result,'previous_confirmed':confirmed}
                if result['state']=='not_uploaded':result.update(state='unknown',note='此前有已核验提交凭证，本次未找到对应记录；保留原凭证，不能直接重传。')
            saved['results']=[result if r['asset_id']==result['asset_id'] else r for r in saved['results']]
            saved['updated_at']=now().isoformat()
            assets=self.s.get('assets');a=next(a for a in assets if a['id']==result['asset_id'])
            state=result['state'];a['state']='ready' if state in {'not_started','not_uploaded','item_failed'} else 'queued' if state=='preparing' else 'uploading' if state in STAGES else state
            if confirmed and state not in ACCEPTED:a['state']=confirmed['state']
            if state in ACCEPTED|{'duplicate'}:
                a.update(platform_id=result['platform_id'],scheduled_at=result['platform_at'],dedup_evidence=result.get('note',''))
            self.s.set('assets',assets);self.s.set('jobs',jobs)

    def run(self,job,manifest,items,mode):
        try:
            for index,item in enumerate(items,1):
                if self.r.cancel:break
                self.r.update(job['id'],current_index=index,current_asset_id=item['asset_id'],stage='connecting',message=('正在核对平台结果' if mode=='verify' else '正在连接小红书并核对内容'),last_activity_at=now().isoformat())
                if mode!='verify' and manifest.get('auto_prepare') and job.get('resume_existing_asset')!=item['asset_id']:
                    try:item=self.prepare_item(job,item)
                    except Exception as exc:
                        self.set_result(job,dict(asset_id=item['asset_id'],state='item_failed',block_scope='item',reason_code='preparation_unresolved',upload_started=False,submission_started=False,note='本篇自动匹配未完成，未上传：'+str(exc)))
                        continue
                    if self.r.cancel:
                        self.set_result(job,dict(asset_id=item['asset_id'],state='not_uploaded',upload_started=False,submission_started=False,note='用户在本地匹配期间停止；本篇未上传'))
                        break
                result=self.execute(job,manifest,item,index,mode)
                self.set_result(job,result)
                if result['state'] not in CONTINUE:break
        except Exception as exc:
            self.r.update(job['id'],message='执行中断：'+str(exc))
        finally:
            saved=next(j for j in self.s.get('jobs') if j['id']==job['id'])
            # Only untouched queue entries can be returned to the local plan.
            for result in saved['results']:
                if result['state']=='queued':self.set_result(job,dict(asset_id=result['asset_id'],state='not_started',note='本批次在此篇开始前已暂停；未上传'))
                elif result['state']=='preparing':self.set_result(job,dict(asset_id=result['asset_id'],state='not_uploaded',upload_started=False,note='本地匹配中断；本篇未上传'))
                elif result['state'] in STAGES:self.set_result(job,dict(asset_id=result['asset_id'],state='unknown',note='执行中断，需先核对结果，不能重传'))
            saved=next(j for j in self.s.get('jobs') if j['id']==job['id']);results=saved['results']
            submitted=sum(r['state'] in ACCEPTED or bool(r.get('previous_confirmed')) for r in results);duplicates=sum(r['state']=='duplicate' for r in results);held=sum(r['state']=='duplicate_pending' for r in results);failed=sum(r['state']=='item_failed' for r in results)
            uncertain=any(r['state'] in {'unknown','awaiting_manual'} for r in results)
            complete=all(r['state'] in CONTINUE for r in results)
            state=('completed_with_skips' if held or failed else 'completed') if complete else 'attention' if uncertain else 'paused'
            self.r.update(job['id'],state=state,stage='done' if complete else 'paused',completed_at=now().isoformat(),updated_at=now().isoformat(),message=f'本次已向小红书提交 {submitted} 篇；已核实旧作跳过 {duplicates} 篇；疑似重复待核对 {held} 篇；单篇失败 {failed} 篇（未上传，未设置定时，可单独重试）。'+('其余条目已处理完。' if complete else '未开始的条目未上传、未设置平台定时；暂停原因见对应视频。'))
            self.r.active=None;self.r.process=None

    def prepare_item(self,job,item):
        from field_resolver import resolve_asset
        from dedup import signature
        def progress(note):
            if self.r.cancel:raise ValueError('用户已停止本地匹配')
            self.set_result(job,dict(asset_id=item['asset_id'],state='preparing',note=note,upload_started=False,submission_started=False))
            self.r.update(job['id'],stage='preparing',message=note,last_activity_at=now().isoformat())
        with self.s.lock:
            original=next(a for a in self.s.get('assets',[]) if a['id']==item['asset_id'])
            if not Path(original['video']).is_file() or signature(original['video'])!=item.get('preparation_signature'):raise ValueError('视频不存在或版本已变化，请重新查重')
            if item.get('preparation_cover_signature') and (not Path(original.get('cover','')).is_file() or signature(original['cover'])!=item['preparation_cover_signature']):raise ValueError('原确认封面的文件版本已变化；本篇未上传')
            fields=['video','cover','name','title','caption','tags','settings']
            scope={**original,**validate({**original,'title':''})};scope['title']=original.get('title','')
            if any(scope.get(k)!=item['asset'].get(k) for k in fields):raise ValueError('本篇字段已变化，不能静默扩大原批次')
            original=copy.deepcopy(original)
        resolved=resolve_asset(self.s,original,job['executor']['model'],progress)
        normalized=validate(resolved,for_execution=True)
        public={k:resolved[k] for k in ['id','video','name','cover','duration'] if k in resolved}
        public.update(normalized,composed_caption=compose_caption(normalized['caption'],normalized['tags']))
        outcome={**item,'asset':public,'preparation_evidence':{k:resolved.get(k) for k in ['title_source','cover_source','ai_confirmation']}}
        with self.s.lock:
            assets=self.s.get('assets',[]);current=next(a for a in assets if a['id']==item['asset_id'])
            if signature(current['video'])!=item['preparation_signature'] or any(current.get(k)!=original.get(k) for k in fields):raise ValueError('匹配过程中素材或设置发生变化；本篇未上传')
            if item.get('preparation_cover_signature') and signature(current['cover'])!=item['preparation_cover_signature']:raise ValueError('匹配过程中原封面变化；本篇未上传')
            current.update({k:v for k,v in resolved.items() if k not in {'state','selected'}})
            sources=self.s.get('preparation_sources',{});sources[item['asset_id']]={**sources.get(item['asset_id'],{}),'signature':signature(current['video']),'title':current['title'],'title_source':current.get('title_source',''),'cover':current.get('cover',''),'cover_source':current.get('cover_source','')}
            with self.s.connect() as connection:
                connection.executemany('INSERT OR REPLACE INTO kv VALUES (?,?)',[('assets',json.dumps(assets,ensure_ascii=False)),('preparation_sources',json.dumps(sources,ensure_ascii=False))])
            path=Path(job['folder'])/'prepared';path.mkdir(exist_ok=True)
            (path/(item['asset_id']+'.json')).write_text(json.dumps(outcome,ensure_ascii=False,indent=2),encoding='utf-8')
        return outcome

    def execute(self,job,manifest,item,index,mode):
        if mode!='verify':
            at=dt.datetime.strptime(item['at'],'%Y-%m-%d %H:%M').replace(tzinfo=TZ)
            policy=manifest['schedule_policy'];current=now()
            if not current+dt.timedelta(minutes=policy['lead_minutes'])<=at<=current+dt.timedelta(days=policy['window_days']):
                return dict(asset_id=item['asset_id'],state='item_failed',block_scope='item',reason_code='schedule_expired',note='轮到本篇时计划时间已不在本地准备窗口，请调整排期；未上传')
        context={**manifest,'items':[item],'mode':mode,'batch_index':index,'batch_count':job['count'],'attempt_started_at':now().isoformat(),'resume_existing_upload':mode!='verify' and job.get('resume_existing_asset')==item['asset_id'],'resume_tab_id':job.get('resume_tab_id')}
        folder=Path(job['folder'])/'attempts'/uuid.uuid4().hex[:12];folder.mkdir(parents=True)
        (folder/'queue.json').write_text(json.dumps(context,ensure_ascii=False,indent=2),encoding='utf-8')
        self.r.update(job['id'],attempt_folder=str(folder),attempt_started_at=context['attempt_started_at'])
        events=queue.Queue();started=time.monotonic();last_activity=started;last_content=None;mutation=context['resume_existing_upload'];reason='';process=None
        try:
            with (folder/'events.jsonl').open('w',encoding='utf-8') as log,(folder/'errors.log').open('w',encoding='utf-8') as err:
                process=subprocess.Popen(self.r.command(job,folder),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,text=True,encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));self.r.process=process
                process.stdin.write(self.prompt(folder,mode));process.stdin.close()
                def read_output():
                    try:
                        for line in process.stdout:events.put(line)
                    finally:events.put(None)
                reader=threading.Thread(target=read_output,daemon=True);reader.start()
                while True:
                    try:
                        line=events.get(timeout=.5)
                        if line:
                            log.write(line);log.flush();last_activity=time.monotonic()
                            self.r.update(job['id'],last_activity_at=now().isoformat())
                            try:
                                message=json.loads(line)
                                if message.get('type')=='thread.started' and message.get('thread_id'):
                                    uuid.UUID(message['thread_id']);self.r.update(job['id'],browser_thread_id=message['thread_id'])
                                event=message.get('item',{})
                                save_browser_images(event,folder)
                                if event.get('type')=='agent_message':self.r.update(job['id'],message=event.get('text','')[:600])
                            except (ValueError,TypeError,AttributeError):pass
                    except queue.Empty:pass
                    try:
                        content=(folder/'progress.json').read_text(encoding='utf-8-sig')
                        if content!=last_content:
                            report=json.loads(content);last_content=content;last_activity=time.monotonic()
                            raw=next(x for x in report.get('items',[]) if x.get('asset_id')==item['asset_id'])
                            stage=raw.get('stage',raw.get('state'))
                            mutation=mutation or raw.get('upload_started') is True or raw.get('submission_started') is True or (mode!='verify' and stage in MUTATING)
                            if stage in STAGES:
                                self.set_result(job,dict(asset_id=item['asset_id'],state=stage,note=str(raw.get('note',''))[:600],upload_started=mutation))
                                self.r.update(job['id'],stage=stage,message=str(raw.get('note',''))[:600],last_activity_at=now().isoformat())
                    except (OSError,ValueError,TypeError,AttributeError,StopIteration):pass
                    if process.poll() is not None:break
                    if self.r.cancel:reason='用户停止本批次';process.terminate();break
                    if time.monotonic()-last_activity>int(self.s.config.get('executor_idle_timeout_seconds',300)):
                        reason='执行器超过 5 分钟无新响应，已停止；请检查浏览器连接';process.terminate();break
                    if time.monotonic()-started>int(self.s.config.get('executor_item_timeout_seconds',1800)):
                        reason='本篇执行超时，已停止；请核对平台结果';process.terminate();break
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=10)
                reader.join(timeout=1)
            try:raws=json.loads((folder/'result.json').read_text(encoding='utf-8-sig'))['items']
            except (OSError,ValueError,KeyError):raws=[]
            if len(raws)==1 and isinstance(raws[0],dict) and raws[0].get('asset_id')==item['asset_id']:
                return self.receipt(raws[0],folder,context,mutation,mode)
            return dict(asset_id=item['asset_id'],state='unknown',note=reason or '执行结束但没有可核实的结果；先核对，勿重传')
        except Exception as exc:
            return dict(asset_id=item['asset_id'],state='unknown' if process else 'not_uploaded',note='执行器未完成：'+str(exc))
        finally:
            if process and process.poll() is None:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=10)
            if process:
                if process.stdout:process.stdout.close()
                if process.stdin and not process.stdin.closed:process.stdin.close()
            self.r.process=None

    def receipt(self,raw,folder,manifest,mutation,mode):
        result=dict(raw);state=raw.get('state');expected=manifest['items'][0]['at'];error=''
        proof=self.r._proof(raw,folder,manifest)
        if state in VERIFIED:
            if not proof:error='缺少本次账号与时间对应的后台截图'
            elif not re.fullmatch(r'[0-9a-fA-F]{24}',str(raw.get('platform_id',''))):error='缺少实际平台作品 ID'
            elif raw.get('match_basis')!='continuous_frames_and_record':error='尚未核实同次录制与后台记录'
            elif not raw.get('platform_at'):error='缺少后台显示的实际时间'
            elif state!='duplicate' and (raw.get('at')!=expected or raw.get('platform_at')!=expected):error='后台时间与本次排期不一致'
            elif state=='duplicate' and mutation and mode!='verify':error='已经开始上传，不能认定为上传前跳过重复'
        elif state=='duplicate_pending':
            candidate=raw.get('pending_duplicate_record')
            if mode!='batch_publish' or mutation or raw.get('preflight_only') is not True or raw.get('upload_started') is not False or raw.get('submission_started') is not False:error='疑似重复条目已触及上传或缺少上传前记录，不能直接跳过'
            elif raw.get('block_scope')!='item' or raw.get('reason_code')!='duplicate_unconfirmed':error='未明确区分单篇查重问题与整批异常'
            elif not proof or not isinstance(candidate,dict) or not candidate.get('title'):error='缺少本次旧作候选与账号截图凭证'
        elif state=='item_failed':
            if mode!='batch_publish' or mutation or raw.get('preflight_only') is not True or raw.get('upload_started') is not False or raw.get('submission_started') is not False:error='单篇失败缺少未上传证据，需核对后再恢复'
            elif raw.get('block_scope')!='item' or raw.get('reason_code') not in {'filechooser_timeout','file_missing','schedule_expired'}:error='该异常影响整批，不能按单篇跳过'
            elif not proof or raw.get('file_selection_completed') is not False or raw.get('upload_page_empty') is not True:error='缺少本次空白上传页及未选入文件的凭证'
        elif state=='not_uploaded':
            if mode=='verify':
                if not (proof and raw.get('verified_absent') is True and raw.get('editor_closed') is True and {'scheduled','reviewing','published','drafts'}<=set(raw.get('checked_views',[]))):error='尚未确认平台未提交及无草稿残留'
            elif mutation or raw.get('preflight_only') is not True or raw.get('upload_started') is not False or raw.get('submission_started') is not False:error='缺少明确的上传前中断记录，不能解锁'
        elif state not in {'unknown','awaiting_manual'}:error='返回结果不完整，需核对'
        if error:result.update(state='unknown',validation_error=error,note=(str(raw.get('note',''))+'；'+error).lstrip('；'))
        result['attempt_folder']=str(folder);result['verified_mode']=mode
        return result

    def verify(self,ident):
        with self.s.lock:
            if self.r.active:raise ValueError('请等当前执行结束')
            job=next(j for j in self.s.get('jobs') if j['id']==ident)
            if any(j['id']!=ident and j['state'] in BLOCKING_JOB_STATES for j in self.s.get('jobs')):raise ValueError('请先处理正在执行的任务')
            wanted={r['asset_id'] for r in job['results'] if r['state'] in ACCEPTED|{'unknown','awaiting_manual'}}
            if not wanted:raise ValueError('没有需要核对的提交；未上传的内容可返回排期继续')
            manifest=json.loads((Path(job['folder'])/'queue.json').read_text(encoding='utf-8'))
            items=[x for x in manifest['items'] if x['asset_id'] in wanted]
            self.r.update(ident,state='running',mode='verify',message='只读核对结果，不会重传',updated_at=now().isoformat())
            self.r.active=ident;self.r.cancel=False
            threading.Thread(target=self.run,args=(job,manifest,items,'verify'),daemon=True).start()
            return job

    def prompt(self,folder,mode):
        skill=Path(__file__).resolve().parents[2]/'SKILL.md'
        context=json.loads((folder/'queue.json').read_text(encoding='utf-8'))
        recovery=''
        if context.get('resume_existing_upload'):
            recovery=f'''这是原批次的恢复执行，上一轮只读诊断已经结束。主任务刚核实原标签页 {context['resume_tab_id']} 的账号和文件一致，上传已完成且未最终提交；已有标题或封面弹窗可能保留。本次恢复原先用户已确认的batch_publish权限。必须先回读这一个原编辑页，确认账号、文件和未提交状态仍一致，再从填写阶段继续；不要重新上传/选择文件，不关闭、刷新、导航或另开编辑页，不重复做已完成的上传前搜索。立即在本次progress写upload_started=true，submission_started=false。当前不是重传任务，不能返回not_uploaded；无法确认原页则unknown并停止。只填当前queue的字段及时间，回读后可按原授权最终提交一次并核验。所有新证据/result/progress都写本次目录 {folder}，不能沿用前次结果或截图。\n'''
        base=recovery+f'''读取 {skill} 及 {folder/'queue.json'}。这是用户已确认整批中的一篇，编排器负责顺序推进；只处理本次清单这一篇，先前单篇或只读任务已经结束。使用当前宿主 cua_repl 正常浏览器页面。禁止 Superpowers、子代理、私有 API、Cookie 提取、检测规避或模拟互动。优先复用本批次已登录的 Chrome 和同一浏览器会话；先查标签页。不接管其他会话占用的标签，也不另开编辑页替代仍未核实的原编辑页。任何登录、验证码、风险限制、明确禁止辅助操作、连接失效时立即停下，不循环重试。
任务开始及每个阶段更新 {folder/'progress.json'}，使用 items 数组，字段 asset_id, stage, note, upload_started, submission_started。stage 依次 connecting/checking/choosing/uploading/filling/submitting/verifying。打开文件选择窗口前写 choosing、file_selection_attempted=true，upload_started=false。调用文件选择器 setFiles 之前才写 uploading、upload_started=true；点击最终提交之前必须先写 submission_started=true。不要把模型思考或空等待称为上传进度；无法取得百分比时只写阶段。长上传有页面变化时更新进度，不能伪造活动。
结束必须写 {folder/'result.json'}，格式 {{"items":[{{"asset_id":"ID","state":"状态","at":"排期","account":"实际账号","observed_at":"带时区ISO时间","evidence":"本目录新截图绝对路径","note":"给用户的明确结论"}}]}}。截图保留账号与对应记录周边页面，不引用旧图。不要写数据库。任何失败应先写结果再结束，不留下只说完成的文本。
'''
        if mode=='verify':return base+'''本次仅只读核验，不得上传、编辑、提交或保存草稿。匹配后台记录的连续画面、作品 ID 和实际时间。返回 scheduled/published/reviewing 须写 platform_id, platform_at, match_basis=continuous_frames_and_record。查明是更早的同次录制返回 duplicate（旧作时间必须照实）。无法确认返回 unknown。仅当定时、审核、已发、草稿均核查且先前编辑页关闭，无提交无残留时可返回 not_uploaded，附 verified_absent=true, editor_closed=true, checked_views 四类列表。'''
        return base+'''用户已授权这篇按清单时间上传、填写、点击最终定时提交并核验，不再逐篇询问。只能使用清单标题、caption、tags、已有封面及设置，不能生成或改写文案。标题20、正文含话题1000、话题最多10，页面更严格则停。AI声明用用户已确认事实，保留平台标识。缺少可选下载开关如实记不支持，不阻断；必要声明、定时能力、账号或时间不符则停，不改成立即发布。
先核实账号及本篇是否已发。定时控件通常在视频上传后才显示：上传前未显示定时控件，不代表不支持定时，也不是停止理由；用户已授权上传，可先上传本篇，再在最终提交前核实定时能力、窗口及指定时刻。检索只限本篇必要范围，不全量翻历史。标题相同仅是线索；如发现同次录制的已有作品，保存实际连续画面与记录凭证，返回 duplicate 并写旧作 platform_id、platform_at、match_basis=continuous_frames_and_record，不再上传此篇。若标题/封面点击不能打开旧视频，可用卡片当前可见的“编辑”入口只读查看预览，播放至少两个不同位置与本地成片核对；不改旧稿、不提交，核对后离开。不要只因标题相近判定重复。若仍无法判断，返回 duplicate_pending，附 block_scope=item, reason_code=duplicate_unconfirmed, preflight_only=true, upload_started=false, submission_started=false, pending_duplicate_record={title,platform_at,platform_id}（未取得字段留空）及本次账号和候选记录截图；编排器只隔离本篇并自动继续其余内容。登录、账号不符、验证码、连接故障、风控仍必须返回 not_uploaded 或 unknown 并停止整批，不能冒充单篇重复问题。
若登录或其他错误发生在选文件之前，且从未上传/填写/提交，返回 not_uploaded 并明确 preflight_only=true, upload_started=false, submission_started=false；这不要求去平台证明不存在历史笔记。已经上传或可能提交时返回 unknown，不可自动重传。
视频 setFiles 后先只读等待本条实际上传完成（百分比消失且当前文件的完整视频预览/高清检测就绪），再打开封面编辑器；上传尚未完成时不要打开封面或启动第二个文件选择器。封面文件选择器等待须立即绑定错误处理，并用 Promise.all 同时等待按钮点击与 filechooser，不能留下未捕获的 Promise rejection 导致浏览器内核重置。若操作超时先只读核对原页，禁止重传。
如果宿主当前视口极小，导致实际提交栏被裁掉且正常滚动也无法操作，使用文档化 viewport 能力临时恢复可操作的桌面布局（如1440×900），不以普通DOM中缺按钮文字为由停止；原生截图中可见的真实按钮可按截图坐标操作，禁止脚本伪造点击，最终提交仍只点击一次。完成后恢复默认视口。
浏览器截图输出 emitImage 后，主工作台会将真实图片自动保存到本次目录 browser-shot-*.jpg/png；可用终端列出实际文件并在结果中引用，不要为寻找工具未提供的截图保存方法停批。截图只是证据材料，不能代替平台提交凭证。已有原页字段和预检已核实的恢复任务，不要重新打开无关的智能章节或推荐弹窗；直接核对当前实际已添加数量。若已在章节弹窗且显示已添加0个，只关闭弹窗，不点击生成/应用/保存。
文件选择器必须按当前工具文档注册等待，再点击当前页面可见的“上传视频”按钮，不能把隐藏 input 的“选择文件”文字当作有效按钮。等待窗口使用合理超时（例如30秒），先绑定窗口再设置文件。若窗口超时，尚未调用 setFiles、未填表未提交且页面仍为空白上传页，保存新截图，返回 item_failed，block_scope=item, reason_code=filechooser_timeout, preflight_only=true, upload_started=false, submission_started=false, file_selection_completed=false, upload_page_empty=true；本篇跳过，其余自动继续。任何 setFiles 已调用后的错误都不能声称未上传。登录/连接/验证码/风控仍停整批，不归为单篇失败。
通过预检后上传一篇、选择真实话题节点、回读全部字段及定时时间，然后点击最终定时提交一次；按实际成功页面及后台记录核验。返回 scheduled/published/reviewing，附实际 platform_id、platform_at、match_basis=continuous_frames_and_record。若页面需用户验证码或额外授权，停止并报告；提交后连接中断返回 unknown，不能再点提交。上传成功不是提交成功，已定时不是已公开。之后结束，由编排器决定下一篇。'''
