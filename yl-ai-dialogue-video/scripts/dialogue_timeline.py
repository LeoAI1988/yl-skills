"""Local frame-based dialogue editing. No network, generation or automatic cuts."""
from pathlib import Path
from fractions import Fraction
import argparse,copy,hashlib,json,math,subprocess,sys,tempfile

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def local(base,value):
    if not isinstance(value,str) or '://' in value:raise ValueError('Local file path required')
    p=(base/value).expanduser().resolve()
    if not p.is_file():raise ValueError('Missing local input: '+str(p))
    return p

def probe(path,ffprobe):
    return json.loads(subprocess.check_output([ffprobe,'-v','error','-show_streams','-show_format','-of','json',str(path)]))

def integer(value,label):
    if isinstance(value,bool) or not isinstance(value,int):raise ValueError(label+' must be an integer')
    return value

def compile_plan(path,ffprobe='ffprobe'):
    path=Path(path).resolve();base=path.parent;plan=read(path)
    fps=integer(plan.get('fps',24),'fps');canvas=plan.get('canvas',[720,1280])
    if not 1<=fps<=120 or len(canvas)!=2 or any(integer(x,'canvas')<=0 or x%2 for x in canvas):raise ValueError('Invalid canvas/fps')
    sources={};assets={}
    for item in plan['sources']:
        sid=item['id']
        if not isinstance(sid,str) or not sid or sid in sources:raise ValueError('Duplicate/empty source id')
        video=local(base,item['video']);audio=local(base,item.get('audio',item['video']))
        vp=probe(video,ffprobe);ap=vp if audio==video else probe(audio,ffprobe)
        vs=next((s for s in vp['streams'] if s['codec_type']=='video'),None)
        aus=next((s for s in ap['streams'] if s['codec_type']=='audio'),None)
        if vs is None or aus is None:raise ValueError('Each source needs video and aligned audio')
        native=float(Fraction(vs['avg_frame_rate']));rate=float(Fraction(vs['r_frame_rate']))
        if native<=0 or abs(native-rate)>.001:raise ValueError('Normalize variable-frame-rate source before editing')
        if any(abs(float(x.get('rotation',0)))>.01 for x in vs.get('side_data_list',[])):raise ValueError('Normalize rotated source first')
        frames=int(vs.get('nb_frames') or round(float(vp['format']['duration'])*native))
        duration=float(aus.get('duration') or ap['format']['duration'])
        crop=item.get('crop',[0,0,vs['width'],vs['height']])
        if len(crop)!=4 or any(not isinstance(x,int) for x in crop):raise ValueError('Invalid crop')
        x,y,w,h=crop
        if min(x,y)<0 or min(w,h)<=0 or x+w>vs['width'] or y+h>vs['height']:raise ValueError('Crop out of bounds')
        if abs((w/h)/(canvas[0]/canvas[1])-1)>.01:raise ValueError('Crop must match output aspect ratio; do not stretch')
        for f in {video,audio}:assets[str(f)]=digest(f)
        sources[sid]={'video':str(video),'audio':str(audio),'fps':native,'frames':frames,'audio_duration':duration,'crop':crop,'existing_speed_note':item.get('existing_speed_note','unknown; requested speed is relative to this input')}
    segments=[];cursor=0;ids=set()
    for raw in plan['segments']:
        s=copy.deepcopy(raw);sid=s['source'];sid_data=sources[sid]
        if not isinstance(s['id'],str) or not s['id'] or s['id'] in ids:raise ValueError('Duplicate/empty segment id')
        ids.add(s['id']);a=integer(s['start_frame'],'start_frame');b=integer(s['end_frame'],'end_frame')
        speed=float(s.get('speed',1))
        if not math.isfinite(speed) or not .5<=speed<=2:raise ValueError('Speed must be between 0.5 and 2 relative to input')
        if not 0<=a<b<=sid_data['frames'] or b/sid_data['fps']>sid_data['audio_duration']+.025:raise ValueError('Segment outside video/audio range')
        duration=(b-a)/sid_data['fps'];n=round(duration/speed*fps)
        if n<1:raise ValueError('Segment rounds to zero frames')
        s.update(speed=speed,applied_speed=duration/(n/fps),output_start=cursor,output_end=cursor+n,output_frames=n,
                 source_frames=[min(b-1,a+math.floor((j+.5)*(b-a)/n)) for j in range(n)])
        cursor+=n;segments.append(s)
    if not segments:raise ValueError('Empty timeline')
    def map_ranges(rows,images=False):
        result=[]
        for raw in rows:
            source=sources[raw['source']];a=integer(raw['start_frame'],'cue start');b=integer(raw['end_frame'],'cue end')
            if not 0<=a<b<=source['frames']:raise ValueError('Cue outside source')
            image=None
            if images:
                image=local(base,raw['image']);assets[str(image)]=digest(image)
            elif not isinstance(raw['text'],str) or not raw['text'].strip():raise ValueError('Empty caption')
            hits=[]
            for s in segments:
                if s['source']==raw['source']:
                    hits.extend(s['output_start']+j for j,f in enumerate(s['source_frames']) if a<=f<b)
            if not hits:continue
            groups=[];start=previous=hits[0]
            for f in hits[1:]:
                if f!=previous+1:groups.append((start,previous+1));start=f
                previous=f
            groups.append((start,previous+1))
            for start,end in groups:
                row={'start':start,'end':end}
                if images:row['image']=str(image)
                else:row['text']=raw['text']
                result.append(row)
        return result
    captions=map_ranges(plan.get('captions',[]));overlays=map_ranges(plan.get('overlays',[]),True)
    captions.sort(key=lambda c:c['start'])
    for a,b in zip(captions,captions[1:]):
        if a['end']>b['start']:raise ValueError('Caption pages overlap')
    return {'schema_version':1,'fps':fps,'canvas':canvas,'sources':sources,'segments':segments,'captions':captions,'overlays':overlays,'assets':assets,'frames':cursor,'duration':cursor/fps,'plan_sha256':digest(path),'listening_review':'not_performed'}

