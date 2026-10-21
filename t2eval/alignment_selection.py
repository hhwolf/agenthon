"""Apply the precommitted gates, freeze once, then allow one confirmation run."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from t2agent.io import read_card, read_panels
from t2eval.data import units
from t2eval.final_alignment import SEEDS, dump, group_for, paired_ci, run, sha


def select(directory, output):
    if output.exists():
        raise FileExistsError('Selection is frozen; never overwrite after confirmation')
    df=pd.read_csv(directory/'cards.csv',keep_default_na=False)
    data=df.loc[df.split=='development'].copy()
    if data.duplicated(['id','arm','seed']).any() or set(data.seed)!=set(SEEDS):
        raise ValueError('Incomplete or duplicated declared seeds')
    counts=data.groupby(['id','arm']).size().unstack('arm')
    if set(counts.columns)!={'release','A','B','C'} or not (counts==len(SEEDS)).all().all():
        raise ValueError('Incomplete or duplicated development comparison')
    means=data.groupby('arm').score.mean();baseline=float(means['release']);comparisons={}
    for arm in ['A','B','C']:
        ci=paired_ci(data,arm)
        group_gates={}
        for group,g in data.groupby('group'):
            group_means=g.groupby('arm').score.mean()
            cards=g.id.nunique();weeks=g.week.nunique()
            group_gates[group]=dict(cards=cards,weeks=weeks,adequate=cards>=40 and weeks>=12,
                relative_change=float(group_means[arm]/group_means['release']-1),
                mean=float(group_means[arm]),baseline_mean=float(group_means['release']))
        seeds={}
        for seed,g in data.groupby('seed'):
            a=g.loc[g.arm==arm];b=g.loc[g.arm=='release']
            seeds[str(seed)]=dict(mean=float(a.score.mean()),baseline=float(b.score.mean()),
                caps=int((a.score>=8).sum()),baseline_caps=int((b.score>=8).sum()),
                failures=int(a.failed.sum()),baseline_failures=int(b.failed.sum()),
                fallbacks=int((a.fallback!='').sum()),baseline_fallbacks=int((b.fallback!='').sum()))
        gates=dict(improvement_1pct=float(means[arm])<=.99*baseline,ci_upper_negative=ci['ci95'][1]<0,
            no_major_group_5pct_harm=all(not g['adequate'] or g['mean']<=1.05*g['baseline_mean'] for g in group_gates.values()),
            no_new_failures=not any((data.loc[data.arm==arm].set_index(['id','seed']).failed & ~data.loc[data.arm=='release'].set_index(['id','seed']).failed)),
            no_new_fallbacks=not any(((data.loc[data.arm==arm].set_index(['id','seed']).fallback!='') & (data.loc[data.arm=='release'].set_index(['id','seed']).fallback==''))),
            caps_nonincreasing_each_seed=all(s['caps']<=s['baseline_caps'] for s in seeds.values()),
            improvement_each_seed=all(s['mean']<s['baseline'] for s in seeds.values()),
            leave_best_week_out_improves=ci['delta_without_best_week']<0)
        comparisons[arm]=dict(mean=float(means[arm]),relative_change=float(means[arm]/baseline-1),
                              uncertainty=ci,groups=group_gates,seeds=seeds,gates=gates,passed=all(gates.values()))
    best=min(comparisons,key=lambda a:comparisons[a]['mean'])
    if comparisons[best]['mean']>=baseline:
        winner='release'
    else:
        tied=[a for a in ['A','C','B'] if comparisons[a]['mean']<=comparisons[best]['mean']+.0005]
        winner=tied[0]  # A/C remove a knob; B introduces a fixed blend/half-life.
    record=dict(frozen_at=datetime.now(timezone.utc).isoformat(),winner=winner,
        development_pass=winner!='release' and comparisons[winner]['passed'],release_mean=baseline,
        comparisons=comparisons,development_identity_sha256=sha(directory/'identity.json'),
        development_scores_sha256=sha(directory/'cards.csv'),seeds=SEEDS,confirmation_unopened=True,
        plan_sha256=sha(Path('reports/final_alignment/PLAN.md')))
    dump(output,record)
    print(json.dumps(record,indent=2))


def confirm(root, frozen, out, development=None):
    selection=json.loads(frozen.read_text())
    if out.exists() or out.with_name(out.name+'-unblinding.json').exists():
        raise FileExistsError('Confirmation already started; no re-selection or overwrite')
    if (selection.get('winner') not in {'release','A','B','C'}
            or selection.get('confirmation_unopened') is not True
            or selection.get('seeds') != SEEDS):
        raise ValueError('Invalid frozen selection policy')
    if selection.get('plan_sha256') != sha(Path('reports/final_alignment/PLAN.md')):
        raise ValueError('Frozen plan hash mismatch')
    if development is None:
        raise ValueError('Confirmation requires the frozen development directory')
    if (selection.get('development_identity_sha256') != sha(development/'identity.json')
            or selection.get('development_scores_sha256') != sha(development/'cards.csv')):
        raise ValueError('Frozen development evidence hash mismatch')
    # Only this function reads newly published answer files; freeze is mandatory.
    cases=[]
    for unit in units(root):
        if not unit.name.endswith('-ps1'): continue
        c=read_card(unit/'card.toml');cutoff=pd.Timestamp(c['provenance']['data_cutoff']);iso=cutoff.isocalendar()
        answer=root.parent/'practice-answers'/(unit.name+'.parquet')
        if not answer.exists(): raise FileNotFoundError(answer)
        cases.append(dict(id=unit.name,unit=str(unit.resolve()),realized=str(answer.resolve()),
            asof=str(cutoff.date()),year=cutoff.year,week=f'{iso.year}-W{iso.week:02d}',
            group=group_for(c,read_panels(unit/'panels')),cohort='official_ps1',split='confirmation',
            shape='joint_assets' if len(c['targets']['asset_ids'])>1 else 'single_asset'))
    if len(cases)!=22: raise ValueError(f'Unexpected confirmation roster: {len(cases)}')
    # Log first answer access before identity() hashes the references or any parquet is read.
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.with_name(out.name+'-unblinding.json').open('x') as stream:
        json.dump(dict(time=datetime.now(timezone.utc).isoformat(),frozen_selection_sha256=sha(frozen),
                       winner=selection['winner'],cards=len(cases)),stream,indent=2)
    arms=list(dict.fromkeys(['M0','release',selection['winner']]))
    run(cases,out,root,arms)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['select','confirm'])
    p.add_argument('--development',type=Path);p.add_argument('--frozen',type=Path,required=True)
    p.add_argument('--units-root',type=Path,default=Path('vendor/current/units'));p.add_argument('--out',type=Path)
    a=p.parse_args()
    if a.command=='select':select(a.development,a.frozen)
    else:confirm(a.units_root,a.frozen,a.out,a.development)


if __name__=='__main__':main()
