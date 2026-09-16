"""Isolated acceptance checks for the actual archive and installer."""
from pathlib import Path
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from library import ROOT, digest, read_json
from check_updates import compare


def run(root, target, *flags, ok=True):
    proc = subprocess.run([sys.executable, '-B', str(root/'install.py'),
                           '--target', str(target), *flags],
                          capture_output=True, text=True, encoding='utf-8',
                          env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUTF8': '1'})
    if (proc.returncode == 0) != ok:
        raise AssertionError(proc.stdout + proc.stderr)
    return proc


def main():
    spec = importlib.util.spec_from_file_location('yl_build', ROOT/'build.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    release, blobs = module.prepare()
    archive = ROOT/'yl-toolbox-cluster.zip'
    packed = archive.read_bytes()
    versioned = ROOT/'releases'/('yl-toolbox-cluster-v'+release['version']+'.zip')
    assert versioned.read_bytes() == packed
    assert archive.with_suffix('.zip.sha256').read_text().split()[0] == digest(packed)
    passed = []
    with tempfile.TemporaryDirectory(prefix='yl-cluster-verify-') as temp:
        work = Path(temp)
        with zipfile.ZipFile(archive) as z:
            expected_names = {'yl-toolbox-cluster/'+n for n in blobs}
            assert set(z.namelist()) == expected_names
            assert len(z.namelist()) == len(expected_names)
            assert z.testzip() is None
            for name, data in blobs.items():
                assert z.read('yl-toolbox-cluster/'+name) == data
            z.extractall(work/'unpacked')
        passed.append('archive members, hashes and bytes')
        unpacked = work/'unpacked/yl-toolbox-cluster'
        target = work/'agent-skills'
        run(unpacked, target, '--dry-run')
        assert not target.exists()
        passed.append('dry-run writes nothing')
        run(unpacked, target)
        catalog = read_json(unpacked/'cluster.json')
        for item in catalog['skills']:
            for rel, sha in item['files'].items():
                assert digest((target/item['name']/rel).read_bytes()) == sha
        passed.append('isolated installation and every file hash')
        run(unpacked, target)
        passed.append('identical installation is idempotent')
        modified = target/'yl-writing/SKILL.md'
        modified.write_text(modified.read_text(encoding='utf-8')+'\nLocal user edit\n', encoding='utf-8')
        before = modified.read_bytes()
        run(unpacked, target, ok=False)
        assert modified.read_bytes() == before
        passed.append('different installation refused, edits retained')
        bad_src = unpacked/'yl-writing/SKILL.md'
        bad_src.write_bytes(bad_src.read_bytes()+b'\nCorrupted package\n')
        rejected_build = subprocess.run([sys.executable, '-B', str(unpacked/'build.py')],
                                       capture_output=True, text=True, encoding='utf-8',
                                       env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUTF8': '1'})
        assert rejected_build.returncode != 0
        assert not (unpacked/'yl-toolbox-cluster.zip').exists()
        assert 'changed after review' in rejected_build.stderr
        passed.append('post-review change refused by build before producing an archive')
        untouched = work/'fresh-target'
        run(unpacked, untouched, ok=False)
        assert not untouched.exists()
        passed.append('corrupted package refused before any installation')
        bad_src.write_bytes(blobs['yl-writing/SKILL.md'])
        bad_catalog = read_json(unpacked/'cluster.json')
        bad_catalog['skills'].append(bad_catalog['skills'][0])
        (unpacked/'cluster.json').write_text(json.dumps(bad_catalog), encoding='utf-8')
        run(unpacked, untouched, ok=False)
        assert not untouched.exists()
        passed.append('duplicate manifest member refused')
        daily = work/'daily'
        daily.mkdir()
        (daily/'SKILL.md').write_bytes(b'original')
        snapshot = {'files': {'SKILL.md': digest(b'original')}}
        assert compare(daily, snapshot)['status'] == 'unchanged'
        (daily/'SKILL.md').write_bytes(b'changed')
        (daily/'new.txt').write_bytes(b'new')
        outcome = compare(daily, snapshot)
        assert outcome['changed'] == ['SKILL.md'] and outcome['added'] == ['new.txt']
        (daily/'SKILL.md').unlink()
        assert compare(daily, snapshot)['removed'] == ['SKILL.md']
        assert compare(work/'missing-source', snapshot)['status'] == 'source_missing'
        try:
            compare(daily, {'files': {'../outside': 'x'}})
        except ValueError:
            pass
        else:
            raise AssertionError('unsafe snapshot path accepted')
        passed.append('source comparison unchanged, changed, added, removed, missing and unsafe path')
    print(json.dumps({'status': 'PASS', 'checks': passed, 'skills': len(release['skills']),
                      'files': len(blobs), 'full_video_or_writing_quality_tested': False},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
