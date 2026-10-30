"""Local, conservative media comparisons. No source writes or platform requests."""
import array
import hashlib
import json
import math
import re
import shutil
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from engine import now
from rules import BLOCKING_JOB_STATES

HISTORY = {'published', 'scheduled', 'reviewing', 'history', 'duplicate'}
EDITABLE = {'ready', 'duplicate_review', 'duplicate_checking'}
VERSION = 1


def decision_key(a, b):
    return hashlib.sha256(json.dumps(sorted([a, b])).encode()).hexdigest()+f'-v{VERSION}'


def review_revision(store):
    return hashlib.sha256(json.dumps([store.preparation_revision(), store.get('dedup_groups', [])], sort_keys=True).encode()).hexdigest()


def signature(path):
    p = Path(path); s = p.stat()
    return [str(p.resolve()).casefold(), s.st_size, s.st_mtime_ns]


def require_unchanged(asset):
    saved = asset.get('dedup_signature')
    if saved and signature(asset['video']) != saved:
        raise ValueError('视频文件在查重后发生变化，请重新查重：'+asset['name'])


def distance(a, b):
    return sum(abs(x-y) for x, y in zip(a, b)) / (255 * len(a))


def same_name(a, b):
    def key(a):
        name = Path(a['video']).stem.casefold()
        name = re.sub(r'(?:[_ -](?:v\d+|副本|copy|导出|最终版))+$', '', name)
        recording = re.search(r'(?:img|dsc|mov)[_-]?\d{4,}', name)
        return recording[0] if recording else name
    return key(a) == key(b) or bool(a.get('title') and a.get('title') == b.get('title'))


def visual_verdict(a, b, duration_a, duration_b, audio_match=False):
    """Sparse samples can prove strong matches, but cannot clear similar scenes."""
    if len(a) != 12 or len(b) != 12:
        return 'review', '抽帧不完整，继续隔离'
    aligned = [distance(x, y) for x, y in zip(a, b)]
    motion = min(sum(distance(x, y) for x, y in zip(seq, seq[1:]))/11 for seq in (a, b))
    if abs(duration_a-duration_b) <= .12 and max(aligned) < .008 and motion > .012 and audio_match:
        return 'duplicate', '12 处动态画面高度一致，时长一致且 3 段音频一致'
    # Every sample must differ from every other sample; shifted/re-edited clips
    # and same-background separate takes remain uncertain rather than auto-cleared.
    if all(distance(x, y) > .14 for x in a for y in b):
        return 'distinct', '12 处画面交叉比对均有明显差异'
    return 'review', '画面仍相似或音频/动态证据不足，继续隔离；同稿不同次拍摄不直接判重'


