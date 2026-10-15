"""Isolated FFmpeg behavior test; generated media never enters the Skill tree. MIT."""
import argparse
import copy
import tempfile
import subprocess
from pathlib import Path
import course_edit as c


def rejected(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError('Expected rejection')


def main():
    p = argparse.ArgumentParser(); p.add_argument('--ffmpeg', required=True); p.add_argument('--ffprobe', required=True)
    a = p.parse_args()
    with tempfile.TemporaryDirectory(prefix='yl-course-test-') as tmp:
        root = Path(tmp); src = root/'source.mp4'
        subprocess.run([a.ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=540x360:rate=30:duration=4',
                        '-f', 'lavfi', '-i', 'sine=frequency=700:duration=4', '-c:v', 'libx264', '-c:a', 'aac', '-shortest', str(src)], check=True)
        asr = {'duration': 4, 'segments': [{'words': [{'word': '这个', 'start': .2, 'end': .5},
               {'word': '这个', 'start': .5, 'end': .8}, {'word': '演示', 'start': 2.2, 'end': 2.8}]}]}
        c.write(root/'asr.json', asr)
        cc = c.candidates(asr)
        assert {z['type'] for z in cc} >= {'filler', 'stutter', 'gap', 'asr-negative'}
        plan = {'schema_version': 1, 'workdir': str(root/'work'), 'output': str(root/'lesson.mp4'),
                'fps': 30, 'speed': 1.1, 'size': [540, 360], 'style': {'font': 'Arial'},
                'sources': {'a': {'path': str(src), 'sha256': c.sha(src), 'asr': str(root/'asr.json')}},
                'candidates': [{'id': z['id'], 'action': 'keep', 'reason': 'Synthetic input'} for z in cc],
                'parts': [{'source': 'a', 'keeps': [[0, 1], [2, 3]], 'bounds': [0, 3],
                           'captions': [{'start': .2, 'end': .8, 'text': 'Demo'}, {'start': 2.2, 'end': 2.8, 'text': 'Result'}], 'mute': []}]}
        prepared = c.prepare(plan, a.ffprobe)
        assert len(prepared['mapping']) == 2 and len(prepared['captions']) == 2
        assert prepared['mapping'][1]['offset'] == 1
        bad = copy.deepcopy(plan); bad['candidates'][0]['action'] = 'pending'
        rejected(lambda: c.prepare(bad, a.ffprobe))
        bad = copy.deepcopy(plan); bad['sources']['a']['sha256'] = '0'*64
        rejected(lambda: c.prepare(bad, a.ffprobe))
        bad = copy.deepcopy(plan); bad['parts'][0]['keeps'][1][1] = 2.5
        rejected(lambda: c.prepare(bad, a.ffprobe))
        bad = copy.deepcopy(plan); bad['parts'][0]['mute'] = [{'start': .2, 'end': .5, 'kind': 'speech', 'reason': 'Must reject'}]
        rejected(lambda: c.prepare(bad, a.ffprobe))
        bad = copy.deepcopy(plan); bad['parts'][0]['captions'][0]['end'] = 2.8
        rejected(lambda: c.prepare(bad, a.ffprobe))
        c.render(plan, prepared, a.ffmpeg)
        c.write(root/'work/prepared.json', prepared)
        result = c.verify(plan, prepared, a.ffmpeg, a.ffprobe)
        assert result['technical_decode'] == 'pass' and result['actual_listening'] == 'pending'
        rejected(lambda: c.render(plan, prepared, a.ffmpeg))
        print('PASS: candidates, unresolved gate, source hash, word coverage, speech mute refusal, cut-split subtitles, actual render/decode, overwrite refusal')


if __name__ == '__main__':
    main()
