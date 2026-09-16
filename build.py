"""Build a reviewed, versioned, reproducible yl distribution."""
from pathlib import Path
import io
import json
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent/'tools'))
from library import (ROOT, VERSION, read_json, json_bytes, digest, file_map,
                     skill_metadata, check_links, project_map, hash_map)
from writing_foundation import validate as validate_writing_foundation

def prepare():
    release = read_json(ROOT/'release.json')
    if not VERSION.fullmatch(release['version']):
        raise ValueError('Invalid release version')
    reviews = read_json(ROOT/'reviews/skills.json')
    folders = {p.name: p for p in ROOT.iterdir() if p.is_dir() and (p/'SKILL.md').is_file()}
    if set(folders) != set(release['skills']):
        raise ValueError('Skill directories and release register differ')
    if set(reviews['skills']) != set(folders):
        raise ValueError('Missing or stale review entries')
    blobs = project_map()
    if hash_map(blobs) != reviews['project_files']:
        raise ValueError('Project files changed since review')
    skills = []
    for name, folder in sorted(folders.items()):
        meta = skill_metadata(folder)
        config = release['skills'][name]
        if not VERSION.fullmatch(config['version']):
            raise ValueError('Invalid member version: ' + name)
        meta.update(config)
        files = file_map(folder)
        if any(p != 'SKILL.md' and p.endswith('/SKILL.md') for p in files):
            raise ValueError('Nested installable Skill: ' + name)
        check_links(folder, files)
        review_files = dict(files)
        if name == 'yl-toolbox':
            review_files.pop('references/catalog.json', None)
        reviewed = reviews['skills'][name]
        if any(reviewed.get(k) != 'passed' for k in
               ('privacy_review', 'rights_review', 'method_review')):
            raise ValueError('Review not passed: ' + name)
        if hash_map(review_files) != reviewed['files']:
            raise ValueError('Skill changed after review: ' + name)
        meta['files'] = hash_map(files)
        skills.append(meta)
        blobs.update({name+'/'+rel: data for rel, data in files.items()})
    validate_writing_foundation(ROOT, release)
    catalog = {'version': release['version'],
               'skills': [{k:v for k,v in s.items() if k != 'files'}
                          for s in skills if s['name'] != 'yl-toolbox']}
    catalog_data = json_bytes(catalog)
    blobs['yl-toolbox/references/catalog.json'] = catalog_data
    for s in skills:
        if s['name'] == 'yl-toolbox':
            s['files']['references/catalog.json'] = digest(catalog_data)
    cluster = {'name': release['name'], 'version': release['version'],
               'date': release['date'], 'skills': skills}
    blobs['cluster.json'] = json_bytes(cluster)
    blobs['reviews/skills.json'] = (ROOT/'reviews/skills.json').read_bytes()
    return release, blobs

def main():
    release, blobs = prepare()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in sorted(blobs.items()):
            info = zipfile.ZipInfo('yl-toolbox-cluster/'+name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            z.writestr(info, data, compresslevel=9)
    packed = buffer.getvalue()
    versioned = ROOT/'releases'/('yl-toolbox-cluster-v'+release['version']+'.zip')
    if versioned.exists() and versioned.read_bytes() != packed:
        raise ValueError('Version already released with different bytes; increment release.json version')
    with zipfile.ZipFile(io.BytesIO(packed)) as z:
        if z.testzip() is not None or len(z.namelist()) != len(blobs):
            raise ValueError('Archive verification failed')
        for name, data in blobs.items():
            if z.read('yl-toolbox-cluster/'+name) != data:
                raise ValueError('Archive bytes differ')
    versioned.parent.mkdir(exist_ok=True)
    # Publish only after all checks, including the immutable version check, pass.
    for name in ('yl-toolbox/references/catalog.json', 'cluster.json'):
        (ROOT/name).write_bytes(blobs[name])
    for output in (versioned, ROOT/'yl-toolbox-cluster.zip'):
        output.write_bytes(packed)
        output.with_suffix('.zip.sha256').write_text(
            digest(packed)+'  '+output.name+'\n', encoding='utf-8')
    print(json.dumps({'version': release['version'], 'skills': len(release['skills']),
                      'files': len(blobs), 'sha256': digest(packed),
                      'zip_byte_comparison': 'PASS'}, ensure_ascii=False))

if __name__ == '__main__':
    main()
