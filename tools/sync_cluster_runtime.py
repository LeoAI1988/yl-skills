"""Mechanical packaging of one maintained installer; no personal settings."""
from pathlib import Path
import argparse
ROOT=Path(__file__).resolve().parents[1]
def validate():
    if (ROOT/'install.py').read_bytes()!=(ROOT/'yl-skill-sync/scripts/cluster_install.py').read_bytes():
        raise ValueError('Bundled installer differs from canonical implementation')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true');a=p.parse_args()
    if a.apply: (ROOT/'yl-skill-sync/scripts/cluster_install.py').write_bytes((ROOT/'install.py').read_bytes())
    validate();print('installer parity PASS')
