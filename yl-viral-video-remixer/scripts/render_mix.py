"""Render an adjudicated mixed-take plan. No speech/semantic decisions are inferred.

Python 3.10+, Pillow, fontTools, FFmpeg with zscale/tonemap/libx264, ffprobe.
All input, tool and output paths come from a runtime plan outside the skill.
"""
from __future__ import annotations
import argparse,hashlib,json,math,subprocess
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont,ImageFilter,ImageChops
from fontTools.ttLib import TTFont

def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def save(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def call(cmd,log=None):
 if log:
  with Path(log).open('wb') as f:q=subprocess.run(cmd,stdout=f,stderr=f)
  err=Path(log).read_text('utf8',errors='replace')[-3500:]
 else:
  q=subprocess.run(cmd,capture_output=True);err=q.stderr.decode(errors='replace')[-3500:]
 if q.returncode:raise RuntimeError(err)
 return q.stdout if not log else None
def resolve(plan):
 fps=plan['fps'];assert isinstance(fps,int) and fps>0
 assert plan['width']>0 and plan['height']>0
 assert len({s['takeId'] for s in plan['blocks']})>=2,'Need two independent takes'
 at=0
 for b in plan['blocks']:
  assert b['role'] in ['mother','existing']
  assert .5<=b['rate']<=100,'Rate outside atempo supported range'
  if b['role']=='existing':
   assert b['rate']==1,'Existing edits must not receive another speed pass'
   assert b.get('bakedStyleReviewed') is True and b.get('visualEvidence'),'Review baked text before reuse'
  previous=-1;keeps=[]
  for a,z in b['keeps']:
   assert 0<=a<z and a>=previous,'Invalid or overlapping keeps'
   keeps.append([round(a*fps)/fps,round(z*fps)/fps]);previous=z
  assert all(z>a for a,z in keeps),'Sub-frame empty keep'
  b['keeps']=keeps
  kept=sum(round((z-a)*fps) for a,z in keeps)
  b['outputFrames']=round(kept/b['rate']);assert b['outputFrames']>0
  b['startFrame']=at;at+=b['outputFrames']
  actual=sha(b['path'])
  assert actual==b['sha256'],'Source bytes changed'
  b['keptSourceFrames']=kept
 plan['outputFrames']=at
 for c in plan['captions']:
  assert 0<=c['startFrame']<c['endFrame']<=at,'Caption outside output'
 for a,b in zip(plan['captions'],plan['captions'][1:]):assert a['endFrame']<=b['startFrame'],'Captions overlap'
 for p in plan.get('pauseReviews',[]):
  assert p.get('decision') in ['cut','retain','false_positive'],'Unresolved pauses'
  if p['decision']=='cut':
   b=plan['blocks'][p['block']]
   assert p['sourceStart']<p['sourceEnd'] and p.get('reason'),'Cut review lacks interval or reason'
   assert all(min(z,p['sourceEnd'])-max(a,p['sourceStart'])<=1/fps+1e-6 for a,z in b['keeps']),'Pause marked cut is still present in actual keeps'
 if plan.get('audioCopyFrom'):
  approved=read(plan['audioCopyPlan'])
  identity=lambda d:[{k:b.get(k) for k in ['sha256','rate','keeps','gainDb','outputFrames','startFrame']} for b in d['blocks']]
  assert approved['outputFrames']==plan['outputFrames'] and identity(approved)==identity(plan),'Audio copy belongs to another EDL'
  assert sha(plan['audioCopyFrom'])==plan['audioCopySha256'],'Approved audio container changed'
 return plan

def text_layer(text,baseline,size,sx,color,style,width,height,font_file,kind):
 font=ImageFont.truetype(str(font_file),size); length=font.getlength(text)*sx
 base=style['canvas'][0];scale=width/base
 maximum=style.get('subtitleMaxWidth',base*960/1080) if kind=='subtitle' else style.get('titleMaxWidth',base*1000/1080)
 maximum*=scale
 assert length<=maximum+1,f'Text too wide at fixed size: {text} ({length:.1f}>{maximum})'
 mask=Image.new('L',(width,height));d=ImageDraw.Draw(mask)
 d.text(((width-font.getlength(text))/2,baseline),text,font=font,fill=255,anchor='ls')
 if sx!=1:
  narrow=mask.resize((round(width*sx),height),Image.Resampling.LANCZOS);mask=Image.new('L',(width,height));mask.paste(narrow,((width-narrow.width)//2,0))
 # Measure actual rendered glyphs separately from outlines/shadows.
 box=mask.getbbox();assert box and box[0]>0 and box[2]<width and box[1]>=0 and box[3]<=height
 outline_px=max(1,round(style['outline']*scale));outline=mask.filter(ImageFilter.MaxFilter(outline_px*2+1))
 sh=style['shadow'];shadow=Image.new('L',(width,height));shadow.paste(outline,(round(sh['x']*scale),round(sh['y']*scale)))
 shadow=ImageChops.lighter(shadow,shadow.filter(ImageFilter.GaussianBlur(sh['blur']*scale)))
 shadow=shadow.point(lambda x:round(x*sh['alpha']))
 layer=Image.new('RGBA',(width,height));layer.alpha_composite(Image.composite(Image.new('RGBA',layer.size,'black'),Image.new('RGBA',layer.size),shadow))
 layer.alpha_composite(Image.composite(Image.new('RGBA',layer.size,'black'),Image.new('RGBA',layer.size),outline))
 layer.alpha_composite(Image.composite(Image.new('RGBA',layer.size,color),Image.new('RGBA',layer.size),mask))
 return layer,{'text':text,'size':size,'scaleX':sx,'baseline':baseline,'glyphBox':box,'glyphWidth':round(length,2)}

def graphics(plan,work):
 w,h,fps=plan['width'],plan['height'],plan['fps'];st=read(plan['styleFile']);scale=w/st['canvas'][0]
 assert abs(w/h-st['canvas'][0]/st['canvas'][1])<1e-6
 font=Path(plan['fontFile']);ft=TTFont(font);weight=ft['OS/2'].usWeightClass
 assert weight==st['weight'],'Actual font weight differs from style'
 if 'fvar' in ft:assert not any(a.axisTag=='wght' for a in ft['fvar'].axes),'Instantiate variable font first'
 bounds=sorted({0,plan['outputFrames'],min(plan['outputFrames'],plan.get('titleEndFrame',300))}|{v for c in plan['captions'] for v in [c['startFrame'],c['endFrame']]})
 out=work/'overlays';out.mkdir();states=[];measurements=[];cache={}
 def raster(text,base,size,sx,color,kind):
  key=(text,base,size,sx,color,kind)
  if key not in cache:cache[key]=text_layer(text,round(base*scale),round(size*scale),sx,color,st,w,h,font,kind)
  return cache[key]
 for a,z in zip(bounds,bounds[1:]):
  caption=next((c['text'] for c in plan['captions'] if c['startFrame']<=a<c['endFrame']),None)
  show_title=a<plan.get('titleEndFrame',300) and not plan.get('titleAlreadyBaked',False)
  key=(caption,show_title)
  if key not in cache:
   pic=Image.new('RGBA',(w,h));metrics=[]
   if caption:
    layer,m=raster(caption,st['subtitleBaseline'],st['subtitleSize'],st['subtitleScaleX'],st['subtitleColor'],'subtitle');pic.alpha_composite(layer);metrics.append({'kind':'subtitle',**m})
   if show_title:
    assert len(plan['titleLines'])==2
    for i,line in enumerate(plan['titleLines']):
     layer,m=raster(line,st['titleBaselines'][i],st['titleSize'],st['titleScaleX'],st['titleColor'][i],'title');pic.alpha_composite(layer);metrics.append({'kind':'title',**m})
    u=st.get('underline')
    if u:ImageDraw.Draw(pic).rectangle([round(u['inset']*scale),round(u['y']*scale),round((st['canvas'][0]-u['inset'])*scale),round((u['y']+u['height'])*scale)-1],fill=st['titleColor'][1])
   p=out/f'{len(measurements):04d}.png';pic.save(p);cache[key]=p
   measurements.append({'image':str(p),'sha256':sha(p),'textMetrics':metrics})
  states.append({'startFrame':a,'endFrame':z,'image':str(cache[key])})
 manifest={'width':w,'height':h,'fps':fps,'outputFrames':plan['outputFrames'],'styleSha256':sha(plan['styleFile']),'fontSha256':sha(font),'actualWeight':weight,'states':states,'measurements':measurements}
 save(work/'graphics.json',manifest)
 def quote(p):return str(p).replace('\\','/').replace("'","'\\''")
 lines=['ffconcat version 1.0']
 for s in states:lines += ["file '"+quote(s['image'])+"'",f'option framerate {fps}',f'duration {(s["endFrame"]-s["startFrame"])/fps:.12f}']
 lines += ["file '"+quote(states[-1]['image'])+"'",f'option framerate {fps}']
 cat=work/'overlays.ffconcat';cat.write_text('\n'.join(lines)+'\n','utf8')
 mov=work/'overlays.mov'
 call([plan['ffmpeg'],'-v','warning','-nostdin','-n','-f','concat','-safe','0','-i',str(cat),'-an','-c:v','qtrle','-pix_fmt','argb','-r',str(fps),'-frames:v',str(plan['outputFrames']),str(mov)],work/'overlays.log')
 return mov

def render(plan_file):
 plan=resolve(read(plan_file));dest=Path(plan['output']);assert not dest.exists(),'Existing output is protected'
 work=Path(plan['work']);work.mkdir(parents=True,exist_ok=False);dest.parent.mkdir(parents=True,exist_ok=True)
 save(work/'executed_plan.json',plan);overlay=graphics(plan,work)
 ff=plan['ffmpeg'];fps=plan['fps'];w=plan['width'];h=plan['height']
 cmd=[ff,'-hide_banner','-nostdin','-n','-filter_complex_threads','2'];filters=[];labels=''
 for i,b in enumerate(plan['blocks']):
  start=b['keeps'][0][0];end=b['keeps'][-1][1];duration=b['outputFrames']/fps
  cmd+=['-threads','1','-ss',str(start),'-t',str(end-start+.05),'-i',b['path']]
  expr='+'.join(f'between(n,{round((a-start)*fps)},{round((z-start)*fps)-1})' for a,z in b['keeps'])
  # fps/select only change which source frames survive; spatial color/scale
  # then process those frames. Actual-source raw pixels matched the old order.
  vf=f"[{i}:v]setpts=PTS-STARTPTS,fps={fps},select='{expr}',"
  if b.get('transfer') in ['arib-std-b67','smpte2084']:
   tone=b.get('toneMap','hable');assert tone in ['hable','mobius','reinhard']
   vf+=f'zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap={tone}:desat=0,zscale=t=bt709:m=bt709:r=tv,'
  elif b.get('transfer') not in [None,'bt709','unknown']:raise ValueError('Unimplemented transfer')
  elif not b.get('sdrEvidence') and not b.get('transfer'):raise ValueError('Missing SDR interpretation evidence')
  vf+=f"scale={w}:{h}:flags=lanczos,setsar=1,setpts=N/({fps}*{b['rate']}*TB),fps={fps},tpad=stop_mode=clone:stop_duration=0.1,trim=end_frame={b['outputFrames']},setpts=N/({fps}*TB),format=yuv420p,setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709[v{i}]"
  filters.append(vf)
  n=len(b['keeps']);splits=''.join(f'[a{i}s{j}]' for j in range(n))
  filters.append(f'[{i}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asplit={n}{splits}')
  for j,(a,z) in enumerate(b['keeps']):
   filters.append(f'[a{i}s{j}]atrim=start_sample={round((a-start)*48000)}:end_sample={round((z-start)*48000)},asetpts=PTS-STARTPTS,afade=t=in:st=0:d=0.003,afade=t=out:st={max(0,z-a-.003):.9f}:d=0.003[a{i}k{j}]')
  ins=''.join(f'[a{i}k{j}]' for j in range(n))
  filters.append(ins+f"concat=n={n}:v=0:a=1,atempo={b['rate']},volume={b.get('gainDb',0)}dB,apad=pad_dur=0.2,atrim=end_sample={round(b['outputFrames']*48000/fps)},asetpts=N/SR/TB[a{i}]")
  labels+=f'[v{i}][a{i}]'
 cmd+=['-threads','1','-i',str(overlay)]
 filters.append(labels+f'concat=n={len(plan["blocks"])}:v=1:a=1[base][audio]')
 filters.append(f'[base][{len(plan["blocks"])}:v]overlay=eof_action=pass:format=auto,format=yuv420p[vout]')
 filters.append('[audio]alimiter=limit=0.891251:level=false:latency=true[aout]')
 script=work/'filters.txt';script.write_text(';\n'.join(filters),'utf8');encoded=work/'encoded.mp4'
 cmd+=['-filter_complex_script',str(script),'-map','[vout]','-map','[aout]','-c:v','libx264','-crf',str(plan.get('crf',14)),'-preset',plan.get('preset','medium'),'-threads','6','-r',str(fps),'-fps_mode','cfr','-c:a','aac','-b:a','192k','-ar','48000','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-color_range','tv','-map_metadata','-1','-metadata:s:v:0','rotate=0','-movflags','+faststart',str(encoded)]
 save(work/'command.json',cmd);call(cmd,work/'render.log')
 # Auto-oriented decoded pixels are upright; discard any stale inherited matrix.
 remux=[ff,'-v','warning','-nostdin','-n','-display_rotation:v:0','0','-i',str(encoded)]
 if plan.get('audioCopyFrom'):remux+=['-i',plan['audioCopyFrom']]
 remux+=['-map','0:v:0','-map','1:a:0' if plan.get('audioCopyFrom') else '0:a:0','-c','copy','-map_metadata','-1','-metadata:s:v:0','rotate=0','-movflags','+faststart',str(dest)]
 call(remux,work/'remux.log')
 probe=json.loads(call([plan['ffprobe'],'-v','error','-count_frames','-show_streams','-show_format','-of','json',str(dest)]))
 video=next(s for s in probe['streams'] if s['codec_type']=='video');audio=next(s for s in probe['streams'] if s['codec_type']=='audio')
 assert int(video['nb_read_frames'])==plan['outputFrames'],'Decoded frame count differs'
 assert video['width']==w and video['height']==h
 assert all(not x.get('rotation',0) for x in video.get('side_data_list',[])),'Stale display matrix'
 assert abs(float(video['duration'])-float(audio['duration']))<=1/fps+.001,'AV duration differs'
 save(work/'technical.json',{'sha256':sha(dest),'probe':probe,'executionPlanSha256':sha(work/'executed_plan.json'),'videoEncodedOnceFromSources':True,'audioEncodedOnceFromSources':True,'audioCopiedFrom':plan.get('audioCopyFrom'),'listeningReview':'NOT_PERFORMED_BY_RENDERER'})
 print(json.dumps({'output':str(dest),'frames':plan['outputFrames'],'seconds':plan['outputFrames']/fps},ensure_ascii=False),flush=True)
 return plan

if __name__=='__main__':
 a=argparse.ArgumentParser(description=__doc__);a.add_argument('plan');args=a.parse_args();render(args.plan)
