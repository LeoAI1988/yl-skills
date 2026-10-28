"""Read-only visual provenance/geometry gate; does not certify subjective layout."""
from pathlib import Path
import argparse,json,hashlib,sys

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def verify(style_path,captions_path,layers_path):
    from PIL import Image,ImageFont,ImageColor,ImageDraw
    import math
    from fontTools.ttLib import TTFont
    import numpy as np
    s=read(style_path);caps=read(captions_path);m=read(layers_path);errors=[];measurements=[]
    def check(ok,message):
        if not ok:errors.append(message)
    if s.get('sourceStyle'):
        reference_path=Path(s['sourceStyle']);reference=read(reference_path)
        check(s.get('sourceStyleSha256')==sha(reference_path),'Personal reference style changed; recalibration required')
        authorized=s.get('authorizedOverrides',[])
        for field in ['fontFile','weight','titleSize','titleScaleX','subtitleSize','subtitleBaseline','subtitleScaleX']:
            if field not in authorized:check(s.get(field)==reference.get(field),f'Unauthorized reference override: {field}')
    check(m.get('styleSha256')==sha(style_path),'Layer cache provenance does not match current style')
    font=Path(s['fontFile']);weight=TTFont(font)['OS/2'].usWeightClass
    check(weight==s['weight'],'Actual font weight mismatch')
    check(m.get('font_sha256')==sha(font),'Layer font provenance mismatch')
    check([m.get('width'),m.get('height')]==s['canvas'],'Canvas mismatch')
    if m.get('title'):
        check(m.get('titleSize')==s.get('titleSize'),'Title size differs from current visual style; stale or hardcoded title layer')
    if 'enabled' in s.get('underline',{}):check(m.get('underline')==s['underline']['enabled'],'Title underline switch mismatch')
    width_font=ImageFont.truetype(str(font),s['subtitleSize'])
    for c in caps:
        for actual,expected in [('fontSize','subtitleSize'),('fontWeight','weight'),('baseline','subtitleBaseline'),('scaleX','subtitleScaleX')]:
            check(c.get(actual)==s[expected],f'Caption {c.get("startFrame")} {actual} mismatch: {c.get(actual)} vs {s[expected]}')
        check(width_font.getlength(c['text'])*s['subtitleScaleX']<=s.get('subtitleMaxWidth',s['canvas'][0]-120),f'Caption exceeds reference safe width at frame {c.get("startFrame")}')
    # The lower half of ordinary transparent text states contains captions only.
    # This catches stale low subtitles and unintended explanatory graphic labels.
    seen=set();title_bounds={};font_obj=ImageFont.truetype(str(font),s['subtitleSize']);height=s['canvas'][1];split=height//2
    for state in m.get('states',[]):
        if state['image'] in seen:continue
        seen.add(state['image']);im=Image.open(state['image']).convert('RGBA')
        check(list(im.size)==s['canvas'],'Text PNG canvas mismatch')
        a=np.asarray(im);mask=a[split:,:,3]>=96;yy,xx=np.where(mask)
        if state['startFrame']<s.get('titleDurationFrames',300) and m.get('title'):
            tf=ImageFont.truetype(str(font),m['titleSize']);sx=s['titleScaleX'];actual_sx=round(s['canvas'][0]*sx)/s['canvas'][0];ink=s.get('titleInkExpansion',0)
            for ti,title in enumerate(m['title']):
                bb=tf.getbbox(title,anchor='ls');x=(s['canvas'][0]/sx-tf.getlength(title))/2;y=s['titleBaselines'][ti]
                top=max(0,y+bb[1]-ink-3);bottom=min(height,y+bb[3]+ink+4)
                region=a[top:bottom];color=np.array(ImageColor.getrgb(s['titleColor'][ti]),dtype=np.int16)
                colored=(np.max(np.abs(region[:,:,:3].astype(np.int16)-color),axis=2)<=35)&(region[:,:,3]>=180)
                cy,cx=np.where(colored)
                check(bool(len(cx)),f'Missing title ink at frame {state["startFrame"]}, line {ti}')
                if len(cx):
                    key=(m['titleSize'],title,ink)
                    if key not in title_bounds:
                        pad=m['titleSize']*2;mask=Image.new('L',(math.ceil(tf.getlength(title))+pad*2,pad*2));ImageDraw.Draw(mask).text((pad,pad),title,font=tf,fill=255,stroke_width=ink,stroke_fill=255,anchor='ls')
                        my,mx=np.where(np.asarray(mask)>=180);title_bounds[key]=(int(mx.min())-pad,int(mx.max())-pad)
                    left,right=title_bounds[key];expected_left=round((x+left)*actual_sx);expected_right=round((x+right)*actual_sx)
                    check(abs(int(cx.min())-expected_left)<=3 and abs(int(cx.max())-expected_right)<=3,f'Title glyph width/crop mismatch at frame {state["startFrame"]}, line {ti}: ink {int(cx.min())}-{int(cx.max())} vs {expected_left}-{expected_right}')
        c=next((c for c in caps if c['startFrame']<=state['startFrame']<c['endFrame']),None)
        if not c:
            check(not len(yy),f'Unexpected lower-half labels at frame {state["startFrame"]}');continue
        check(bool(len(yy)),f'Missing caption pixels at frame {state["startFrame"]}')
        if not len(yy):continue
        bbox=font_obj.getbbox(c['text'],anchor='ls');expected=s['subtitleBaseline']+bbox[1]
        top=int(yy.min()+split);bottom=int(yy.max()+split)
        check(abs(top-expected)<=16,f'Caption pixel top mismatch at frame {state["startFrame"]}: {top} vs {expected}')
        check(bottom<=s['subtitleBaseline']+bbox[3]+32,f'Caption pixels too low at frame {state["startFrame"]}')
        measurements.append({'frame':state['startFrame'],'text':c['text'],'top':top,'bottom':bottom,'expectedGlyphTop':expected})
    return {'status':'FAIL' if errors else 'PASS','scope':'visual parameter provenance and transparent caption pixel geometry only; subjective/reference/final-MP4 review remains separate','styleSha256':sha(style_path),'fontWeight':weight,'statesChecked':len(seen),'measurements':measurements,'errors':errors}

def main():
    p=argparse.ArgumentParser();p.add_argument('--style',type=Path,required=True);p.add_argument('--captions',type=Path,required=True);p.add_argument('--layers',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    if a.report.exists():raise FileExistsError(a.report)
    if a.report.resolve() in [q.resolve() for q in [a.style,a.captions,a.layers]]:raise ValueError('Report aliases an input')
    try:r=verify(a.style,a.captions,a.layers)
    except Exception as e:r={'status':'FAIL','errors':[str(e)]}
    a.report.parent.mkdir(parents=True,exist_ok=True)
    with a.report.open('x',encoding='utf-8') as f:json.dump(r,f,ensure_ascii=False,indent=2)
    print(r['status'],len(r.get('errors',[])),flush=True)
    if r['status']!='PASS':sys.exit(1)
if __name__=='__main__':main()