class DedupService:
    def clear_review(self, group_id, ident, revision):
        """User attestation for current local candidates, never a global whitelist."""
        with self.s.lock:
            if getattr(self.s, 'dedup_busy', False): raise ValueError('查重进行中，请稍后核对')
            if any(j['state'] in BLOCKING_JOB_STATES for j in self.s.get('jobs', [])):
                raise ValueError('请先结束当前发布任务')
            if not revision or revision != review_revision(self.s): raise ValueError('查重列表已变化，请刷新后重新核对')
            groups=self.s.get('dedup_groups', [])
            group=next((g for g in groups if g['id']==group_id), None)
            if not group or group.get('error') or not group.get('pairs'): raise ValueError('文件检查未完成，不能按不重复放行')
            if ident and ident not in group['ids']: raise ValueError('视频不在该组')
            assets=self.s.get('assets', []); byid={a['id']:a for a in assets}
            targets={ident} if ident else set(group['ids'])
            if any(byid[i]['state']!='duplicate_review' for i in targets):
                raise ValueError('只能解除本地疑似项，已提交或平台待核对项不能放行')
            facts={}
            for i in group['ids']:
                a=byid[i]
                if a.get('dedup_error'): raise ValueError('文件检查未完成，请先重新查重')
                saved_sig=a.get('dedup_signature') or a.get('dedup_reference_signature')
                if not saved_sig or signature(a['video'])!=saved_sig:
                    raise ValueError('文件已变化或缺少指纹，请重新查重')
                digest, sig=self.digest(a)
                if digest!=a.get('sha256'): raise ValueError('文件指纹已变化，请重新查重')
                facts[i]=(digest,sig)
            decisions=self.s.get('dedup_decisions', {}); audit=self.s.get('dedup_manual_reviews', [])
            stamp=now().isoformat(); ids=group['ids']
            for n,i in enumerate(ids):
                for j in ids[n+1:]:
                    if not targets.intersection([i,j]): continue
                    if facts[i][0]==facts[j][0]: raise ValueError('文件字节完全相同，不能解除重复拦截')
                    decisions[decision_key(facts[i][0],facts[j][0])]=dict(result='distinct',reason='用户已人工查看，确认不是重复视频',manual=True,signatures=sorted([facts[i][1],facts[j][1]]),confirmed_at=stamp)
            affected=set(); remaining=[]
            for g in groups:
                if g['id']!=group_id: remaining.append(g);continue
                pairs=[p for p in g['pairs'] if not targets.intersection(p['ids'])]
                affected.update(g['ids'])
                if pairs:
                    members=sorted({i for p in pairs for i in p['ids']})
                    remaining.append(dict(g, ids=members, pairs=pairs))
            held={i for g in remaining for i in g['ids']}; released=[]
            for i in affected-held:
                a=byid[i]
                if a['state']=='duplicate_review':
                    a.update(state='ready',selected=False,dedup='人工核对不重复',dedup_evidence='用户已查看本组视频并解除相关疑似关系',manual_review_at=stamp)
                    released.append(i)
            # Check again immediately before the atomic commit.
            for i,(_,sig) in facts.items():
                if signature(byid[i]['video'])!=sig: raise ValueError('文件在核对期间发生变化，请重新查重')
            audit.append(dict(group=group_id,targets=sorted(targets),released=released,confirmed_at=stamp,signatures={i:f[1] for i,f in facts.items()}))
            count=sum(a['state'] in {'duplicate_review','duplicate_checking'} for a in assets)
            values=dict(assets=assets,dedup_groups=remaining,dedup_decisions=decisions,dedup_manual_reviews=audit,dedup_status=dict(state='done',held=count,message=f'人工核对完成：恢复 {len(released)} 条可选视频，库存 {count} 条待排查'))
            with self.s.connect() as c:
                c.executemany('INSERT OR REPLACE INTO kv VALUES (?,?)',[(k,json.dumps(v,ensure_ascii=False)) for k,v in values.items()])
            return dict(released=released,held=count)

    def __init__(self, store):
        self.s = store
        self.thread = None
        self.cache = store.root/'dedup-cache'
        self.cache.mkdir(exist_ok=True)
        self.ffmpeg = store.config.get('ffmpeg') or shutil.which('ffmpeg')
        if not self.ffmpeg:
            sibling = Path(store.config.get('ffprobe', 'ffprobe')).with_name('ffmpeg.exe')
            if sibling.is_file(): self.ffmpeg = str(sibling)
        # A service interruption never returns unchecked videos to the library.
        if store.get('dedup_status', {}).get('state') == 'running':
            assets=store.get('assets', [])
            scope=set(store.get('dedup_scope', []))
            for a in assets:
                if a['state'] in EDITABLE and (not scope or a['id'] in scope): a['state']='duplicate_checking'
            store.set('assets', assets)
            store.set('dedup_status', {'state':'failed', 'message':'上次查重中断，请重新查重；未完成项保持隔离'})

    def start(self, group=None, folder=None):
        with self.s.lock:
            if getattr(self.s, 'dedup_busy', False): raise ValueError('查重正在进行，请等待当前结果')
            if any(j['state'] in BLOCKING_JOB_STATES for j in self.s.get('jobs', [])):
                raise ValueError('请先完成或核对当前发布任务，再开始本地查重')
            groups = self.s.get('dedup_groups', [])
            if group and group != 'all' and not any(g['id'] == group for g in groups):
                raise ValueError('疑似重复组已更新，请刷新')
            deep_ids = {i for g in groups if group == 'all' or g['id'] == group for i in g['ids']} if group else set()
            self.s.dedup_busy = True
            self.s.set('dedup_scope', sorted(deep_ids))
            self.progress('正在准备查重', 0, 0)
            try:
                self.thread = threading.Thread(target=self.run, args=(deep_ids, folder), daemon=True)
                self.thread.start()
            except BaseException:
                self.s.dedup_busy = False
                raise
        return {'started':True}

    def progress(self, message, completed=0, total=0, **extra):
        self.s.set('dedup_status', dict(state='running', message=message, completed=completed, total=total, updated_at=now().isoformat(), **extra))

    def digest(self, asset):
        sig = signature(asset['video'])
        cache = self.s.get('dedup_hashes', {})
        old = cache.get(asset['id'], {})
        if old.get('signature') == sig: return old['sha256'], sig
        with Path(asset['video']).open('rb') as f: value = hashlib.file_digest(f, 'sha256').hexdigest()
        if signature(asset['video']) != sig: raise ValueError('文件在查重时发生变化')
        cache[asset['id']] = dict(signature=sig, sha256=value)
        self.s.set('dedup_hashes', cache)
        return value, sig

    def command(self, args):
        if not self.ffmpeg: raise ValueError('未配置 FFmpeg，无法抽帧；请配置后重新查重')
        p = subprocess.run([self.ffmpeg, '-v', 'error', '-nostdin', *args], capture_output=True, timeout=30,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if p.returncode: raise ValueError('视频解码失败，文件保持隔离')
        return p.stdout

    def frames(self, asset, digest, count):
        target = self.cache/f'{digest}-v{VERSION}-{count}.bin'
        size = 64*64
        if target.is_file() and target.stat().st_size == count*size:
            data = target.read_bytes()
        else:
            duration = asset['duration']
            if duration <= 0: raise ValueError('无法读取视频时长')
            data = b''
            for i in range(count):
                t = duration*(i+1)/(count+1)
                frame = self.command(['-threads', '4', '-ss', str(t), '-i', asset['video'], '-an', '-frames:v', '1', '-vf', 'scale=64:64', '-threads', '1', '-pix_fmt', 'gray', '-f', 'rawvideo', 'pipe:1'])
                if len(frame) != size: raise ValueError('未取得完整画面')
                data += frame
            temporary=target.with_suffix('.'+uuid.uuid4().hex+'.tmp')
            temporary.write_bytes(data)
            temporary.replace(target)
        return [data[i*size:(i+1)*size] for i in range(count)]

    def audio_match(self, a, b):
        for fraction in (.2, .5, .8):
            samples = []
            for item in (a, b):
                raw = self.command(['-ss', str(item['duration']*fraction), '-i', item['video'], '-t', '2', '-vn', '-ac', '1', '-ar', '8000', '-f', 's16le', 'pipe:1'])
                values = array.array('h'); values.frombytes(raw); samples.append(values)
            x, y = samples
            if len(x) < 4000 or len(x) != len(y): return False
            energy = math.sqrt(sum(v*v for v in x)*sum(v*v for v in y))
            if not energy or sum(v*w for v, w in zip(x, y))/energy < .995: return False
        return True

    def run(self, deep_ids, folder=None):
        try:
            if folder: self.s.scan(folder)
            with self.s.lock:
                assets = self.s.get('assets', [])
                for a in assets:
                    if deep_ids and a['id'] not in deep_ids: continue
                    if a['state']=='excluded' and a.get('duplicate_of') and a.get('dedup_signature'):
                        try:
                            if signature(a['video']) != a['dedup_signature']: a['state']='duplicate_checking'
                        except OSError: pass
                    if a['state'] in EDITABLE: a['state'] = 'duplicate_checking'
                self.s.set('assets', assets)
            self.check(assets, deep_ids)
        except Exception as exc:
            self.s.set('dedup_status', dict(state='failed', message=str(exc)+'；未完成项保持隔离，可重新查重', updated_at=now().isoformat()))
        finally:
            with self.s.lock: self.s.dedup_busy = False

    def check(self, assets, deep_ids):
        facts = {}; errors = {}; decisions = self.s.get('dedup_decisions', {})
        prior_pairs={tuple(sorted(p['ids'])) for g in self.s.get('dedup_groups', []) for p in g.get('pairs', [])}
        candidates = [a for a in assets if a['state'] in EDITABLE | HISTORY | {'duplicate_pending'} and (not deep_ids or a['id'] in deep_ids)]
        for i, a in enumerate(candidates):
            self.progress('读取文件指纹：'+a['name'], i, len(candidates))
            try:
                digest, sig = self.digest(a)
                if deep_ids and a.get('dedup_signature') and a['dedup_signature'] != sig:
                    raise ValueError('文件已变化，请先重新查重全部库存，再做深度排查')
                # Existing submission digests anchor the historical bytes, even if
                # the source path was subsequently overwritten.
                historical_sha = a.get('sha256') if a['state'] in HISTORY else None
                facts[a['id']] = dict(sha=digest, sig=sig, old_sha=historical_sha)
            except (OSError, ValueError) as exc:
                errors[a['id']] = str(exc)
                if a['state'] in HISTORY and a.get('sha256'):
                    facts[a['id']] = dict(sha=a['sha256'], sig=None, old_sha=a['sha256'])
        # Byte-identical pairs do not need decoding. Historical matches take priority.
        pairs = []; thumbnails = {}
        extractable = [a for a in candidates if a['id'] in facts and facts[a['id']]['sig'] and
                       (not facts[a['id']]['old_sha'] or facts[a['id']]['old_sha']==facts[a['id']]['sha'])]
        self.progress('并行抽帧初筛（最多 3 个本地文件）', 0, len(extractable))
        with ThreadPoolExecutor(max_workers=3) as pool:
            tasks={pool.submit(self.frames,a,facts[a['id']]['sha'],3):a for a in extractable}
            for i, task in enumerate(as_completed(tasks), 1):
                a=tasks[task]
                try: thumbnails[a['id']]=task.result()
                except (OSError, ValueError, subprocess.TimeoutExpired) as exc: errors[a['id']]=str(exc)
                self.progress('抽帧初筛：'+a['name'],i,len(extractable))
        total = len(candidates)*(len(candidates)-1)//2; done = 0
        for i, a in enumerate(candidates):
            for b in candidates[i+1:]:
                done += 1
                if a['state'] not in EDITABLE and b['state'] not in EDITABLE: continue
                fa, fb = facts.get(a['id']), facts.get(b['id'])
                previously_held = tuple(sorted([a['id'],b['id']])) in prior_pairs
                if not fa or not fb:
                    if same_name(a,b) or previously_held: pairs.append(dict(ids=[a['id'],b['id']],result='review',reason='疑似参考文件无法读取，需要恢复文件后排查'))
                    continue
                key = decision_key(fa['old_sha'] or fa['sha'], fb['old_sha'] or fb['sha'])
                verdict = decisions.get(key)
                if verdict and verdict.get('manual') and (not fa['sig'] or not fb['sig'] or verdict.get('signatures') != sorted([fa['sig'],fb['sig']])):
                    verdict = None
                exact = (fa['old_sha'] or fa['sha']) == (fb['old_sha'] or fb['sha'])
                x, y = thumbnails.get(a['id']), thumbnails.get(b['id'])
                close_duration = abs(a['duration']-b['duration']) <= max(1, min(a['duration'],b['duration'])*.03)
                near = bool(x and y and close_duration and all(distance(p[::8],q[::8]) < .06 for p,q in zip(x,y)))
                if exact:
                    verdict = dict(result='duplicate', reason='文件 SHA-256 完全一致')
                elif not verdict and not (same_name(a,b) or near or previously_held): continue
                elif not verdict: verdict = dict(result='review', reason='名称、标题或抽样画面相近，需要深度排查')
                if not exact and a['id'] in deep_ids and b['id'] in deep_ids and verdict['result'] == 'review':
                    self.progress('深度比对：'+a['name']+' / '+b['name'], done, total)
                    try:
                        if not x or not y: raise ValueError('参考文件缺失、已变化或无法抽帧')
                        dx = self.frames(a, fa['sha'], 12); dy = self.frames(b, fb['sha'], 12)
                        visual_close = max(distance(p,q) for p,q in zip(dx,dy)) < .008
                        result, reason = visual_verdict(dx, dy, a['duration'], b['duration'], self.audio_match(a,b) if visual_close else False)
                        verdict = dict(result=result, reason=reason)
                        if result != 'review': decisions[key] = verdict
                    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                        verdict = dict(result='review', reason='深度排查未完成：'+str(exc))
                pairs.append(dict(ids=[a['id'],b['id']], **verdict))
        # A source change invalidates this whole assessment, never a partial release.
        for a in candidates:
            f = facts.get(a['id'])
            if f and f['sig'] and signature(a['video']) != f['sig']:
                raise ValueError('查重期间文件发生变化，请重新查重')
        byid = {a['id']:a for a in assets}; parent = {a['id']:a['id'] for a in candidates}
        def root(i):
            while parent[i] != i: i = parent[i]
            return i
        planned = {r['asset_id'] for r in self.s.get('plan', [])}
        def rank(i):
            a = byid[i]
            return (a['state'] not in HISTORY, a['state'] != 'duplicate_pending', i not in planned, a.get('date',''), i)
        for pair in pairs:
            if pair['result'] != 'duplicate': continue
            a,b = map(root,pair['ids']); winner,loser = sorted([a,b],key=rank); parent[loser] = winner
        excluded = {i:root(i) for i in parent if root(i) != i and byid[i]['state'] in EDITABLE}
        unresolved = [p for p in pairs if p['result']=='review' and any(i not in excluded and byid[i]['state'] in EDITABLE for i in p['ids'])]
        held = {i for p in unresolved for i in p['ids'] if i not in excluded and byid[i]['state'] in EDITABLE}
        groups = [g for g in self.s.get('dedup_groups', []) if deep_ids and not deep_ids.intersection(g['ids'])]
        # Connected components are for presentation only, never evidence of duplication.
        remaining = list(unresolved)
        while remaining:
            first = remaining.pop(0); members=set(first['ids']); evidence=[first]
            changed=True
            while changed:
                changed=False
                for pair in remaining[:]:
                    if members.intersection(pair['ids']):
                        members.update(pair['ids']);evidence.append(pair);remaining.remove(pair);changed=True
            ids=sorted(members); groups.append(dict(id=hashlib.sha256('|'.join(ids).encode()).hexdigest()[:16], ids=ids, pairs=evidence))
        for i,error in errors.items():
            if byid[i]['state'] in EDITABLE and i not in excluded:
                held.add(i)
                if not any(i in g['ids'] for g in groups): groups.append(dict(id=i,ids=[i],pairs=[],error=error))
        for a in assets:
            if a['state'] not in EDITABLE:
                if a['id'] in facts: a['dedup_reference_signature']=facts[a['id']]['sig']
                continue
            if deep_ids and a['id'] not in deep_ids: continue
            ident=a['id']
            a['dedup_error']=errors.get(ident, '')
            if ident in excluded:
                a.update(state='excluded',selected=False,dedup='已确认重复',dedup_evidence='重复参考：'+excluded[ident],duplicate_of=excluded[ident])
            elif ident in held:
                a.update(state='duplicate_review',selected=False,dedup='疑似重复 / 查重待完成',dedup_evidence=errors.get(ident,'在查重区域深度排查'))
            else:
                a.update(state='ready',dedup='本地查重通过',dedup_evidence='未发现未解决的本地重复候选；发布前仍须核对平台')
            if ident in facts:
                a['sha256']=facts[ident]['sha']
                a['dedup_signature']=facts[ident]['sig']
        with self.s.lock:
            held_count=sum(a['state'] in {'duplicate_review','duplicate_checking'} for a in assets)
            # All values commit together so groups never disagree with eligibility.
            values=dict(assets=assets,dedup_groups=groups,dedup_decisions=decisions,
                        dedup_status=dict(state='done',message=f'查重完成：本次排除 {len(excluded)} 条重复，库存 {held_count} 条待排查',updated_at=now().isoformat(),excluded=len(excluded),held=held_count))
            with self.s.connect() as c:
                c.executemany('INSERT OR REPLACE INTO kv VALUES (?,?)',[(k,json.dumps(v,ensure_ascii=False)) for k,v in values.items()])
