"""Summarize the audit mock-final matrix from .context/audit/mock/*/a."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path('/Users/henryhe/conductor/workspaces/agenthon/louisville')
M = ROOT/'.context/audit/mock'
OUT = ROOT/'reports/audit'
LIMIT_BYTES, LIMIT_FILES = 64*1024**2, 256


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def sweep(name):
    a = M/name/'a'
    s = json.loads((a/'summary.json').read_text())
    units = sorted(p for p in a.iterdir() if p.is_dir() and (p/'ingestion.json').is_file())
    ing = [json.loads((u/'ingestion.json').read_text()) for u in units]
    walls = np.array([i['wall_seconds'] for i in ing])
    reqs = np.array([i['requests_used'] for i in ing])
    trees, symlinks, blank, cites = [], 0, 0, 0
    for u in units:
        out = u/'output'
        files = [p for p in out.rglob('*')]
        symlinks += sum(p.is_symlink() for p in files)
        trees.append((sum(p.stat().st_size for p in files if p.is_file()), sum(p.is_file() for p in files)))
        r = out/'forecast_rationale.md'
        text = r.read_text() if r.is_file() else ''
        blank += not text.strip()
        cites += ('| doc_id |' in text and 'no validated document evidence' not in text)
    house = {}
    hs = a.parent/'a'/'house-stats.json'
    for cand in [a/'house-stats.json', M/name/'house-stats.json']:
        if cand.is_file():
            house = json.loads(cand.read_text())
    return dict(sweep=name, image=s['image'][-20:], network=s['network'], house_mode=s['house_mode'],
                units=s['units'], passed=s['statuses'].get('passed', 0), statuses=s['statuses'],
                proxy_mean=s.get('proxy_mean'), proxy_caps=s.get('proxy_caps'),
                requests_total=int(reqs.sum()), requests_max=int(reqs.max()), over_20=int((reqs > 20).sum()),
                over_25=int((reqs > 25).sum()),
                wall_mean=float(walls.mean()), wall_max=float(walls.max()), wall_sum=float(walls.sum()),
                projected_100_units=float(walls.mean()*100),
                pull_seconds=s.get('pull_seconds'), image_cached_before=s.get('image_cached_before'),
                max_tree_bytes=max(t[0] for t in trees), max_tree_files=max(t[1] for t in trees),
                tree_violations=sum(t[0] >= LIMIT_BYTES or t[1] > LIMIT_FILES for t in trees),
                symlinks=symlinks, blank_rationales=blank, rationales_citing_doc_ids=cites,
                seed=ing[0].get('seed') if len({i.get('seed') for i in ing}) == 1 else 'per-card'), units, ing


def triplets(units):
    return {u.name: tuple(sha(u/'output'/f) for f in ('forecast.parquet', 'forecast_meta.json', 'forecast_rationale.md'))
            for u in units}


def boot_mean_ci(df, seed=20261015):
    yrs = pd.to_datetime(df['asof']).dt.year
    blocks = df.score.groupby(yrs).agg(['sum', 'size'])
    rng = np.random.default_rng(seed)
    picks = rng.integers(len(blocks), size=(10000, len(blocks)))
    d = blocks['sum'].to_numpy()[picks].sum(1)/blocks['size'].to_numpy()[picks].sum(1)
    return [float(x) for x in np.quantile(d, [.025, .975])]


names = sorted(p.name for p in M.iterdir() if (p/'a'/'summary.json').is_file())
rows, units, ings = [], {}, {}
for n in names:
    r, u, i = sweep(n)
    rows.append(r); units[n] = u; ings[n] = i
table = pd.DataFrame(rows)
table.drop(columns=['statuses']).to_csv(OUT/'mock-final-matrix.csv', index=False)

checks = {}
if {'fin-offline', 'fin-offline-repeat'} <= set(units):
    a, b = triplets(units['fin-offline']), triplets(units['fin-offline-repeat'])
    checks['final_offline_repeat_identical_triplets'] = sum(a[k] == b[k] for k in a)
for x, y in [('fin-offline', 'fin-canned'), ('fin-offline', 'fin-chaos'), ('fin-offline', 'fin-replay'),
             ('pub-offline', 'pub-canned'), ('pub-offline', 'pub-chaos'), ('pub-offline', 'pub-replay')]:
    if {x, y} <= set(units):
        a, b = triplets(units[x]), triplets(units[y])
        checks[f'{x}_vs_{y}_identical_parquet'] = sum(a[k][0] == b[k][0] for k in a)
        checks[f'{x}_vs_{y}_identical_triplets'] = sum(a[k] == b[k] for k in a)
if {'fin-seed-a', 'fin-seed-b'} <= set(units):
    ca = pd.read_csv(M/'fin-seed-a/a/cards.csv'); cb = pd.read_csv(M/'fin-seed-b/a/cards.csv')
    roster = pd.read_csv(sorted((ROOT/'.context/audit/eval-A/runs').glob('eval-practice-m0-54b*'))[0]/'cards.csv')[['unit_id', 'asof']]
    ca = ca.dropna(subset=['score']).merge(roster, on='unit_id'); cb = cb.dropna(subset=['score']).merge(roster, on='unit_id')
    ci_a, ci_b = boot_mean_ci(ca), boot_mean_ci(cb)
    pa, pb = ca.set_index('unit_id').score, cb.set_index('unit_id').score.reindex(ca.unit_id)
    d = (pb.values-pa.values)
    yrs = pd.to_datetime(ca['asof']).dt.year.values
    blocks = pd.Series(d).groupby(yrs).agg(['sum', 'size'])
    rng = np.random.default_rng(20261015)
    picks = rng.integers(len(blocks), size=(10000, len(blocks)))
    dd = blocks['sum'].to_numpy()[picks].sum(1)/blocks['size'].to_numpy()[picks].sum(1)
    changed = sum(triplets(units['fin-seed-a'])[k][0] != triplets(units['fin-seed-b'])[k][0] for k in triplets(units['fin-seed-a']))
    checks['fresh_seed'] = dict(mean_a=float(ca.score.mean()), mean_b=float(cb.score.mean()), ci_a=ci_a, ci_b=ci_b,
                                b_in_ci_a=ci_a[0] <= cb.score.mean() <= ci_a[1], a_in_ci_b=ci_b[0] <= ca.score.mean() <= ci_b[1],
                                paired_delta=float(d.mean()), paired_ci=[float(x) for x in np.quantile(dd, [.025, .975])],
                                caps_a=int((ca.score >= 8).sum()), caps_b=int((cb.score >= 8).sum()), changed_parquets=int(changed))
# Chaos fallback reasons for the labels variant.
if 'lab-chaos' in units:
    reasons = {}
    for u in units['lab-chaos']:
        t = (u/'output'/'forecast_rationale.md').read_text() if (u/'output'/'forecast_rationale.md').is_file() else ''
        line = next((l for l in t.splitlines() if 'neutral' in l.lower() or 'fallback' in l.lower() or 'failed' in l.lower()), '')
        reasons[u.name] = line[:200]
    checks['lab_chaos_rationale_fallback_lines'] = reasons
json.dump(dict(matrix=rows, checks=checks), open(OUT/'mock-final.json', 'w'), indent=2, default=str)
pd.set_option('display.width', 250); pd.set_option('display.max_columns', 40)
print(table.drop(columns=['statuses', 'image']).to_string(index=False))
print(json.dumps(checks, indent=1, default=str))
