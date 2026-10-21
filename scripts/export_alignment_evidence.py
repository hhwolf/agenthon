"""Export compact, deterministic score evidence; never copy raw panels/answers."""
import argparse
import gzip
import json
from pathlib import Path
import shutil

from t2eval.final_alignment import dump, sha, summarize

p=argparse.ArgumentParser();p.add_argument('--work',type=Path,default=Path('.eval/final_alignment'))
p.add_argument('--out',type=Path,default=Path('reports/final_alignment/evidence'));a=p.parse_args()
a.out.mkdir(parents=True,exist_ok=True)
runs={'development-v3':'development','confirmation':'confirmation','old-reference-v2':'old-reference','old-reference-final':'old-reference-final','old-regression':'old-regression'}
for source,target in runs.items():
    root=a.work/source
    summarize(root)
    for name in ['cards.csv','horizons.csv','identity.json']:
        destination=a.out/(target+'-'+name+'.gz')
        destination.write_bytes(gzip.compress((root/name).read_bytes(),mtime=0))
    for name in ['summary.csv','paired.json']:
        shutil.copyfile(root/name,a.out/(target+'-'+name))
for name in ['roster.json','omissions.json','reserved-windows.json','provenance.json']:
    (a.out/('data-'+name+'.gz')).write_bytes(gzip.compress((a.work/'data'/name).read_bytes(),mtime=0))
for name in ['cards.csv','assets.csv','summary.json']:
    shutil.copyfile(a.work/'audit-final'/name,a.out/('audit-'+name))
shutil.copyfile(a.work/'confirmation-unblinding.json',a.out/'confirmation-unblinding.json')
for name in ['cards.json','summary.json']:
    (a.out/('published-'+name+'.gz')).write_bytes(gzip.compress((a.work/'published-current/a'/name).read_bytes(),mtime=0))
for mode in ['offline','canned','chaos','replay']:
    root=a.work/('final-compat-'+mode)/'a'
    if (root/'summary.json').exists():
        for name in ['cards.json','summary.json']:
            (a.out/('compat-'+mode+'-'+name+'.gz')).write_bytes(gzip.compress((root/name).read_bytes(),mtime=0))
dump(a.out/'SHA256SUMS.json',{f.name:sha(f) for f in sorted(a.out.iterdir()) if f.name!='SHA256SUMS.json'})
print(f'Exported {len(list(a.out.iterdir()))} evidence files')
