"""Regression checks: operation scope, decimal rates, source edits and stale links."""
import copy,hashlib,tempfile
from pathlib import Path
from verify_revision_contract import verify
with tempfile.TemporaryDirectory() as d:
    p=Path(d)/'final.mp4';p.write_bytes(b'synthetic binding evidence')
    c={'requestedRate':'1.15','audioTempo':1.15,'previewRate':1.15,
       'edl':{'source':'camera','fps':30,'playbackRate':1.15,'outputFrames':60,'keeps':[
           {'sourceStartFrame':0,'sourceEndFrame':30,'role':'hook','existingRate':1,'appliedRate':1.15},
           {'sourceStartFrame':0,'sourceEndFrame':39,'role':'main','existingRate':1,'appliedRate':1.15}]},
       'operations':[{'id':'cut','kind':'delete_audio_text','status':'done','role':'main','text':'failed start','expectedRemainingCount':0,'sourceRanges':[{'source':'camera','start':39,'end':45}]},
                     {'id':'hook','kind':'copy_hook','status':'done','sourceRanges':[{'source':'camera','start':0,'end':30}]}],
       'finalText':'complete thought','measured':{'frames':60,'audioDuration':2},
       'enhancementInput':{'frames':60,'audioDuration':2,'hookCoverageChecked':True},
       'finalVideo':str(p),'previewVideo':str(p),'videoSha256':hashlib.sha256(p.read_bytes()).hexdigest(),'previewSha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    assert verify(c)['status']=='PASS'
    def fail(change):
        x=copy.deepcopy(c);change(x);assert verify(x)['status']=='FAIL',x
    fail(lambda x:x['edl'].update(playbackRate=1.5))
    fail(lambda x:x['edl']['keeps'][1].update(sourceEndFrame=42))
    fail(lambda x:x.update(finalText='failed start complete thought'))
    fail(lambda x:x['edl']['keeps'][1].update(role='hook'))
    fail(lambda x:x['enhancementInput'].update(frames=59))
    fail(lambda x:x['enhancementInput'].update(audioDuration=1))
    fail(lambda x:x.update(previewVideo=str(p.with_name('old.mp4'))))
    # Hook-only deletion must preserve the original occurrence in main.
    x=copy.deepcopy(c);x['operations']=[{'id':'hook cut','kind':'delete_audio_text','status':'done','role':'hook','sourceRanges':[{'source':'camera','start':30,'end':39}]}]
    assert verify(x)['status']=='PASS'
print('PASS: typed deletions, copy scope, exact decimal speed, enhancement duration, stale links')

# Verify the SDK route snapshot without a network call or consuming a task.
import sys,types
import kaipai_enhance as wrapper
config=types.ModuleType('sdk.core.config');api=types.ModuleType('sdk.core.api')
api._deep_merge_params=lambda base,override:{**base,**override}
sys.modules['sdk.core.config']=config;sys.modules['sdk.core.api']=api
for route in ('mtlab','speedup'):
    config.INVOKE={'hdvideoallinone':{'task':'/v1/hdvideoallinone_async','task_type':route,'params':{}}}
    assert wrapper.effective_preset('hdvideoallinone',{})['taskType']==route
for spec in ({'task':'/v1/other','task_type':'speedup','params':{}},
             {'task':'/v1/hdvideoallinone_async','task_type':'unknown','params':{}},
             {'task':'/v1/hdvideoallinone_async','task_type':'speedup','params':{'unverified':1}}):
    config.INVOKE={'hdvideoallinone':spec}
    try:wrapper.effective_preset('hdvideoallinone',{})
    except wrapper.GateError:pass
    else:raise AssertionError('unverified preset accepted')
print('PASS: verified SDK routes accepted, unknown route/path/params rejected without submission')
