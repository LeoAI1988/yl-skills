"""Resolve a confirmed video's fields locally, before any browser upload."""
import copy
import json
import re
import subprocess
from pathlib import Path

from autofill import named_title, placeholder_title
from dedup import signature, require_unchanged
from engine import IMAGES, VIDEO, matching_tags, now, source_title
from rules import DEFAULTS, units, validate
from vision_title import read_titles, read_source_title


def media_key(path):
    text=path.stem
    camera=re.match(r'^(IMG[_-]?\d+|DSC[_-]?\d+|\d{5,})\b',text,re.I)
    if not camera:camera=re.match(r'^(IMG[_-]?\d+|DSC[_-]?\d+|\d{5,})(?=[_-])',text,re.I)
    if camera:return camera[1].casefold()
    return re.split(r'[_-](?:最终版|成片|精剪|横屏独白|v\d+|封面|cover)',text,flags=re.I)[0].casefold()


def bound(path,key):
    name=path.stem.casefold()
    return name==key or any(name.startswith(key+sep) for sep in ['_','-',' '])


def match_cover(video):
    """Only a name-bound image, or a sole generic cover in a one-video folder."""
    key=media_key(video)
    images=[p for p in video.parent.iterdir() if p.is_file() and p.suffix.lower() in IMAGES and ('封面' in p.name or 'cover' in p.name.lower())]
    candidates=[p for p in images if bound(p,video.stem.casefold()) or (key and bound(p,key))]
    if not candidates:
        video_keys={media_key(p) for p in video.parent.iterdir() if p.is_file() and p.suffix.lower() in VIDEO}
        if video_keys=={key}:
            candidates=[p for p in images if p.stem.casefold() in {'封面','cover'}]
    if not candidates:return None
    exact=[p for p in candidates if bound(p,video.stem.casefold())]
    return max(exact or candidates,key=lambda p:(p.stat().st_mtime,p.name))


def source_quotes(video):
    """Extract original speech only, without exposing review instructions as copy."""
    key=media_key(video);texts=[];paths=[]
    for p in sorted(video.parent.iterdir()):
        if p.suffix.lower() not in {'.md','.srt','.txt'} or not (bound(p,video.stem.casefold()) or (key and bound(p,key))):continue
        text=p.read_text(encoding='utf-8-sig',errors='replace')[:120000]
        if p.suffix.lower()=='.srt':
            text='\n'.join(line for line in text.splitlines() if line.strip() and not line.strip().isdigit() and '-->' not in line)
        else:
            kept=re.findall(r'^\*\*S\d+\*\*\s*〔[^〕]*〕\s*(.+)$',text,re.M)
            if kept:text='\n'.join(line for line in kept if '~~' not in line)
            else:
                sections=re.findall(r'^#{1,4}[^\n]*(?:完整顺读稿|最终顺读稿|字幕全文|原始逐字稿|完整逐字稿|最终口播稿)[^\n]*\n([\s\S]*?)(?=^#{1,4}\s|\Z)',text,re.M)
                if not sections:continue
                text='\n'.join(sections)
            text=re.sub(r'~~[\s\S]*?~~','',text)
            text=re.sub(r'```[\s\S]*?```','',text)
        if text.strip():texts.append(text.strip());paths.append(str(p))
    return '\n'.join(texts)[:18000],paths


