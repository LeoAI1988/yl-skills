"""Check common writing copies; --apply copies reviewed canonical edits locally."""
import argparse
from library import ROOT, NAME, read_json
from writing_foundation import SHARED_FILES, validate

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    release = read_json(ROOT/'release.json')
    members = [name for name, item in release['skills'].items() if item['category']=='writing']
    if any(not NAME.fullmatch(name) or (ROOT/name).is_symlink() or
           bool(getattr((ROOT/name).stat(), 'st_file_attributes', 0) & 0x400)
           for name in members):
        raise ValueError('Unsafe writing member directory')
    # Complete all path checks before any write; no linked nested files/directories.
    from library import file_map
    for name in members:
        file_map(ROOT/name)
    if args.apply:
        for name in members:
            if name == 'yl-writing':
                continue
            for rel in SHARED_FILES:
                target = ROOT/name/rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT/'yl-writing'/rel).read_bytes())
    validate(ROOT, release)
    print('Writing foundation copies are consistent; semantic review still required.')

if __name__ == '__main__':
    main()