def srt(captions,fps):
    def stamp(frame):
        ms=round(frame/fps*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
        return f'{h:02}:{m:02}:{s:02},{ms:03}'
    return '\n\n'.join(f'{i+1}\n{stamp(c["start"])} --> {stamp(c["end"])}\n{c["text"]}' for i,c in enumerate(captions))+'\n'

def verify(path,edl,ffmpeg='ffmpeg',ffprobe='ffprobe'):
    data=probe(path,ffprobe);v=next(s for s in data['streams'] if s['codec_type']=='video');a=next(s for s in data['streams'] if s['codec_type']=='audio')
    if [v['width'],v['height']]!=edl['canvas'] or abs(float(Fraction(v['avg_frame_rate']))-edl['fps'])>.001:raise ValueError('Wrong output geometry/fps')
    if int(v['nb_frames'])!=edl['frames'] or abs(float(v['duration'])-edl['duration'])>.025:raise ValueError('Wrong output frame count/duration')
    if abs(float(a['duration'])-float(v['duration']))>.03:raise ValueError('Audio/video duration mismatch')
    check=subprocess.run([ffmpeg,'-v','error','-i',str(path),'-f','null','-'],capture_output=True)
    if check.returncode or check.stderr:raise ValueError('Decode failure: '+check.stderr.decode(errors='replace'))
    return {'output':str(Path(path).resolve()),'sha256':digest(path),'frames':edl['frames'],'duration':float(v['duration']),'decode':'passed','listening_review':'not_performed','visual_review':'not_performed','generation_calls':0}

def render(edl,out,work,ffmpeg='ffmpeg',ffprobe='ffprobe'):
    import cv2
    import numpy as np
    from PIL import Image
    out=Path(out).resolve();work=Path(work).resolve()
    if out.exists() or str(out) in edl['assets']:raise ValueError('Use a new output file; never replace an input')
    if not out.parent.is_dir() or not work.is_dir():raise ValueError('Output/work directory must already exist')
    for path,expected in edl['assets'].items():
        if digest(path)!=expected:raise ValueError('Input changed after compilation: '+path)
    width,height=edl['canvas'];fps=edl['fps'];segments=edl['segments']
    audio_paths=list(dict.fromkeys(s['audio'] for s in edl['sources'].values()));filters=[];args=[]
    for f in audio_paths:args+=['-i',f]
    for ai,f in enumerate(audio_paths):
        indices=[i for i,s in enumerate(segments) if edl['sources'][s['source']]['audio']==f]
        if indices:filters.append(f'[{ai}:a]asplit={len(indices)}'+''.join(f'[a{i}]' for i in indices))
    for i,s in enumerate(segments):
        source=edl['sources'][s['source']];start=s['start_frame']/source['fps'];end=s['end_frame']/source['fps'];dur=s['output_frames']/fps
        filters.append(f'[a{i}]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,atempo={s["applied_speed"]:.12f},apad,atrim=duration={dur}[o{i}]')
    filters.append(''.join(f'[o{i}]' for i in range(len(segments)))+f'concat=n={len(segments)}:v=0:a=1[aout]')
    layers=[]
    for o in edl['overlays']:
        im=Image.open(o['image']).convert('RGBA')
        if im.size!=(width,height):raise ValueError('Overlay must use output canvas dimensions')
        layers.append((o,np.asarray(im)))
    with tempfile.TemporaryDirectory(prefix='dialogue-render-',dir=work) as temporary:
        temp=Path(temporary);audio=temp/'edited.wav';graph=temp/'audio.txt';graph.write_text(';'.join(filters),encoding='utf-8')
        subprocess.run([ffmpeg,'-v','error','-n',*args,'-filter_complex_script',str(graph),'-map','[aout]','-ar','48000','-ac','2','-c:a','pcm_s24le',str(audio)],check=True)
        log=temp/'render.log';caps={};positions={};current={}
        with log.open('wb') as stream:
            proc=subprocess.Popen([ffmpeg,'-hide_banner','-n','-f','rawvideo','-pixel_format','bgr24','-video_size',f'{width}x{height}','-framerate',str(fps),'-i','pipe:0','-i',str(audio),'-map','0:v','-map','1:a','-c:v','libx264','-crf','16','-preset','medium','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart','-metadata','comment=AI dialogue source footage; locally edited with a source-based timeline.',str(out)],stdin=subprocess.PIPE,stderr=stream)
            try:
                for s in segments:
                    source=edl['sources'][s['source']];video=source['video']
                    for j,fno in enumerate(s['source_frames']):
                        if video not in caps or fno<positions[video]:
                            if video in caps:caps[video].release()
                            caps[video]=cv2.VideoCapture(video);positions[video]=-1
                        while positions[video]<fno:
                            ok,frame=caps[video].read()
                            if not ok:raise ValueError('Source decode ended before selected frame')
                            current[video]=frame;positions[video]+=1
                        x,y,w,h=source['crop'];frame=cv2.resize(current[video][y:y+h,x:x+w],(width,height),interpolation=cv2.INTER_LANCZOS4)
                        n=s['output_start']+j
                        for o,im in layers:
                            if o['start']<=n<o['end']:
                                alpha=im[:,:,3:4].astype(np.float32)/255
                                frame=(frame*(1-alpha)+im[:,:,:3][:,:,::-1]*alpha).round().astype(np.uint8)
                        proc.stdin.write(frame.tobytes())
                proc.stdin.close()
                if proc.wait():raise ValueError('Encoder failed; inspect output')
            except BaseException:
                proc.kill();proc.wait();raise
            finally:
                for cap in caps.values():cap.release()
        report=verify(out,edl,ffmpeg,ffprobe)
    return report

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    c=sub.add_parser('compile');c.add_argument('--plan',required=True);c.add_argument('--out',required=True);c.add_argument('--ffprobe',default='ffprobe')
    for name in ['render','verify']:
        cmd=sub.add_parser(name);cmd.add_argument('--edl',required=True);cmd.add_argument('--out',required=True);cmd.add_argument('--ffmpeg',default='ffmpeg');cmd.add_argument('--ffprobe',default='ffprobe')
        if name=='render':cmd.add_argument('--work-dir',required=True)
    args=parser.parse_args()
    if args.command=='compile':
        out=Path(args.out).resolve();plan=Path(args.plan).resolve()
        if out.exists() or out==plan or out.with_suffix('.srt').exists():raise ValueError('Use new EDL and SRT paths')
        e=compile_plan(plan,args.ffprobe)
        if str(out) in e['assets'] or str(out.with_suffix('.srt')) in e['assets']:raise ValueError('Output aliases an input')
        write(out,e);out.with_suffix('.srt').write_text(srt(e['captions'],e['fps']),encoding='utf-8');print(json.dumps({'frames':e['frames'],'duration':e['duration'],'captions':len(e['captions'])}))
    else:
        e=read(args.edl)
        report=render(e,args.out,args.work_dir,args.ffmpeg,args.ffprobe) if args.command=='render' else verify(args.out,e,args.ffmpeg,args.ffprobe)
        write(Path(args.out).with_suffix('.verification.json'),report);print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
