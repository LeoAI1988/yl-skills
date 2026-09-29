"""Whole-cluster install and explicit host mappings; no auto-discovered installations."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.request
import zipfile
from cluster_install import install, contents, linked, make_link, child

def acquire(value, expected=None):
    if not value.startswith('https://'):
        if '://' in value: raise ValueError('Only local directories or HTTPS archives')
        return Path(value).expanduser().resolve()
    if not expected or not re.fullmatch('[a-fA-F0-9]{64}',expected): raise ValueError('HTTPS source requires separately obtained SHA-256')
    cache=Path(os.environ.get('YL_RELEASE_CACHE',str(Path.home()/'.cache/yl-toolbox/releases')))
    cache.mkdir(parents=True,exist_ok=True)
    with urllib.request.urlopen(value,timeout=30) as response: data=response.read(256*1024*1024+1)
    if len(data)>256*1024*1024 or hashlib.sha256(data).hexdigest()!=expected.lower(): raise ValueError('Package size/hash failed')
    folder=cache/expected.lower()
    if folder.exists():
        root=folder/'yl-toolbox-cluster'
        if not (root/'cluster.json').is_file(): raise ValueError('Incomplete release cache')
        return root
    import io
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names=set();total=0
        for item in z.infolist():
            name=item.filename;parts=name.rstrip('/').split('/')
            if not parts or parts[0]!='yl-toolbox-cluster' or any(v in ('','.','..') for v in parts) or '\\' in name or ':' in name: raise ValueError('Unsafe archive member')
            if name in names or ((item.external_attr>>16)&0o170000)==0o120000: raise ValueError('Duplicate archive member or link')
            names.add(name);total+=item.file_size
        if total>512*1024*1024: raise ValueError('Unpacked archive too large')
        stage=Path(tempfile.mkdtemp(prefix='.download-',dir=cache));z.extractall(stage)
        if not (stage/'yl-toolbox-cluster/cluster.json').is_file(): raise ValueError('No cluster manifest')
        stage.rename(folder)
    return folder/'yl-toolbox-cluster'

def map_hosts(target, destinations, dry_run=False):
    target=target.expanduser().absolute()
    meta=json.loads((target/'.yl-cluster-install.json').read_text(encoding='utf-8'));planned=[]
    for value in destinations:
        dest=value.expanduser().absolute()
        if dest.resolve()==target.resolve(): raise ValueError('Cannot map primary to itself')
        if target.resolve() in dest.resolve().parents or dest.resolve() in target.resolve().parents:
            raise ValueError('Host roots must not overlap')
        for info in meta['skills'].values():
            core=Path(info['source']).resolve()
            if dest.resolve()==core or core in dest.resolve().parents or dest.resolve() in core.parents:
                raise ValueError('Host root overlaps a core member')
        if linked(dest): raise ValueError('Host skills root itself is linked')
        for name,info in meta['skills'].items():
            src=child(target,name);dst=child(dest,name)
            if contents(src,allow_root_link=True)!=info['files']: raise ValueError('Primary core drift: '+name)
            if dst.exists() or linked(dst):
                if not linked(dst) or dst.resolve()!=src.resolve(): raise ValueError('Host conflict; preserve entry: '+str(dst))
            else: planned.append((src,dst))
    created=[]
    if not dry_run:
        try:
            for src,dst in planned:
                dst.parent.mkdir(parents=True,exist_ok=True);make_link(dst,src);created.append(dst)
                if contents(dst,allow_root_link=True)!=meta['skills'][dst.name]['files']: raise ValueError('Mapped hashes differ')
        except Exception:
            for dst in reversed(created):
                if os.name=='nt': os.rmdir(dst)
                else: dst.unlink()
            raise
    return {'status':'dry_run' if dry_run else 'mapped','new_links':len(planned),'targets':[str(p) for p in destinations],'copies':0}

def status(target,destinations):
    meta=json.loads((target/'.yl-cluster-install.json').read_text(encoding='utf-8'));problems=[]
    for name,info in meta['skills'].items():
        p=child(target,name)
        if not p.exists() or contents(p,allow_root_link=True)!=info['files']: problems.append(name+': primary missing/drift')
        for dest in destinations:
            q=child(dest,name)
            if not linked(q) or q.resolve()!=p.resolve(): problems.append(name+': host missing/wrong mapping')
    return {'status':'PASS' if not problems else 'INCOMPLETE','version':meta['version'],'members':len(meta['skills']),'problems':problems,'runtime_invocation_tested':False}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['install','map','status'])
    p.add_argument('--source');p.add_argument('--sha256');p.add_argument('--target',required=True,type=Path)
    p.add_argument('--map-target',action='append',type=Path,default=[]);p.add_argument('--upgrade',action='store_true');p.add_argument('--dry-run',action='store_true');a=p.parse_args()
    try:
        if a.command=='install':
            if not a.source: raise ValueError('--source required')
            if a.map_target: raise ValueError('Run map after verified primary installation')
            result=install(acquire(a.source,a.sha256),a.target,upgrade=a.upgrade,dry_run=a.dry_run)
        elif a.command=='map': result=map_hosts(a.target,a.map_target,a.dry_run)
        else: result=status(a.target,a.map_target)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 2 if result.get('status')=='INCOMPLETE' else 0
    except (ValueError,OSError,KeyError) as exc:
        print(json.dumps({'status':'ERROR','error':str(exc)},ensure_ascii=False));return 2

if __name__=='__main__':sys.exit(main())
