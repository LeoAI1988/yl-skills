"""Signal test: additive mono voice protection and playback pause gating. MIT."""
import numpy as np
from balance_playback import balance


def main():
    sr=16000;rng=np.random.default_rng(8);n=8*sr;y=np.zeros((n,2),dtype='float32');t=np.arange(2*sr)/sr
    far=np.column_stack([.12*np.sin(2*np.pi*340*t)+.04*rng.normal(size=len(t)),
                         .13*np.sin(2*np.pi*340*t)+.04*rng.normal(size=len(t))]).astype('float32')
    y[sr:3*sr]=far;y[4*sr:6*sr]=far;y[round(5.8*sr):6*sr]=0
    voice=.008*np.sin(2*np.pi*217*np.arange(n)/sr).astype('float32')
    y[:sr]+=voice[:sr,None];y[7*sr:]+=voice[7*sr:,None]
    plan={'reference_spans_reviewed':True,'lecturer_check_windows':[[0,.8],[7,7.8]],
          'spans':[{'type':'reference_overlap','start':4,'end':6,'gain_db':-30,'reason':'Synthetic double talk',
                    'reference_delta':3,'fit':[4.1,5.5],'reference_playback_only_confirmed':True}]}
    base,_=balance(y,sr,plan);mixed=y.copy();mixed[4*sr:6*sr]+=voice[4*sr:6*sr,None];z,_=balance(mixed,sr,plan)
    assert np.max(abs((z-base)[4*sr:6*sr]-voice[4*sr:6*sr,None]))<2e-7
    assert np.array_equal(z[:4*sr],mixed[:4*sr])
    assert np.max(abs(base[round(5.85*sr):round(5.97*sr)]))<1e-6
    ratio=np.std(base[round(4.1*sr):round(5.5*sr)])/np.std(y[round(4.1*sr):round(5.5*sr)])
    assert .025<ratio<.04,ratio
    print('PASS: playback attenuated 30 dB; mono speech unchanged; pause gating; other samples untouched')


if __name__=='__main__':main()
