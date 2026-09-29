"""Install/upgrade the whole reviewed cluster; personal configuration is never touched."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone

def linked(path):
    try:
        return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)
    except FileNotFoundError:
        return False

def contents(root, allow_root_link=False):
    if (linked(root) and not allow_root_link) or any(linked(p) for p in root.rglob('*')):
        raise ValueError('Nested linked paths are not supported')
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}

def make_link(dst, src):
    if os.name == 'nt':
        env={**os.environ,'YL_MAP_SOURCE':str(src),'YL_MAP_TARGET':str(dst)}
        subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',
                        "$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path $env:YL_MAP_TARGET -Target $env:YL_MAP_SOURCE | Out-Null"],
                       env=env,check=True,capture_output=True)
    else:
        dst.symlink_to(src,target_is_directory=True)

def child(target, name):
    if not re.fullmatch(r'yl-[a-z0-9]+(?:-[a-z0-9]+)*',name): raise ValueError('Invalid skill name')
    dst=target/name
    if dst.parent != target: raise ValueError('Unsafe target')
    return dst

def install(source,target,upgrade=False,link=False,dry_run=False,backup_root=None):
    source=Path(source).expanduser().resolve();target=Path(target).expanduser().absolute()
    if target.resolve()==source or source in target.resolve().parents or target.resolve() in source.parents:
        raise ValueError('Target must be separate from distribution')
    if linked(target): raise ValueError('Agent skills root itself must not be a link')
    catalog=json.loads((source/'cluster.json').read_text(encoding='utf-8-sig'))
    manifest=target/'.yl-cluster-install.json'
    old=json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {'skills':{}}
    if old.get('target') and old['target'] != str(target): raise ValueError('Installation record target mismatch')
    desired={};actions=[]
    for item in catalog['skills']:
        name=item['name'];dst=child(target,name);src=source/name
        if name in desired or linked(src) or not (src/'SKILL.md').is_file(): raise ValueError('Invalid source or duplicate manifest member')
        for rel in item['files']:
            if not rel or '\\' in rel or ':' in rel or any(v in ('','.','..') for v in rel.split('/')):
                raise ValueError('Invalid manifest file path')
        expected=contents(src)
        if expected!=item['files']: raise ValueError('Package integrity check failed: '+name)
        desired[name]={'files':expected,'mode':'link' if link else 'copy','source':str(src)}
        exists=dst.exists() or linked(dst)
        if exists:
            same=dst.is_dir() and contents(dst,allow_root_link=True)==expected
            same_mode=(linked(dst) and dst.resolve()==src) if link else not linked(dst)
            if same and same_mode: continue
            previous=old.get('skills',{}).get(name)
            if not upgrade or not previous: raise ValueError('Unmanaged/different installation; back up and migrate first: '+name)
            if linked(dst) and dst.resolve()!=Path(previous['source']).resolve(): raise ValueError('Managed link changed target: '+name)
            if contents(dst,allow_root_link=True)!=previous['files']: raise ValueError('Local core edits; review before upgrading: '+name)
        actions.append((name,'replace' if exists else 'create'))
    for name,previous in old.get('skills',{}).items():
        if name in desired: continue
        dst=child(target,name)
        if not upgrade: raise ValueError('Removed members require --upgrade')
        if not dst.is_dir() or contents(dst,allow_root_link=True)!=previous['files']: raise ValueError('Retired member changed or missing')
        if linked(dst) and dst.resolve()!=Path(previous['source']).resolve(): raise ValueError('Retired link target changed')
        actions.append((name,'retire'))
    if dry_run: return {'status':'dry_run','version':catalog['version'],'skills':list(desired),'actions':actions,'personal_config':'untouched'}
    backup_base=Path(backup_root).expanduser().absolute() if backup_root else target.parent/'yl-cluster-backups'
    if backup_base.resolve()==target.resolve() or target.resolve() in backup_base.resolve().parents or source in backup_base.resolve().parents:
        raise ValueError('Backup must be outside core/skills directories')
    target.mkdir(parents=True,exist_ok=True);backup_base.mkdir(parents=True,exist_ok=True)
    backup=Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S-'),dir=backup_base))
    stage=Path(tempfile.mkdtemp(prefix='.yl-stage-',dir=target.parent))
    changed=[];original_manifest=manifest.read_bytes() if manifest.exists() else None
    try:
        for name,action in actions:
            if action=='retire': continue
            if link: make_link(stage/name,source/name)
            else: shutil.copytree(source/name,stage/name,ignore=shutil.ignore_patterns('__pycache__'))
            if contents(stage/name,allow_root_link=True)!=desired[name]['files']: raise ValueError('Staged integrity failure')
        for name,action in actions:
            dst=child(target,name);had_old=dst.exists() or linked(dst)
            if had_old: shutil.move(str(dst),str(backup/name))
            changed.append((name,had_old))
            if action!='retire': (stage/name).rename(dst)
        for name,item in desired.items():
            if contents(target/name,allow_root_link=True)!=item['files']: raise ValueError('Installed integrity failure')
        data={'version':catalog['version'],'target':str(target),'skills':desired,'backup':str(backup)}
        tmp=manifest.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');os.replace(tmp,manifest)
    except Exception:
        for name,had_old in reversed(changed):
            dst=child(target,name)
            if dst.exists() or linked(dst): dst.rename(stage/(name+'-failed'))
            if had_old: shutil.move(str(backup/name),str(dst))
        if original_manifest is not None: manifest.write_bytes(original_manifest)
        elif manifest.exists(): manifest.unlink()
        raise
    finally:
        for entry in stage.iterdir():
            if linked(entry):
                if os.name=='nt': os.rmdir(entry)
                else: entry.unlink()
            elif entry.is_dir(): shutil.rmtree(entry)
            else: entry.unlink()
        stage.rmdir()
    return {'status':'installed','version':catalog['version'],'skills':list(desired),'backup':str(backup),
            'personal_config':'untouched','next':'Reload Agent skills list; map other hosts to this installation'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--target',required=True,type=Path)
    p.add_argument('--dry-run',action='store_true');p.add_argument('--upgrade',action='store_true')
    p.add_argument('--link',action='store_true',help='Link to this permanent shared core, never temporary extraction')
    p.add_argument('--backup-root',type=Path);a=p.parse_args()
    try: result=install(Path(__file__).resolve().parent,a.target,a.upgrade,a.link,a.dry_run,a.backup_root)
    except (ValueError,OSError,KeyError) as exc: p.error(str(exc))
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
