"""Bounded Final-alignment research. No data or answers enter the runtime image.

Run `python -m t2eval.final_alignment --help`. The committed PLAN is authoritative.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import subprocess
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from qfbench2_track_forecasting import scoring

from t2agent import m0, numeric_alignment, numeric_v1, numeric_v1_1
from t2agent.io import read_card, read_panels, sample_frame, write_forecast
from t2eval.data import build_union, panel_frames, units, write_unit
from t2eval.official import normalize, score
from t2eval.scales import expected_errors

ROOT = Path(__file__).resolve().parents[1]
SEEDS = [1111, 2222, 3333]
GROUPS = {
    'UST_bills': ('rates_daily.parquet', ['UST_1Y', 'UST_3M', 'UST_6M']),
    'UST_other': ('rates_daily.parquet', ['UST_2Y', 'UST_5Y', 'UST_10Y', 'UST_30Y']),
    'G10_FedH10': ('g10_fx_daily.parquet', ['EUR', 'GBP', 'JPY', 'CHF']),
    'EM_ECB': ('em_fx_ecb_daily.parquet', ['BRL', 'INR', 'KRW', 'MXN', 'ZAR']),
}


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False, default=str)+'\n')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(path):
    return subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()


def identity(cases, seeds, arms, units_root, normalization='current'):
    sources = {str(p.relative_to(ROOT)): sha(p) for folder in ('t2agent', 't2eval')
               for p in sorted((ROOT/folder).rglob('*')) if p.suffix in ('.py', '.json')}
    inputs = {}
    directory_revisions = {}
    for case in cases:
        unit = Path(case['unit'])
        try:
            directory_revisions[case['id']] = git(unit)
        except (subprocess.CalledProcessError, OSError):
            directory_revisions[case['id']] = None
        # Include prose/corpus as well as panels and card; no answer file is in a unit.
        inputs[case['id']] = {str(p.relative_to(unit)): sha(p) for p in sorted(unit.rglob('*')) if p.is_file()}
        if case.get('realized'):
            inputs[case['id']]['reference_answer_sha256'] = sha(Path(case['realized']))
    data = dict(normalization=normalization, sources=sources, inputs=inputs, input_directory_git_revisions=directory_revisions, roster=cases, seeds=seeds, arms=arms,
                draws=2000, seed_policy='explicit seeds; None means card CRC32 independent of environment',
                text_policy='committed card_notes_only lambda0.5; C explicitly disables it', source_commit=git(ROOT), upstream_commit=git(units_root.parent),
                upstream_commit_role="evaluation specification checkout, not necessarily the input source",
                versions={n: importlib.metadata.version(n) for n in
                          ('qfbench2-common', 'qfbench2-track-forecasting', 'numpy', 'pandas', 'scipy')},
                scorer_sha256=sha(Path(scoring.__file__)),
                configs={n: json.loads((ROOT/'t2agent'/n).read_text()) for n in
                         ('numeric_v1_1_config.json', 'text_config.json')})
    data['identity_sha256'] = hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()
    return data


def group_for(card, panels):
    assets = set(card['targets']['asset_ids'])
    if assets <= {'UST_3M', 'UST_6M', 'UST_1Y'}:
        return 'UST_bills'
    if all(a.startswith('UST_') for a in assets):
        return 'UST_mixed' if assets & {'UST_3M', 'UST_6M', 'UST_1Y'} else 'UST_other'
    if 'g10_fx_daily.parquet' in panels:
        return 'G10_FedH10'
    if 'em_fx_ecb_daily.parquet' in panels:
        return 'EM_ECB'
    if 'em_transfer_early.parquet' in panels:
        return 'EM_legacy'
    return 'other'


def build(root, out):
    out.mkdir(parents=True, exist_ok=False)
    donors, provenance = build_union(root, out/'union')
    panels = panel_frames(donors)
    windows = []
    for unit in units(root):
        if unit.name.endswith('-ps1'):
            c = read_card(unit/'card.toml'); cutoff = pd.Timestamp(c['provenance']['data_cutoff'])
            windows.append((cutoff+pd.offsets.BDay(1), cutoff+pd.offsets.BDay(max(c['targets']['horizons']))))
    dump(out/'reserved-windows.json', windows)
    template = read_card(root/'t2-F1-curve-ust1y-001-ps1/card.toml')
    cases, omitted = [], []

    def add(c, name, cutoff, assets, horizons, panel_name, cohort, prose=None, input_panels=None):
        targets = [cutoff+pd.offsets.BDay(h) for h in horizons]
        reason = None
        if any(lo <= max(targets) and hi >= min(targets) for lo, hi in windows):
            reason = 'reserved_confirmation_window'
        elif max(targets).year != cutoff.year:
            reason = 'year_boundary'
        f = panels[panel_name]
        selected = f.loc[f.asset.isin(assets)]
        history = selected.loc[selected.date <= cutoff].copy() if input_panels is None else input_panels.loc[input_panels.date <= cutoff].copy()
        realized = []
        for a in assets:
            hist = history.loc[history.asset == a]
            if len(hist.loc[hist.date < cutoff]) < 300:
                reason = reason or 'fewer_than_300_prior_observations'
            for h, target in zip(horizons, targets):
                hit = selected.loc[(selected.asset == a) & (selected.date == target)]
                if len(hit) != 1:
                    reason = reason or 'missing_exact_target'
                else:
                    realized.append({'asset': a, 'horizon': h, 'value': float(hit.value.iloc[0])})
        if reason:
            omitted.append(dict(id=name, asof=str(cutoff.date()), panel=panel_name, reason=reason, cohort=cohort))
            return
        c = copy.deepcopy(c); c.pop('forecast_spec', None); c.pop('questions', None)
        c['task']['id'] = name
        if cohort == 'regular':
            c['task']['title'] = 'Short-horizon numerical history forecast'
            c['metadata']['description'] = 'Forecast from available numerical history.'
            c['text'] = dict(path='text/', cutoff=str(cutoff.date()), notes='')
        c['provenance']['data_cutoff'] = str(cutoff.date())
        c['targets'] = dict(asset_ids=assets, horizons=horizons, target_type='level')
        c['metadata'].update(asset_panel=Path(panel_name).stem, horizons=horizons, n_assets=len(assets), target_frequency='daily')
        spec = dict(schema_version='2', card_id=name, targets=c['targets'])
        unit = out/'units'/name
        write_unit(unit, c, {panel_name: history}, spec)
        (unit/'text').mkdir()
        (unit/'forecast_card.md').write_text(prose or 'Short-horizon numerical forecast from available history.\n')
        answer = out/'answers'/name/'realized.parquet'; answer.parent.mkdir(parents=True)
        pd.DataFrame(realized).to_parquet(answer, index=False)
        iso = cutoff.isocalendar()
        cases.append(dict(id=name, unit=str(unit.resolve()), realized=str(answer.resolve()),
                          asof=str(cutoff.date()), year=cutoff.year, week=f'{iso.year}-W{iso.week:02d}',
                          group=group_for(c, {panel_name:history}), cohort=cohort,
                          shape='joint_assets' if len(assets)>1 else 'single_asset',
                          split='development' if cutoff.year <= 2018 else 'report_only'))
    for year in range(2011, 2025):
        for month in range(1, 13):
            start = pd.Timestamp(year, month, 1)
            cutoff = start+pd.Timedelta(days=(7-start.weekday()) % 7)
            for group, (panel_name, assets) in GROUPS.items():
                assets = sorted(assets)
                one = [assets[((year-2011)*12+month-1) % len(assets)]]
                for shape, chosen, hs in [('single', one, [1,2,3,4]), ('joint', assets, [1,4])]:
                    name = f'alignment-{group}-{year}-{month:02d}-{shape}'
                    add(template, name, cutoff, chosen, hs, panel_name, 'regular')
    for unit in units(root):
        if unit.name.endswith('-ps1'):
            continue
        c = read_card(unit/'card.toml'); cutoff = pd.Timestamp(c['provenance']['data_cutoff'])
        if not 2011 <= cutoff.year <= 2024 or c['targets']['target_type'] != 'level':
            continue
        pp = read_panels(unit/'panels')
        names = {name for a in c['targets']['asset_ids'] for name, f in pp.items()
                 if a in set(f.get('asset', f.get('asset_id')))}
        if len(names) != 1 or next(iter(names)) not in {v[0] for v in GROUPS.values()}:
            continue
        panel_name = next(iter(names)); f=pp[panel_name].rename(columns={'asset_id':'asset'}).copy()
        f['date']=pd.to_datetime(f.date); f=f.loc[f.asset.isin(c['targets']['asset_ids'])]
        prose=(unit/'forecast_card.md').read_text() if (unit/'forecast_card.md').exists() else ''
        add(c, 'alignment-episode-'+unit.name, cutoff, c['targets']['asset_ids'], [1,2,3,4],
            panel_name, 'episode', prose=prose, input_panels=f)
    if len(cases)>2000 or len(cases)*12>24000:
        raise RuntimeError('Predeclared budget exceeded; deterministic stratification required before scoring')
    cases.sort(key=lambda r:(r['asof'],r['id']))
    dump(out/'roster.json', cases); dump(out/'omissions.json', omitted)
    dump(out/'provenance.json', provenance)
    print(json.dumps(dict(cards=len(cases), groups=pd.Series([c['group'] for c in cases]).value_counts().to_dict(),
                          omitted=len(omitted)), indent=2))


def matrix(frame, card):
    order = pd.MultiIndex.from_product([card['targets']['asset_ids'], card['targets']['horizons']])
    return frame.pivot(index='draw', columns=['asset','horizon'], values='value').reindex(columns=order).to_numpy()


def metric(samples, y, divisors):
    cells = len(y)
    raw = scoring._composite(samples, y, weights=(5/7,0,2/7) if cells==1 else (.5,.3,.2),
                             tail_levels=(.01,.05,.95,.99), joint='variogram', tail_metric='pinball', ref_scale=divisors)
    payload = dict(admissible=True, marginal_crps=raw['marginal'], joint_variogram=raw['joint'], tail_penalty=raw['tail'])
    result = normalize(payload, divisors, cells)
    if not np.isclose(result['unclipped'], raw['composite'], rtol=1e-12, atol=1e-12):
        raise AssertionError('Official normalized composite differs from adapter')
    return result


def evaluate_case(job):
    case, seeds, arms, normalization = job
    unit = Path(case['unit']); c=read_card(unit/'card.toml'); p=read_panels(unit/'panels')
    cutoff=str(c['provenance']['data_cutoff'])
    grid=[(a,h) for a in c['targets']['asset_ids'] for h in c['targets']['horizons']]
    yframe=pd.read_parquet(case['realized']).set_index(['asset','horizon'])
    y=np.array([yframe.loc[k,'value'] for k in grid], dtype=float)
    baseline=m0.distribution(c,p,cutoff,strict_ratio=normalization=='current')
    div=expected_errors(baseline)
    horizon_divisors={}
    for h in c['targets']['horizons']:
        indices=[i for i,(_,gh) in enumerate(grid) if gh==h]
        b=copy.copy(baseline);b.mean=b.mean[indices];b.covariance=b.covariance[np.ix_(indices,indices)]
        horizon_divisors[h]=expected_errors(b)
    rows=[]; cells=[]
    for seed in seeds:
        actual_seed = (zlib.crc32(c['task']['id'].encode()) & 0x7FFFFFFF) if seed is None else seed
        for arm in arms:
            start=time.monotonic()
            if arm=='M0':
                actual=actual_seed
                draws=baseline.mean+np.random.default_rng(actual).standard_normal((2000,len(grid)))@baseline.factor.T
                frame=sample_frame(c,draws); fallback=None
            else:
                frame=numeric_alignment.forecast(c,p,unit/'text',cutoff,2000,actual_seed,arm=arm,
                    text_mode='card_notes_only',text_lambda=.5)
                draws=matrix(frame,c); fallback=frame.attrs.get('fallback')
            elapsed=time.monotonic()-start
            if draws.shape != (2000,len(grid)) or not np.isfinite(draws).all():
                raise AssertionError('Invalid research forecast; abort instead of dropping case')
            values=metric(draws,y,div)
            bounds=np.quantile(draws,[.01,.05,.95,.99],axis=0)
            row={k:v for k,v in case.items() if k not in ('unit','realized')}
            row.update(arm=arm,seed='crc32' if seed is None else seed,seconds=elapsed,fallback=fallback or '',
                       **values,coverage90=float(np.mean((y>=bounds[1])&(y<=bounds[2]))),
                       coverage98=float(np.mean((y>=bounds[0])&(y<=bounds[3]))),cells=len(grid))
            rows.append(row)
            for h in c['targets']['horizons']:
                indices=[i for i,(_,gh) in enumerate(grid) if gh==h]
                # Horizon-specific normalization uses the matching M0 marginal distribution.
                hv=metric(draws[:,indices],y[indices],horizon_divisors[h])
                cells.append({k:row[k] for k in ('id','asof','year','week','group','cohort','shape','split','arm','seed')} |
                    dict(horizon=h,score=hv['score'],normalized_marginal=hv['normalized_marginal'],
                         normalized_joint=hv['normalized_joint'],normalized_tail=hv['normalized_tail'],
                         covered90=int(np.sum((y[indices]>=bounds[1,indices])&(y[indices]<=bounds[2,indices]))),
                         covered98=int(np.sum((y[indices]>=bounds[0,indices])&(y[indices]<=bounds[3,indices]))),cells=len(indices)))
    return rows,cells


def run(cases, out, units_root, arms, seeds=SEEDS, normalization='current', workers=2):
    ident=identity(cases,seeds,arms,units_root,normalization)
    out.mkdir(parents=True,exist_ok=False);dump(out/'identity.json',ident)
    rows=[];cells=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i,(r,h) in enumerate(pool.map(evaluate_case,[(c,seeds,arms,normalization) for c in cases])):
            rows.extend(r);cells.extend(h)
            if (i+1)%25==0 or i+1==len(cases):
                pd.DataFrame(rows).to_csv(out/'cards.csv',index=False)
                pd.DataFrame(cells).to_csv(out/'horizons.csv',index=False)
                print(f'{i+1}/{len(cases)} cards; {len(rows)} arm/seed evaluations',flush=True)
    summarize(out)


def paired_ci(data, arm, repetitions=10000):
    av=data.groupby(['id','week','arm']).score.mean().unstack('arm')
    av['delta']=av[arm]-av['release']
    weeks=av.groupby('week').delta.agg(['sum','count'])
    rng=np.random.default_rng(20261021)
    picks=rng.integers(len(weeks),size=(repetitions,len(weeks)))
    boots=weeks['sum'].to_numpy()[picks].sum(axis=1)/weeks['count'].to_numpy()[picks].sum(axis=1)
    helpful=weeks['sum'].idxmin()
    return dict(delta=float(av.delta.mean()),ci95=np.quantile(boots,[.025,.975]).tolist(),weeks=len(weeks),
                most_helpful_week=helpful,delta_without_best_week=float(av.loc[av.index.get_level_values('week')!=helpful,'delta'].mean()))


def summarize(out):
    df=pd.read_csv(out/'cards.csv',keep_default_na=False)
    metrics=['score','normalized_marginal','normalized_joint','normalized_tail','coverage90','coverage98','seconds']
    records=[]
    for column in ['split','group','year','cohort','shape','seed']:
        for (split,group,arm),f in df.groupby(['split',column,'arm']) if column!='split' else (( (s,s,a),f) for (s,a),f in df.groupby(['split','arm'])):
            records.append(dict(split=split,dimension=column,group=group,arm=arm,cards=f.id.nunique(),
                **{k:float(np.average(f[k],weights=f.cells) if k.startswith('coverage') else f[k].mean()) for k in metrics},caps=int((f.score>=8).sum()),
                failures=int(f.failed.sum()),fallbacks=int((f.fallback!='').sum())))
    pd.DataFrame(records).to_csv(out/'summary.csv',index=False)
    comparisons={}
    for split,data in df.groupby('split'):
        if 'release' not in set(data.arm): continue
        comparisons[split]={a:paired_ci(data,a) for a in sorted(set(data.arm)-{'release'})}
    dump(out/'paired.json',comparisons)


def old_cases(old_root, units_root):
    roster=json.loads((old_root/'.eval/runs/eval-practice-numeric_v1-743299aa1923/roster.json').read_text())
    result=[]
    for r in roster:
        unit=(old_root/r['unit']).resolve();c=read_card(unit/'card.toml');cutoff=pd.Timestamp(c['provenance']['data_cutoff']);iso=cutoff.isocalendar()
        result.append(dict(id=c['task']['id'],unit=str(unit),realized=str((old_root/r['realized']).resolve()),
            asof=str(cutoff.date()),year=cutoff.year,week=f'{iso.year}-W{iso.week:02d}',group=group_for(c,read_panels(unit/'panels')),
            cohort='old_proxy',shape='joint_assets' if len(c['targets']['asset_ids'])>1 else 'single_asset',split='regression'))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['build','develop','old','summarize'])
    p.add_argument('--units-root',type=Path,default=ROOT/'vendor/current/units')
    p.add_argument('--data',type=Path,default=ROOT/'.eval/final_alignment/data')
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--old-root',type=Path)
    p.add_argument('--arms',nargs='+',default=['release','A','B','C'])
    p.add_argument('--crc32',action='store_true')
    p.add_argument('--normalization',choices=['current','release'],default='current')
    p.add_argument('--workers',type=int,default=2)
    a=p.parse_args()
    if a.command=='build':build(a.units_root,a.out)
    elif a.command=='summarize':summarize(a.out)
    else:
        cases=old_cases(a.old_root,a.units_root) if a.command=='old' else json.loads((a.data/'roster.json').read_text())
        run(cases,a.out,a.units_root,a.arms,[None] if a.crc32 else SEEDS,a.normalization,a.workers)


if __name__=='__main__':main()
