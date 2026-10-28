"""Timing invariants and an optional real FFmpeg render using synthetic media."""
from pathlib import Path
import copy,json,os,subprocess,tempfile,unittest
from unittest.mock import patch
import dialogue_timeline as d

def fake_probe(path,tool):
    return {'streams':[{'codec_type':'video','width':96,'height':160,'avg_frame_rate':'24/1','r_frame_rate':'24/1','nb_frames':'120','duration':'5'}, {'codec_type':'audio','duration':'5'}],'format':{'duration':'5'}}

class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'source.mp4').write_bytes(b'synthetic placeholder for metadata unit tests')
        self.plan={'fps':24,'canvas':[96,160],'sources':[{'id':'s','video':'source.mp4'}],
                   'segments':[{'id':'q','source':'s','start_frame':0,'end_frame':24,'speed':1.12}, {'id':'a','source':'s','start_frame':32,'end_frame':80,'speed':1.05}],
                   'captions':[{'source':'s','start_frame':0,'end_frame':24,'text':'Question'}, {'source':'s','start_frame':32,'end_frame':80,'text':'Answer'}]}
    def tearDown(self):self.temp.cleanup()
    def compile(self,plan=None):
        p=self.root/'plan.json';d.write(p,plan or self.plan)
        with patch.object(d,'probe',fake_probe):return d.compile_plan(p)
    def test_rounding_and_caption_alignment(self):
        e=self.compile();self.assertEqual(e['frames'],round(24/1.12)+round(48/1.05))
        self.assertEqual(e['captions'][1]['start'],e['segments'][1]['output_start'])
        for s in e['segments']:
            self.assertAlmostEqual((s['end_frame']-s['start_frame'])/24/s['applied_speed'],s['output_frames']/24)
    def test_restore_real_pause_preserves_following_mapping(self):
        before=self.compile();self.plan['segments'][0]['end_frame']=30;after=self.compile()
        self.assertGreater(after['segments'][0]['output_frames'],before['segments'][0]['output_frames'])
        self.assertEqual(before['segments'][1]['source_frames'],after['segments'][1]['source_frames'])
        self.assertEqual(before['segments'][1]['applied_speed'],after['segments'][1]['applied_speed'])
    def test_caption_repetition_creates_separate_intervals(self):
        self.plan['segments'].append(dict(self.plan['segments'][0],id='q-again'))
        e=self.compile();self.assertEqual([c['text'] for c in e['captions']],['Question','Answer','Question'])
        self.assertEqual(e['captions'][-1]['start'],e['segments'][-1]['output_start'])
    def test_reject_invalid_or_overlapping_inputs(self):
        bad=[]
        p=copy.deepcopy(self.plan);p['segments'][0]['end_frame']=121;bad.append(p)
        p=copy.deepcopy(self.plan);p['segments'][0]['speed']=float('nan');bad.append(p)
        p=copy.deepcopy(self.plan);p['segments'][1]['id']='q';bad.append(p)
        p=copy.deepcopy(self.plan);p['captions'][0]['end_frame']=70;bad.append(p)
        p=copy.deepcopy(self.plan);p['sources'][0]['crop']=[0,0,96,96];bad.append(p)
        for p in bad:
            with self.subTest(plan=p),self.assertRaises(ValueError):self.compile(p)
    def test_reject_changed_source_before_encoding(self):
        e=self.compile();(self.root/'source.mp4').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'Input changed'):d.render(e,self.root/'out.mp4',self.root)

@unittest.skipUnless(os.environ.get('YL_TEST_FFMPEG') and os.environ.get('YL_TEST_FFPROBE'),'Set FFmpeg/FFprobe paths to run real-media validation')
class RealMediaTests(unittest.TestCase):
    def test_render_decode_and_selected_frames(self):
        import cv2,numpy as np
        from PIL import Image
        ff=os.environ['YL_TEST_FFMPEG'];fp=os.environ['YL_TEST_FFPROBE']
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);source=root/'source.mp4'
            subprocess.run([ff,'-v','error','-f','lavfi','-i','testsrc2=size=96x160:rate=24:duration=1','-f','lavfi','-i','sine=frequency=600:sample_rate=48000:duration=1','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(source)],check=True)
            overlay=Image.new('RGBA',(96,160));overlay.paste((255,0,0,255),(0,0,20,20));overlay.save(root/'overlay.png')
            plan={'fps':24,'canvas':[96,160],'sources':[{'id':'a','video':'source.mp4'}],
                  'segments':[{'id':'one','source':'a','start_frame':0,'end_frame':12,'speed':1.2}, {'id':'two','source':'a','start_frame':16,'end_frame':24,'speed':.9}],
                  'captions':[{'source':'a','start_frame':0,'end_frame':12,'text':'A'}, {'source':'a','start_frame':16,'end_frame':24,'text':'B'}],
                  'overlays':[{'source':'a','start_frame':0,'end_frame':24,'image':'overlay.png'}]}
            d.write(root/'plan.json',plan);e=d.compile_plan(root/'plan.json',fp);out=root/'out.mp4';report=d.render(e,out,root,ff,fp)
            self.assertEqual(report['decode'],'passed');self.assertEqual(report['frames'],19)
            cap=cv2.VideoCapture(str(source));src=[]
            while True:
                ok,f=cap.read()
                if not ok:break
                src.append(f)
            cap.release();cap=cv2.VideoCapture(str(out));mapping=[n for s in e['segments'] for n in s['source_frames']]
            for n in mapping:
                ok,f=cap.read();self.assertTrue(ok)
                self.assertLess(float(np.abs(f[25:].astype(float)-src[n][25:].astype(float)).mean()),8)
                self.assertGreater(float(f[3:15,3:15,2].mean()),235)
            self.assertFalse(cap.read()[0]);cap.release()
            with self.assertRaisesRegex(ValueError,'new output'):d.render(e,out,root,ff,fp)

if __name__=='__main__':unittest.main()
