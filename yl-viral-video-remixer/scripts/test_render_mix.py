"""Real two-take media test; fixtures are generated only in a temporary directory."""
import argparse,copy,json,math,subprocess,tempfile,wave
from pathlib import Path
import render_mix as m

def main():
 p=argparse.ArgumentParser();p.add_argument('--ffmpeg',required=True);p.add_argument('--ffprobe',required=True);p.add_argument('--font',required=True);p.add_argument('--style',required=True);a=p.parse_args()
 with tempfile.TemporaryDirectory(prefix='yl-remix-smoke-') as temp:
  r=Path(temp);sources=[]
  for name,color,tone in [('a','red',440),('b','blue',880)]:
   out=r/(name+'.mp4');m.call([a.ffmpeg,'-v','error','-nostdin','-f','lavfi','-i',f'color=c={color}:s=1080x1920:r=30:d=2','-f','lavfi','-i',f'sine=frequency={tone}:sample_rate=48000:duration=2','-c:v','libx264','-preset','ultrafast','-crf','20','-pix_fmt','yuv420p','-color_trc','bt709','-color_primaries','bt709','-colorspace','bt709','-c:a','aac',str(out)]);sources.append(out)
  blocks=[{'takeId':'a','path':str(sources[0]),'sha256':m.sha(sources[0]),'role':'mother','rate':1.1,'keeps':[[0,1.1]],'transfer':'bt709'}, {'takeId':'b','path':str(sources[1]),'sha256':m.sha(sources[1]),'role':'existing','rate':1,'keeps':[[0,1]],'transfer':'bt709','bakedStyleReviewed':True,'visualEvidence':'synthetic fixture contains no text'}]
  spec={'schemaVersion':1,'fps':30,'width':1080,'height':1920,'ffmpeg':a.ffmpeg,'ffprobe':a.ffprobe,'fontFile':a.font,'styleFile':a.style,'output':str(r/'result.mp4'),'work':str(r/'run'),'blocks':blocks,'captions':[{'startFrame':0,'endFrame':30,'text':'测试字幕'}],'titleLines':['测试标题','第二行标题'],'titleEndFrame':30,'preset':'ultrafast','pauseReviews':[]}
  bad=copy.deepcopy(spec);bad['blocks'][1]['rate']=1.1
  try:m.resolve(bad);raise RuntimeError('Double-speed edit was accepted')
  except AssertionError:pass
  bad=copy.deepcopy(spec);bad['blocks'][0]['keeps']=[[1,1.5],[0,.5]]
  try:m.resolve(bad);raise RuntimeError('Out-of-order keeps were accepted')
  except AssertionError:pass
  bad=copy.deepcopy(spec);bad['blocks'][0]['sha256']='0'*64
  try:m.resolve(bad);raise RuntimeError('Changed source was accepted')
  except AssertionError:pass
  bad=copy.deepcopy(spec);bad['pauseReviews']=[{'block':0,'sourceStart':.3,'sourceEnd':.6,'decision':'cut','reason':'test a claimed cut that was not executed'}]
  try:m.resolve(bad);raise RuntimeError('Unexecuted pause removal was accepted')
  except AssertionError:pass
  path=r/'plan.json';m.save(path,spec);result=m.render(path)
  assert result['outputFrames']==60
  protected=m.sha(r/'result.mp4')
  try:m.render(path);raise RuntimeError('Existing output was overwritten')
  except AssertionError:pass
  assert m.sha(r/'result.mp4')==protected
  # Verify source selection in actual decoded pixels, not only in the plan.
  from PIL import Image
  for t,channel in [(.5,0),(1.5,2)]:
   png=r/(str(t)+'.png');m.call([a.ffmpeg,'-v','error','-ss',str(t),'-i',str(r/'result.mp4'),'-frames:v','1',str(png)]);pixel=Image.open(png).convert('RGB').getpixel((20,1800));assert pixel[channel]>200 and sum(pixel)-pixel[channel]<40,pixel
  # 1.1x must retain pitch. Direct sinusoidal correlations detect both tones.
  pcm=m.call([a.ffmpeg,'-v','error','-i',str(r/'result.mp4'),'-vn','-ac','1','-ar','8000','-f','f32le','-'])
  import array
  xs=array.array('f');xs.frombytes(pcm)
  def power(start,freq):
   ys=xs[round(start*8000):round((start+.4)*8000)];n=len(ys)
   re=sum(y*math.cos(2*math.pi*freq*i/8000) for i,y in enumerate(ys));im=sum(y*math.sin(2*math.pi*freq*i/8000) for i,y in enumerate(ys));return (re*re+im*im)/n**2
  assert power(.25,440)>20*power(.25,484),'Mother audio pitch was shifted'
  assert power(1.25,880)>20*power(1.25,968),'Existing edit was sped up again'
  graphics=m.read(r/'run/graphics.json');first=graphics['measurements'][0];metrics=first['textMetrics'];style=m.read(a.style);assert any(t['kind']=='subtitle' and t['baseline']==style['subtitleBaseline'] for t in metrics)
  visual=copy.deepcopy(spec);visual['output']=str(r/'visual-only.mp4');visual['work']=str(r/'visual-run');visual['captions'][0]['text']='修订字幕';visual.update(audioCopyFrom=str(r/'result.mp4'),audioCopyPlan=str(r/'run/executed_plan.json'),audioCopySha256=m.sha(r/'result.mp4'))
  vp=r/'visual-plan.json';m.save(vp,visual);m.render(vp)
  packet_args=['-map','0:a:0','-c','copy','-f','adts','-']
  before=m.call([a.ffmpeg,'-v','error','-i',str(r/'result.mp4'),*packet_args]);after=m.call([a.ffmpeg,'-v','error','-i',str(r/'visual-only.mp4'),*packet_args]);assert before==after,'Visual-only revision changed AAC packets'
  print('PASS: source identity, pixel selection, exact frames, AV duration, pitch-preserving speed, existing rate, fixed baseline, source hash and immutable outputs')
if __name__=='__main__':main()
