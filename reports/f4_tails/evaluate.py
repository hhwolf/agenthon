"""Apply the pre-registered gates in reports/f4_tails/PLAN.md to the candidate runs. Writes results.json/.md."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
cli = argparse.ArgumentParser(description=__doc__)
cli.add_argument('--work', type=Path, default=ROOT/'.context/f4/eval', help='candidate run work dir')
cli.add_argument('--hist-base', type=Path, default=ROOT/'.context/audit/eval-A', help='work dir with numeric_v1_1 backtest')
cli.add_argument('--prac-base', type=Path, default=ROOT/'.context/release/eval', help='work dir with card-notes practice run')
args = cli.parse_args()
OUT = Path(__file__).resolve().parent
PRACTICE_BASE, CAPS_BASE, CV_F4_BASE = 2.378141, 9, 0.961435


def find(work, mode, forecaster, text_mode=None):
    hits = []
    for s in sorted((work/'runs').glob('*/summary.json')):
        meta = json.loads(s.read_text())['metadata']
        if (meta['mode'], meta['forecaster'], meta['n_draws']) != (mode, forecaster, 2000) or meta.get('limit'):
            continue
        env = meta.get('output_env')
        if env is not None and env.get('TEXT_LAYER_MODE') != text_mode:
            continue
        hits.append(s.parent)
    assert len(hits) == 1, (work, mode, forecaster, hits)
    return hits[0]


def cards(run):
    df = pd.read_csv(run/'cards.csv')
    df['year'] = pd.to_datetime(df['asof']).dt.year
    return df.set_index('unit_id')


def boot(delta, years, seed=20261015):
    blocks = pd.Series(np.asarray(delta)).groupby(np.asarray(years)).agg(['sum', 'size'])
    picks = np.random.default_rng(seed).integers(len(blocks), size=(10000, len(blocks)))
    d = blocks['sum'].to_numpy()[picks].sum(1)/blocks['size'].to_numpy()[picks].sum(1)
    return [float(x) for x in np.quantile(d, [.025, .975])]


def groups(cand, base, minimum):
    out = []
    for dim in ('family', 'panel'):
        for name, sub in cand.groupby(dim):
            need = 20 if (dim == 'panel' and name == 'macro_monthly' and minimum == 40) else minimum
            if len(sub) < need:
                continue
            before = base.loc[sub.index, 'score'].mean()
            out.append(dict(dimension=dim, group=name, cards=len(sub), before=float(before),
                            after=float(sub.score.mean()), rel=float(sub.score.mean()/before-1)))
    return out


def triplet(run, unit):
    return tuple(hashlib.sha256((run/'outputs'/unit/f).read_bytes()).hexdigest()
                 for f in ('forecast.parquet', 'forecast_meta.json', 'forecast_rationale.md'))


hb_run, pb_run = find(args.hist_base, 'backtest', 'numeric_v1_1'), find(args.prac_base, 'eval-practice', 'numeric_v1_1')
hb, pb = cards(hb_run), cards(pb_run)
assert abs(pb.score.mean()-PRACTICE_BASE) < 1e-6 and int((pb.score >= 8).sum()) == CAPS_BASE
cv_b = hb[hb.year.between(2009, 2018)]
assert abs(cv_b[cv_b.family == 'T2-F4'].score.mean()-CV_F4_BASE) < 1e-6
results = {}
for kind in ('t5', 't4', 'mix10'):
    name = f't2eval.f4_tails:forecast_{kind}'
    hr, pr = find(args.work, 'backtest', name), find(args.work, 'eval-practice', name)
    h, p = cards(hr).loc[hb.index], cards(pr).loc[pb.index]
    cv, ho = h[h.year.between(2009, 2018)], h[h.year.between(2019, 2024)]
    ho_b = hb[hb.year.between(2019, 2024)]
    f4 = lambda df: df[df.family == 'T2-F4']
    nonf4_hist = (h.family != 'T2-F4')
    nonf4_prac = [u for u in p.index if p.loc[u, 'family'] != 'T2-F4']
    hist_identical = bool((h.loc[nonf4_hist, 'score'] == hb.loc[nonf4_hist, 'score']).all())
    prac_identical = sum(triplet(pr, u) == triplet(pb_run, u) for u in nonf4_prac)
    cv_groups, pr_groups = groups(cv, cv_b, 40), groups(p, pb, 10)
    r = dict(
        cv_f4=dict(cards=len(f4(cv)), mean=float(f4(cv).score.mean()), caps=int((f4(cv).score >= 8).sum()),
                   base=CV_F4_BASE, ci_delta=boot(f4(cv).score.values-f4(cv_b).score.values, f4(cv).year)),
        heldout_f4_report_only=dict(cards=len(f4(ho)), mean=float(f4(ho).score.mean()),
                                    caps=int((f4(ho).score >= 8).sum()), base=float(f4(ho_b).score.mean())),
        practice_f4=dict(cards=len(f4(p)), mean=float(f4(p).score.mean()), caps=int((f4(p).score >= 8).sum()),
                         base=float(f4(pb).score.mean())),
        practice=dict(cards=len(p), mean=float(p.score.mean()), median=float(p.score.median()),
                      caps=int((p.score >= 8).sum()), base=PRACTICE_BASE,
                      ci_delta=boot(p.score.values-pb.score.values, p.year)),
        worst_group_cv=max(cv_groups, key=lambda g: g['rel']), worst_group_practice=max(pr_groups, key=lambda g: g['rel']),
        nonf4_hist_scores_identical=hist_identical, nonf4_practice_triplets_identical=f'{prac_identical}/{len(nonf4_prac)}',
        runs=dict(historical=hr.name, practice=pr.name))
    r['gates'] = {
        '1 practice mean <= 2.358141': r['practice']['mean'] <= PRACTICE_BASE-0.02,
        '2 practice caps <= 9': r['practice']['caps'] <= CAPS_BASE,
        '3 CV F4 mean <= 0.971049': r['cv_f4']['mean'] <= CV_F4_BASE*1.01,
        '4 no family/panel group > +10%': all(g['rel'] <= .10 for g in cv_groups+pr_groups),
        '5 non-F4 byte-identical': hist_identical and prac_identical == len(nonf4_prac)}
    r['passes'] = all(r['gates'].values())
    results[kind] = r
passing = [k for k in results if results[k]['passes']]
best = min(passing, key=lambda k: (round(results[k]['practice']['mean'], 4), results[k]['cv_f4']['mean'])) if passing else None
decision = dict(decision='GO' if best else 'NO-GO', selected=best,
                baselines=dict(historical=hb_run.name, practice=pb_run.name))
(OUT/'results.json').write_text(json.dumps(dict(decision=decision, candidates=results), indent=2)+'\n')
rows = ['| candidate | CV F4 (328) | Δ CV F4 [95% CI] | held-out F4 (report-only) | practice F4 (28) | practice overall (88) | Δ practice [95% CI] | caps | worst group | non-F4 identical | gates 1-5 |',
        '|---|---:|---|---:|---:|---:|---|---:|---|---|---|',
        f"| current final | {CV_F4_BASE:.6f} | — | {results['t5']['heldout_f4_report_only']['base']:.6f} | "
        f"{results['t5']['practice_f4']['base']:.6f} | {PRACTICE_BASE:.6f} | — | {CAPS_BASE} | — | — | — |"]
for k, r in results.items():
    wg = max([r['worst_group_cv'], r['worst_group_practice']], key=lambda g: g['rel'])
    rows.append(f"| {k} | {r['cv_f4']['mean']:.6f} | {r['cv_f4']['mean']-CV_F4_BASE:+.6f} [{r['cv_f4']['ci_delta'][0]:+.4f}, {r['cv_f4']['ci_delta'][1]:+.4f}] | "
                f"{r['heldout_f4_report_only']['mean']:.6f} | {r['practice_f4']['mean']:.6f} | {r['practice']['mean']:.6f} | "
                f"{r['practice']['mean']-PRACTICE_BASE:+.6f} [{r['practice']['ci_delta'][0]:+.4f}, {r['practice']['ci_delta'][1]:+.4f}] | "
                f"{r['practice']['caps']} | {wg['dimension']}={wg['group']} {wg['rel']:+.1%} | "
                f"hist {'yes' if r['nonf4_hist_scores_identical'] else 'NO'}, practice {r['nonf4_practice_triplets_identical']} | "
                + ''.join('✔' if v else '✘' for v in r['gates'].values()) + ' |')
(OUT/'results.md').write_text('# F4 tail experiment — results\n\nPre-registration: [PLAN.md](PLAN.md) (commit `42ce8bb`).\n\n'
                              + '\n'.join(rows) + f"\n\n**Decision: {decision['decision']}**"
                              + (f" — selected `{best}`." if best else ' — no candidate passed all five gates; keep the current final.') + '\n')
print('\n'.join(rows)); print(json.dumps(decision))
for k, r in results.items():
    print(k, r['gates'], 'worst cv', r['worst_group_cv'], 'worst practice', r['worst_group_practice'])
