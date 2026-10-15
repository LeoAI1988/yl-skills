"""Narrow stereo-side reference subtraction, external NumPy/SciPy required. MIT."""
import argparse, json
from pathlib import Path


def balance(y, sr, plan):
    import numpy as np
    from scipy import signal, linalg
    from numpy.lib.stride_tricks import sliding_window_view
    if y.ndim != 2 or y.shape[1] != 2 or y.dtype.kind != 'f':
        raise ValueError('Use floating-point stereo PCM')
    if not plan.get('reference_spans_reviewed'):
        raise ValueError('Reference spans need original-source review')
    checks = plan.get('lecturer_check_windows', [])
    if len(checks) < 2:
        raise ValueError('At least two lecturer-only windows required')
    mono = []
    for a,b in checks:
        x = y[round(a*sr):round(b*sr)]
        if len(x) < sr/5 or np.std(x) < 1e-5:
            raise ValueError('Invalid lecturer window')
        rel = 20*np.log10((np.std(x[:,0]-x[:,1])+1e-12)/np.std(x.mean(axis=1)))
        if rel > -35:
            raise ValueError('Lecturer not sufficiently mono; use another method')
        mono.append(float(rel))
    z=y.copy(); d=(y[:,0]-y[:,1])/2; taps=int(plan.get('taps',33))
    if not 3<=taps<=129 or taps%2==0:
        raise ValueError('Odd FIR tap count 3..129 required')
    pad=taps//2; D=sliding_window_view(np.pad(d,(pad,pad)),taps)
    refs=[sliding_window_view(np.pad(y[:,ch],(pad,pad)),taps) for ch in range(2)]
    rows=[];last=0
    for item in plan['spans']:
        s=round(item['start']*sr);e=round(item['end']*sr)
        if not 0<=s<e<=len(y) or s<last or not item.get('reason'):
            raise ValueError('Invalid/unreviewed/overlapping span')
        last=e; gd=item['gain_db']
        if not -60<=gd<=0:
            raise ValueError('Only playback attenuation supported')
        gain=10**(gd/20);env=np.ones(e-s);nf=min(round(.003*sr),len(env)//2)
        env[:nf]=np.linspace(0,1,nf);env[-nf:]=np.linspace(1,0,nf);env=env[:,None]
        if item['type']=='playback_only':
            z[s:e]=y[s:e]*(1-env*(1-gain))
        elif item['type']=='reference_overlap':
            if not item.get('reference_playback_only_confirmed'):
                raise ValueError('Reference may contain lecturer')
            ta,tb=item['fit'];ss=round(ta*sr);ee=round(tb*sr);off=round(item['reference_delta']*sr)
            if not s<=ss<ee<=e or ee-ss<sr/5:
                raise ValueError('Fit must be within target')
            if not pad<=s-off<e-off<s-pad:
                raise ValueError('Reference must be earlier and separate')
            q=d[ss:ee];center=ss-off;radius=round(.0005*sr)
            ref=d[center-radius:ee-off+radius+1]
            corr=signal.correlate(ref,q,'valid',method='fft');off-=int(np.argmax(corr))-radius
            A=D[ss-off:ee-off].astype('float64');aa=A[::4]
            h=linalg.solve(aa.T@aa+np.eye(taps)*1e-7,aa.T@q[::4],assume_a='pos')
            pred=np.column_stack([r[s-off:e-off]@h for r in refs]);pd=(pred[:,0]-pred[:,1])/2
            win=np.ones(max(3,round(.006*sr)))
            num=signal.fftconvolve(pd*d[s:e],win,mode='same');den=signal.fftconvolve(pd*pd,win,mode='same')
            gate=np.clip(num/(den+1e-10),0,1.15)
            z[s:e]=y[s:e]-env*(1-gain)*pred*gate[:,None]
            item={**item,'actual_reference_delta':off/sr,
                  'side_fit_error_db':float(20*np.log10((np.std(q-A@h)+1e-12)/(np.std(q)+1e-12)))}
        else:
            raise ValueError('Unsupported span type')
        def rms(x):return float(20*np.log10(np.sqrt(np.mean(np.asarray(x,dtype='float64')**2))+1e-12))
        rows.append({**item,'before_rms_db':rms(y[s:e]),'after_rms_db':rms(z[s:e])})
    return z,{'spans':rows,'lecturer_lr_relative_db':mono,'actual_listening':'pending',
              'separation_quality':'requires original-source review; lossy residual may remain'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('audio','plan','output','report'):p.add_argument('--'+key,required=True)
    a=p.parse_args();out=Path(a.output);report=Path(a.report)
    if out.exists() or report.exists():raise ValueError('Use new versions; overwrite refused')
    from scipy.io import wavfile
    sr,y=wavfile.read(a.audio);plan=json.loads(Path(a.plan).read_text(encoding='utf-8-sig'))
    z,r=balance(y,sr,plan);wavfile.write(out,sr,z.astype('float32'))
    report.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