def extract_cover(store,asset):
    ffmpeg=store.config.get('ffmpeg')
    if not ffmpeg or not Path(ffmpeg).is_file():raise ValueError('未找到可用的视频抽帧工具；本篇未上传')
    root=store.root/'prepared-covers';root.mkdir(parents=True,exist_ok=True)
    import hashlib
    key=hashlib.sha256(json.dumps(signature(asset['video'])).encode()).hexdigest()[:20]
    target=root/(asset['id']+'-'+key+'.jpg')
    if not target.exists():
        at=min(1,max(0,float(asset.get('duration') or 0)/4))
        try:result=subprocess.run([ffmpeg,'-v','error','-nostdin','-y','-threads','2','-ss',str(at),'-i',asset['video'],'-frames:v','1','-vf',"scale='min(1440,iw)':-2",'-q:v','2','-threads','1',str(target)],capture_output=True,timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except (OSError,subprocess.TimeoutExpired) as exc:
            target.unlink(missing_ok=True);raise ValueError('本篇封面抽帧未完成，未上传') from exc
        if result.returncode or not target.is_file():
            target.unlink(missing_ok=True);raise ValueError('无法从本条视频取得封面原帧；本篇未上传')
    return str(target)


def resolve_asset(store,asset,model=None,progress=None):
    """Does not mutate database, source media, account, time or publish body."""
    report=progress or (lambda note:None)
    a=copy.deepcopy(asset);require_unchanged(a);before=signature(a['video']);video=Path(a['video'])
    saved=store.get('preparation_sources',{}).get(a['id'],{})
    if saved.get('signature')!=before:saved={}
    report('正在匹配本篇标题与对应封面；尚未上传')
    cover=a.get('cover','')
    if not cover or not Path(cover).is_file():
        paired=match_cover(video)
        a['cover']=str(paired) if paired else ''
        if paired:a['cover_source']='同一成片名称匹配：'+str(paired)
    if placeholder_title(a):
        value=saved.get('title','');source=saved.get('title_source','')
        if not value:value,source,_=source_title(video)
        if not value:value=named_title(video);source='成片描述性文件名（去除技术后缀）'
        if not value:
            report('正在核对成片主标题和对应封面文字；尚未上传')
            found=read_titles(store,[a],model)
            if a['id'] in found:
                value,frame=found[a['id']];source='读取本篇实际画面：'+frame
        if not value:
            text,paths=source_quotes(video)
            if text:
                report('正在从本篇原始口播中匹配标题原话；尚未上传')
                value=read_source_title(store,text,model)
                if value:source='对应原稿原话：'+'；'.join(paths)
        a['title']=value;a['title_source']=source
    if units(a.get('title',''))>20 and not a.get('title_source','').startswith('手动确认标题'):
        clauses=[x.strip() for x in re.split(r'[，。！？；,!?;\n]',a['title']) if 4<=units(x.strip())<=20]
        if clauses:
            a['title_original']=a['title'];a['title']=clauses[0];a['title_source']=a.get('title_source','')+'；原题完整短句'
        else:
            report('原题超过20字，正在选取原题中的完整短句；尚未上传')
            short=read_source_title(store,a['title'],model)
            if short:a['title_original']=a['title'];a['title']=short;a['title_source']=a.get('title_source','')+'；逐字核验的原题短句'
    if not a.get('title','').strip():raise ValueError('本篇画面、封面与对应原稿均没有可核实的标题，已单独留待处理；其他篇继续')
    a['settings']={**DEFAULTS,**a.get('settings',{})}
    if a['settings']['ai_declaration']=='unknown':
        declaration=saved.get('ai_declaration') or store.config.get('ai_declaration_default')
        if declaration in {'none','contains_ai'}:
            a['settings']['ai_declaration']=declaration
            a['ai_confirmation']=dict(value=declaration,source=saved.get('ai_source') or store.config.get('ai_declaration_default_source','安装者个人默认值'),at=now().isoformat(),signature=before)
    if not a.get('tags'):a['tags']=matching_tags(a['title'],a.get('caption',''),store.config.get('tag_pool',[]),a['id'])
    a.update(validate(a,for_execution=True))
    if not a.get('cover'):
        report('没有本篇已有封面，正在提取本片原帧；尚未上传')
        a['cover']=extract_cover(store,a);a['cover_source']='本条成片原帧（非AI生成）'
    if signature(a['video'])!=before:raise ValueError('匹配期间视频文件已变化；本篇未上传，请重新查重')
    return a
