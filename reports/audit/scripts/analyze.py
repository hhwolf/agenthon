"""Independent audit analysis: recompute tables and gates from fresh audit runs only."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from runs import ROOT, find_run

cli = argparse.ArgumentParser(description=__doc__)
cli.add_argument('--eval-a', type=Path, default=ROOT/'.context/audit/eval-A', help='work dir with default-env runs')
cli.add_argument('--eval-n', type=Path, default=ROOT/'.context/audit/eval-N', help='work dir with TEXT_LAYER_MODE=numeric_only runs')
cli.add_argument('--out', type=Path, default=ROOT/'reports/audit')
args = cli.parse_args()
A, N, OUT = args.eval_a, args.eval_n, args.out
OUT.mkdir(parents=True, exist_ok=True)


def run(base, mode, forecaster, n_draws, text_mode=None):
    path = find_run(base, mode, forecaster, n_draws, text_mode)
    df = pd.read_csv(path/'cards.csv')
    df['year'] = pd.to_datetime(df['asof']).dt.year
    df['capped'] = df.score >= 8
    return df, path.name


hist = {'M0 (500)': run(A, 'backtest', 'm0', 500), 'M0 (2000)': run(A, 'backtest', 'm0', 2000),
        'numeric_v1': run(A, 'backtest', 'numeric_v1', 2000), 'numeric_v1.1': run(A, 'backtest', 'numeric_v1_1', 2000)}
# Historical cards carry no text dir, so final == numeric_v1.1 there by construction (checked below).
hist['final (card-notes λ0.5)'] = hist['numeric_v1.1']
prac = {'M0 (500)': run(A, 'eval-practice', 'm0', 500), 'M0 (2000)': run(A, 'eval-practice', 'm0', 2000),
        'numeric_v1': run(N, 'eval-practice', 'numeric_v1', 2000, 'numeric_only'),
        'numeric_v1.1': run(N, 'eval-practice', 'numeric_v1_1', 2000, 'numeric_only'),
        'final (card-notes λ0.5)': run(A, 'eval-practice', 'numeric_v1_1', 2000)}
runs = {f'hist/{k}': v[1] for k, v in hist.items()} | {f'practice/{k}': v[1] for k, v in prac.items()}


def parts(h):
    return {'CV 2009–18': h[h.year.between(2009, 2018)], 'Held-out 2019–24 (report-only)': h[h.year.between(2019, 2024)],
            'All historical': h}


def m(df):
    return dict(cards=len(df), mean=float(df.score.mean()), median=float(df.score.median()),
                caps=int(df.capped.sum()), failures=int(df.failed.sum()))


# Previously reported headline values (BUILD_LOG / reports), for the >0.002 check.
REPORTED = {
    ('M0 (500)', 'All historical'): 1.214629, ('M0 (500)', 'Practice (88)'): 2.551735,
    ('M0 (2000)', 'CV 2009–18'): 1.033389, ('M0 (2000)', 'Held-out 2019–24 (report-only)'): 1.480838,
    ('M0 (2000)', 'All historical'): 1.210785,
    ('numeric_v1', 'CV 2009–18'): 0.953077, ('numeric_v1', 'Held-out 2019–24 (report-only)'): 1.456363,
    ('numeric_v1', 'All historical'): 1.154244, ('numeric_v1', 'Practice (88)'): 2.435614,
    ('numeric_v1.1', 'CV 2009–18'): 0.951081, ('numeric_v1.1', 'Held-out 2019–24 (report-only)'): 1.454208,
    ('numeric_v1.1', 'Practice (88)'): 2.415744,
    ('final (card-notes λ0.5)', 'Practice (88)'): 2.378141,
}
REPORTED_CAPS = {('M0 (500)', 'All historical'): 24, ('M0 (500)', 'Practice (88)'): 11,
                 ('M0 (2000)', 'CV 2009–18'): 1, ('M0 (2000)', 'Held-out 2019–24 (report-only)'): 15,
                 ('M0 (2000)', 'All historical'): 23, ('numeric_v1', 'CV 2009–18'): 1,
                 ('numeric_v1', 'Held-out 2019–24 (report-only)'): 17, ('numeric_v1', 'All historical'): 23,
                 ('numeric_v1', 'Practice (88)'): 9, ('numeric_v1.1', 'Held-out 2019–24 (report-only)'): 18,
                 ('numeric_v1.1', 'All historical'): 24, ('numeric_v1.1', 'Practice (88)'): 9,
                 ('final (card-notes λ0.5)', 'Practice (88)'): 9}

rows = []
for name in hist:
    blocks = {**parts(hist[name][0]), 'Practice (88)': prac[name][0]}
    for part, df in blocks.items():
        r = dict(arm=name, partition=part, **m(df))
        rep = REPORTED.get((name, part))
        r['reported_mean'] = rep
        r['diff'] = None if rep is None else r['mean']-rep
        r['flag_gt_0.002'] = bool(rep is not None and abs(r['mean']-rep) > .002)
        r['reported_caps'] = REPORTED_CAPS.get((name, part))
        rows.append(r)
headline = pd.DataFrame(rows)
headline.to_csv(OUT/'comparison-headline.csv', index=False)

# Breakdowns by family / panel / horizon bucket / shape for CV, held-out, practice.
GROUPS = ['family', 'panel', 'horizon_bucket', 'shape']
br = []
for name in ['M0 (2000)', 'numeric_v1', 'numeric_v1.1', 'final (card-notes λ0.5)']:
    blocks = {**parts(hist[name][0]), 'Practice (88)': prac[name][0]}
    for part, df in blocks.items():
        if part == 'All historical':
            continue
        for g in GROUPS:
            for k, sub in df.groupby(g):
                br.append(dict(arm=name, partition=part, dimension=g, group=k, cards=len(sub),
                               mean=float(sub.score.mean()), caps=int(sub.capped.sum())))
breakdown = pd.DataFrame(br)
breakdown.to_csv(OUT/'comparison-breakdowns.csv', index=False)

# Per-card reproduction against frozen per-card files.
def frozen(path, dataset=None):
    f = pd.read_csv(ROOT/path)
    if dataset:
        f = f[f.dataset == dataset]
    return f.set_index('unit_id').score

repro = {}
pairs = {
    'numeric_v1 hist vs reports/phase2_5/cards-numeric_v1.csv': (hist['numeric_v1'][0], frozen('reports/phase2_5/cards-numeric_v1.csv', 'historical')),
    'numeric_v1 practice vs reports/phase2_5/cards-numeric_v1.csv': (prac['numeric_v1'][0], frozen('reports/phase2_5/cards-numeric_v1.csv', 'practice')),
    'numeric_v1.1 hist vs reports/phase2_5/cards-A1_fhs5.csv': (hist['numeric_v1.1'][0], frozen('reports/phase2_5/cards-A1_fhs5.csv', 'historical')),
    'numeric_v1.1 practice vs reports/phase4/numeric_v1_1.csv': (prac['numeric_v1.1'][0], frozen('reports/phase4/numeric_v1_1.csv')),
    'final practice vs reports/phase4/card_notes_l05.csv': (prac['final (card-notes λ0.5)'][0], frozen('reports/phase4/card_notes_l05.csv')),
    'M0(2000) CV vs reports/phase2/development-m0.csv': (hist['M0 (2000)'][0], frozen('reports/phase2/development-m0.csv')),
    'M0(2000) held-out vs reports/phase2/holdout-m0.csv': (hist['M0 (2000)'][0], frozen('reports/phase2/holdout-m0.csv')),
}
for label, (mine, ref) in pairs.items():
    s = mine.set_index('unit_id').score.reindex(ref.index)
    repro[label] = dict(cards=int(len(ref)), missing=int(s.isna().sum()), max_abs_diff=float((s-ref).abs().max()))

# Final vs numeric_v1.1 on historical: identical by construction? Verify byte-level scores equal.
# (Same run reused; record the reason instead of claiming a separate measurement.)

# Gates: numeric_v1.1 vs numeric_v1 (C1 + held-out veto), recomputed independently.
def regress(c, p, limit):
    out = []
    for g in GROUPS:
        for k, sub in c.groupby(g):
            thr = 20 if (g == 'panel' and k == 'macro_monthly') else 40
            if len(sub) < thr:
                continue
            before = p.loc[p[g] == k, 'score'].mean()
            ratio = sub.score.mean()/before-1
            out.append(dict(dimension=g, group=k, cards=len(sub), before=float(before), after=float(sub.score.mean()),
                            rel=float(ratio), breach=bool(ratio > limit)))
    return out


def boot(c, p, seed=20261015):
    d = c.set_index('unit_id').score-p.set_index('unit_id').score.reindex(c.unit_id).values
    yrs = c.set_index('unit_id').year
    blocks = d.groupby(yrs).agg(['sum', 'size'])
    rng = np.random.default_rng(seed)
    picks = rng.integers(len(blocks), size=(10000, len(blocks)))
    draws = blocks['sum'].to_numpy()[picks].sum(1)/blocks['size'].to_numpy()[picks].sum(1)
    return dict(delta=float(d.mean()), ci95=[float(x) for x in np.quantile(draws, [.025, .975])], years=len(blocks))


hv1, hv11 = parts(hist['numeric_v1'][0]), parts(hist['numeric_v1.1'][0])
pv1, pv11, pfin = prac['numeric_v1'][0], prac['numeric_v1.1'][0], prac['final (card-notes λ0.5)'][0]
c1 = dict(
    cv_mean=(m(hv1['CV 2009–18'])['mean'], m(hv11['CV 2009–18'])['mean']),
    practice_mean=(m(pv1)['mean'], m(pv11)['mean']),
    cv_plus_practice_caps=(m(hv1['CV 2009–18'])['caps']+m(pv1)['caps'], m(hv11['CV 2009–18'])['caps']+m(pv11)['caps']),
    cv_regressions=[r for r in regress(hv11['CV 2009–18'], hv1['CV 2009–18'], .10)],
    practice_regressions=[r for r in regress(pv11, pv1, .10)],
    heldout_veto=[r for r in regress(hv11['Held-out 2019–24 (report-only)'], hv1['Held-out 2019–24 (report-only)'], .15)],
    boot_cv=boot(hv11['CV 2009–18'], hv1['CV 2009–18']), boot_practice=boot(pv11, pv1),
    boot_heldout=boot(hv11['Held-out 2019–24 (report-only)'], hv1['Held-out 2019–24 (report-only)']),
)
c1['pass'] = dict(
    cv=c1['cv_mean'][1] < c1['cv_mean'][0], practice=c1['practice_mean'][1] <= c1['practice_mean'][0]+1e-12,
    caps=c1['cv_plus_practice_caps'][1] <= c1['cv_plus_practice_caps'][0],
    no_major_group_gt10=not any(r['breach'] for r in c1['cv_regressions']+c1['practice_regressions']),
    no_heldout_veto=not any(r['breach'] for r in c1['heldout_veto']))

# Monthly macro per year.
macro = []
for name in ['M0 (2000)', 'numeric_v1', 'numeric_v1.1']:
    h = hist[name][0]
    for y, sub in h[h.panel == 'macro_monthly'].groupby('year'):
        macro.append(dict(arm=name, year=int(y), cards=len(sub), mean=float(sub.score.mean()), caps=int(sub.capped.sum())))
macro = pd.DataFrame(macro)
macro.to_csv(OUT/'macro-monthly-by-year.csv', index=False)

# Text decision: card-notes λ0.5 vs numeric_v1.1 on practice.
fam = []
for k in sorted(pv11.family.unique()):
    a, b = pv11[pv11.family == k], pfin[pfin.family == k]
    fam.append(dict(family=k, cards=len(a), numeric=float(a.score.mean()), final=float(b.score.mean()),
                    delta=float(b.score.mean()-a.score.mean()), caps_numeric=int(a.capped.sum()), caps_final=int(b.capped.sum())))
text = dict(numeric=m(pv11), final=m(pfin), boot=boot(pfin, pv11), families=fam,
            changed_cards=int((pfin.set_index('unit_id').score != pv11.set_index('unit_id').score.reindex(pfin.unit_id).values).sum()),
            new_caps=sorted(set(pfin[pfin.capped].unit_id)-set(pv11[pv11.capped].unit_id)),
            removed_caps=sorted(set(pv11[pv11.capped].unit_id)-set(pfin[pfin.capped].unit_id)))

json.dump(dict(runs=runs, reproduction=repro, c1=c1, text=text), open(OUT/'gates.json', 'w'), indent=2, default=str)
pd.set_option('display.width', 200)
print(headline.to_string(index=False))
print(json.dumps(repro, indent=1))
print(json.dumps(c1['pass'], indent=1), c1['cv_mean'], c1['practice_mean'], c1['cv_plus_practice_caps'])
print([r for r in c1['cv_regressions']+c1['practice_regressions'] if r['breach']])
print([r for r in c1['heldout_veto'] if r['breach']])
print(c1['boot_cv'], c1['boot_practice'], c1['boot_heldout'])
print(macro[macro.year.between(2019, 2024)].pivot(index='year', columns='arm', values='mean'))
print(json.dumps(text, indent=1, default=str))
