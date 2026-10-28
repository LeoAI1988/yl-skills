"""Source-bound preparation only. Never uploads, schedules or guesses AI facts."""
import copy
import re
from pathlib import Path
from engine import source_title, matching_tags, now
from dedup import signature, require_unchanged
from rules import DEFAULTS, BLOCKING_JOB_STATES, validate, units
from vision_title import read_titles


def named_title(path):
    text=re.sub(r'^\d+[_-]', '', path.stem)
    text=re.sub(r'[_-](?:\d+(?:\.\d+)?倍|v\d+|最终版|成片|精剪字幕标题)(?:[_-].*)?$', '', text, flags=re.I)
    if re.search(r'(?:IMG|DSC|MOV)[_-]?\d|^\d+(?:\.\d+)?$|审查|重剪|手动精修|精剪字幕标题|横屏独白', text, re.I): return ''
    return text.replace('_', '，') if re.search(r'[\u4e00-\u9fff]{2}', text) else ''


def placeholder_title(asset):
    title=asset.get('title','').strip()
    if not title: return True
    if asset.get('title_source','').startswith('手动确认标题'): return False
    return title in {'精剪字幕标题','横屏独白','手动精修','重剪','成片','final'} or bool(re.fullmatch(r'(?:IMG|DSC|MOV)[_-]?\d+(?:[_-].*)?(?:\.mp4)?',title,re.I))


def prepare(store, ids, revision, ai=None, model=None):
    with store.lock:
        if getattr(store,'dedup_busy',False) or any(j['state'] in BLOCKING_JOB_STATES for j in store.get('jobs',[])):
            raise ValueError('请先结束当前查重或发布任务')
        if not revision or revision!=store.preparation_revision(): raise ValueError('内容或排期已变化，请刷新后重试')
        if not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)): raise ValueError('请选择不重复的作品')
        assets={a['id']:a for a in store.get('assets',[])}; sources=store.get('preparation_sources',{})
        pending=[]
        for ident in ids:
            if ident not in assets or assets[ident]['state']!='ready': raise ValueError('作品已锁定，请刷新')
            a=assets[ident];require_unchanged(a)
            if not placeholder_title(a): continue
            saved=sources.get(ident,{})
            if saved.get('signature')==signature(a['video']) and saved.get('title'): continue
            if source_title(Path(a['video']))[0] or named_title(Path(a['video'])): continue
            pending.append(a)
    # Image interpretation may take time; never hold the database lock across it.
    vision=read_titles(store,pending,model)
    with store.lock:
        if getattr(store,'dedup_busy',False) or any(j['state'] in BLOCKING_JOB_STATES for j in store.get('jobs',[])):
            raise ValueError('请先结束当前查重或发布任务')
        if not revision or revision!=store.preparation_revision(): raise ValueError('内容或排期已变化，请刷新后重试')
        if not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)): raise ValueError('请选择不重复的作品')
        if ai not in [None,'none','contains_ai']: raise ValueError('AI 声明无效')
        assets=store.get('assets',[]); byid={a['id']:a for a in assets}
        evidence=store.get('preparation_sources',{}); updates={}; unresolved=[]; need_ai=[]; sigs={}
        for ident in ids:
            if ident not in byid or byid[ident]['state']!='ready': raise ValueError('作品已锁定，请刷新')
            a=copy.deepcopy(byid[ident]); require_unchanged(a); sigs[ident]=signature(a['video'])
            saved=evidence.get(ident,{})
            if saved.get('signature')!=sigs[ident]: saved={}
            if placeholder_title(a):
                if a.get('title'): a['title_source_original']=a.get('title_source','')
                value=saved.get('title',''); source=saved.get('title_source','')
                if not value: value,source,_=source_title(Path(a['video']))
                if not value:
                    value=named_title(Path(a['video'])); source='成片描述性文件名（去除编号及版本后缀）'
                if not value and ident in vision:
                    value,frame=vision[ident];source=('模型读取现有封面：' if frame==a.get('cover') else '模型读取成片顶部画面：')+frame
                if value:
                    a['title']=value; a['title_source']=source
                else:
                    a['title']=''
            if units(a.get('title',''))>20:
                # Select a complete original clause, never invent a title or cut a word.
                clauses=[x.strip() for x in re.split(r'[，。！？；,!?;\n]',a['title']) if 4<=units(x.strip())<=20]
                if clauses:
                    a['title_original']=a['title'];a['title']=clauses[0];a['title_source']=a.get('title_source','')+'；自动选取原题完整分句'
            a['settings']={**DEFAULTS,**a.get('settings',{})}
            if a['settings']['ai_declaration']=='unknown':
                declaration=ai or saved.get('ai_declaration') or store.config.get('ai_declaration_default')
                if declaration in ['none','contains_ai']:
                    a['settings']['ai_declaration']=declaration
                    default_source=store.config.get('ai_declaration_default_source','个人默认设置') if not ai else '用户在本批次确认'
                    a['ai_confirmation']=dict(value=declaration,source=saved.get('ai_source',default_source),at=now().isoformat(),signature=sigs[ident])
                else: need_ai.append(ident)
            if not a.get('tags'):
                a['tags']=matching_tags(a.get('title',''),a.get('caption',''),store.config.get('tag_pool',[]),ident)
            try:
                a.update(validate(a))
                if not a.get('title','').strip(): raise ValueError('未找到可靠标题来源，需要助手读取成片标题')
            except ValueError as exc:
                unresolved.append(dict(id=ident,name=a.get('name',''),reason=str(exc)))
                continue
            updates[ident]=a
            if ident in vision:
                evidence[ident]=dict(signature=sigs[ident],title=a['title'],title_source=a['title_source'],frame=vision[ident][1])
        for ident,sig in sigs.items():
            if signature(byid[ident]['video'])!=sig: raise ValueError('视频在整理期间发生变化，请重新查重')
        with store.connect() as c:
            import json
            c.executemany('INSERT OR REPLACE INTO kv VALUES (?,?)',[
                ('assets',json.dumps([updates.get(a['id'],a) for a in assets],ensure_ascii=False)),
                ('preparation_sources',json.dumps(evidence,ensure_ascii=False))])
        return dict(prepared=list(updates),unresolved=unresolved,need_ai=need_ai,revision=store.preparation_revision())
