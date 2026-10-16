"""Precommitted Phase 2.5 ablations; only calls the pinned official score math."""
from dataclasses import asdict, replace
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import warnings

import numpy as np
import pandas as pd
from qfbench2_track_forecasting.scoring import _composite
from t2agent import numeric_v1 as old, numeric_v1_1 as nv
from t2agent.io import read_card, read_panels
from t2eval.ablations import GROUPS, groups, metrics
from t2eval.scales import expected_errors

OUT = Path('reports/phase2_5')
PROTOCOL = OUT/'VALIDATION_2_5.md'
RUNS = {'historical':Path('.eval/runs/backtest-m0-a9a5d3fc5371'),
        'practice':Path('.eval/runs/eval-practice-numeric_v1-743299aa1923')}


def partitions(frame):
    hist = frame.loc[frame.dataset == 'historical']
    return {'cv':hist.loc[hist.year.between(2009, 2018)],
            'practice':frame.loc[frame.dataset == 'practice'],
            'heldout':hist.loc[hist.year.between(2019, 2024)], 'historical':hist}


def validate_pair(candidate, previous):
    """Never hide failed/missing cards through an inner join or changed groups."""
    for frame in (candidate, previous):
        if not frame.unit_id.is_unique or frame.unit_id.isna().any():
            raise ValueError('Comparison requires unique, nonmissing unit IDs')
        if not np.isfinite(frame.score).all():
            raise ValueError('Comparison requires finite scores for every card')
    if set(candidate.unit_id) != set(previous.unit_id):
        raise ValueError('Paired comparison requires the identical card roster')
    columns = [c for c in ('dataset', 'year', *GROUPS) if c in candidate or c in previous]
    try:
        pd.testing.assert_frame_equal(candidate.set_index('unit_id')[columns].sort_index(),
                                      previous.set_index('unit_id')[columns].sort_index(), check_dtype=False)
    except (AssertionError, KeyError) as exc:
        raise ValueError('Paired comparison requires identical card metadata') from exc


def cache_signature(source, inputs, seed):
    return hashlib.sha256(json.dumps({'source':source, 'inputs':inputs, 'QFBENCH_SEED':seed},
                                    sort_keys=True).encode()).hexdigest()


def bootstrap(candidate, previous):
    validate_pair(candidate, previous)
    paired = candidate.merge(previous[['unit_id', 'score']], on='unit_id', suffixes=('', '_old'), validate='one_to_one')
    paired['delta'] = paired.score-paired.score_old
    years = paired.groupby('year').delta.agg(['sum', 'size'])
    rng = np.random.default_rng(20261015)
    draws = rng.integers(len(years), size=(10000, len(years)))
    deltas = years['sum'].to_numpy()[draws].sum(axis=1)/years['size'].to_numpy()[draws].sum(axis=1)
    return {'delta':float(paired.delta.mean()), 'ci95':np.quantile(deltas, [.025, .975]).tolist(),
            'years':len(years), 'year_wins':int((years['sum'] < 0).sum()), 'resamples':10000}


def regressions(candidate, previous, limit):
    result = []
    for key in GROUPS:
        for name, g in candidate.groupby(key):
            threshold = 20 if key == 'panel' and name == 'macro_monthly' else 40
            if len(g) < threshold:
                continue
            before = previous.loc[previous[key] == name, 'score'].mean()
            ratio = float(g.score.mean()/before-1)
            if ratio > limit+1e-12:
                result.append({'dimension':key, 'group':str(name), 'cards':len(g), 'relative_change':ratio})
    return result


def gates(candidate, previous, baseline):
    validate_pair(candidate, previous)
    validate_pair(candidate, baseline)
    c, p, b = partitions(candidate), partitions(previous), partitions(baseline)
    cm, pm = metrics(c['cv']), metrics(p['cv'])
    caps = cm['capped']+metrics(c['practice'])['capped']
    old_caps = pm['capped']+metrics(p['practice'])['capped']
    reasons = []
    if not (cm['mean'] < pm['mean'] or (cm['mean'] <= pm['mean']+.005+1e-12 and caps < old_caps)):
        reasons.append('CV mean/cap tradeoff failed')
    if c['practice'].score.mean() > p['practice'].score.mean()+1e-12:
        reasons.append('practice mean worsened')
    if caps > old_caps:
        reasons.append('CV+practice caps rose')
    for part in ('cv', 'practice'):
        reasons.extend(f'{part} {r["dimension"]}={r["group"]} >10%' for r in regressions(c[part], p[part], .10))
    veto = {label:regressions(c['heldout'], ref['heldout'], .15) for label, ref in [('previous', p), ('numeric_v1', b)]}
    return not reasons, reasons, veto


def complexity(config):
    if config.components:
        return 1+sum(complexity(c) for c in config.components)
    return sum(value != asdict(nv.Config())[key] for key, value in asdict(config).items())


def structure(config):
    return (config.tails, bool(config.term_tau), bool(config.vol_floor),
            'm0' if not config.monthly else 'damped' if config.monthly_damping != 1 else 'long' if config.monthly_window != 12 else 'trend')


def choose(options):
    minimum = min(x['metrics']['cv']['mean'] for x in options)
    tied = [x for x in options if x['metrics']['cv']['mean'] <= minimum+.0005]
    return min(tied, key=lambda x:(complexity(nv.config_from_dict(x['config'])),
               x['metrics']['cv']['capped']+x['metrics']['practice']['capped'], x['name']))


class Evaluation:
    def __init__(self):
        frames = []; self.prepared = {}
        fingerprint = hashlib.sha256(PROTOCOL.read_bytes())
        for name in ('t2agent/numeric_v1.py', 't2agent/numeric_v1_1.py', 't2agent/m0.py',
                     't2agent/io.py', 't2eval/scales.py', 't2eval/ablations.py',
                     'constraints-eval.txt', 'requirements-runtime.txt', _composite.__code__.co_filename, __file__):
            fingerprint.update(Path(name).read_bytes())
        fingerprint.update(json.dumps({p:version(p) for p in ('qfbench2-common', 'qfbench2-track-forecasting',
                                                               'numpy', 'pandas', 'scipy', 'pyarrow')}, sort_keys=True).encode())
        source_signature = fingerprint.hexdigest()
        inputs = hashlib.sha256()
        for dataset, run in RUNS.items():
            inputs.update((run/'cards.csv').read_bytes())
            inputs.update((run/'roster.json').read_bytes())
            rows = pd.read_csv(run/'cards.csv')
            roster = {Path(r['unit']).name:r for r in json.loads((run/'roster.json').read_text())}
            rows = rows[['unit_id', 'asof', 'family', 'panel', 'horizon_bucket', 'shape', 'horizons']].copy()
            rows['year'] = pd.to_datetime(rows['asof']).dt.year; rows['dataset'] = dataset
            for n, row in enumerate(rows.itertuples()):
                case = roster[row.unit_id]; unit = Path(case['unit'])
                input_paths = [unit/'card.toml', *sorted((unit/'panels').glob('*.parquet')), Path(case['realized'])]
                if (unit/'forecast_spec.json').exists(): input_paths.append(unit/'forecast_spec.json')
                for path in input_paths:
                    inputs.update(str(path).encode()); inputs.update(path.read_bytes())
                card = read_card(unit/'card.toml')
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', RuntimeWarning)
                    prep = old.prepare(card, read_panels(unit/'panels'), row.asof)
                grid = [(a, h) for a in card['targets']['asset_ids'] for h in card['targets']['horizons']]
                y = pd.read_parquet(case['realized']).set_index(['asset', 'horizon']).loc[grid, 'value'].to_numpy()
                self.prepared[row.unit_id] = (prep, y, expected_errors(prep.baseline))
                if (n+1)%400 == 0: print(f'Prepared {dataset}: {n+1}/{len(rows)}', flush=True)
            frames.append(rows)
        self.rows = pd.concat(frames, ignore_index=True)
        self.input_signature = inputs.hexdigest()
        self.signature = cache_signature(source_signature, self.input_signature, os.environ.get('QFBENCH_SEED'))
        assert self.rows.unit_id.is_unique
        assert {k:len(v) for k, v in partitions(self.rows).items()} == {'cv':1073, 'practice':88, 'heldout':554, 'historical':2060}

    def evaluate(self, config):
        key = hashlib.sha256(json.dumps(asdict(config), sort_keys=True).encode()).hexdigest()[:16]
        cache = Path('.eval/phase2_5')/f'{self.signature[:16]}-{key}.csv'
        if cache.exists(): return pd.read_csv(cache)
        rows = self.rows.copy(); scores = []; errors = []
        for uid in rows.unit_id:
            p, y, scales = self.prepared[uid]
            try:
                draws = nv.sample(p, config, 2000)
                raw = _composite(draws, y, weights=(5/7, 0, 2/7) if len(y) == 1 else (.5, .3, .2),
                    tail_levels=(.01, .05, .95, .99), joint='variogram', tail_metric='pinball', ref_scale=scales)
                value = float(np.clip(raw['composite'], 0, 8))
                if not np.isfinite(value): raise ValueError('Nonfinite score')
                scores.append(value); errors.append('')
            except Exception as exc:
                scores.append(8.); errors.append(f'{type(exc).__name__}: {exc}')
        rows['score'] = scores; rows['error'] = errors
        cache.parent.mkdir(parents=True, exist_ok=True); rows.to_csv(cache, index=False)
        return rows


def main():
    if (OUT/'frozen-selection.json').exists():
        raise SystemExit('Already frozen; refusing to overwrite')
    evaluation = Evaluation(); configs = {}; frames = {}; records = []
    baseline = evaluation.evaluate(nv.Config())
    # Reproduction check before selecting; original output used the same draws/seeds.
    # Stored Phase 2 scores use implicit per-unit seeds, not an explicit override.
    if os.environ.get('QFBENCH_SEED') is None:
        for part, path in [('cv', 'reports/phase2/development-final-runtime.csv'),
                           ('heldout', 'reports/phase2/holdout-numeric_v1.csv'),
                           ('practice', str(RUNS['practice']/'cards.csv'))]:
            expected = pd.read_csv(path).set_index('unit_id').score
            actual = partitions(baseline)[part].set_index('unit_id').score
            assert np.allclose(actual, expected.reindex(actual.index), atol=1e-12, rtol=0), part
    best_name = 'numeric_v1'; best = nv.Config(); previous = baseline

    def record(name, config, frame, prev_name, prev):
        parts = partitions(frame); prevs = partitions(prev); bases = partitions(baseline)
        eligible, reasons, veto = gates(frame, prev, baseline)
        rec = {'name':name, 'previous':prev_name, 'config':asdict(config), 'eligible_c1':eligible,
               'reasons':reasons, 'veto':veto, 'accepted':False,
               'metrics':{k:metrics(v) for k, v in parts.items()},
               'breakdowns':{k:groups(v) for k, v in parts.items()},
               'paired_previous':{k:bootstrap(v, prevs[k]) for k, v in parts.items()},
               'paired_numeric_v1':{k:bootstrap(v, bases[k]) for k, v in parts.items()},
               'inference_errors':int(frame.error.fillna('').ne('').sum())}
        if rec['inference_errors']: rec['eligible_c1'] = False; rec['reasons'].append('inference errors')
        records.append(rec); configs[name] = config; frames[name] = frame
        frame.to_csv(OUT/f'cards-{name}.csv', index=False)
        print(json.dumps({k:v for k, v in rec.items() if k not in ('breakdowns', 'paired_previous', 'paired_numeric_v1')}), flush=True)
        return rec

    record(best_name, best, baseline, best_name, baseline)['accepted'] = True
    stages = [('A1', [('t5', {'tails':'student_unit'}), ('mixture', {'tails':'mixture_unit'}), ('fhs5', {'tails':'fhs5'})]),
              ('A2', [(str(t), {'term_tau':t}) for t in (63, 126, 252)]),
              ('A3', [(str(f), {'vol_floor':f}) for f in (.25, .5)]),
              ('A4', [('damp025', {'monthly_damping':.25}), ('damp05', {'monthly_damping':.5}),
                      ('window36', {'monthly_window':36}), ('m0', {'monthly':False})]),
              ('A5', None), ('A6', [('sign01', {'momentum':.1}), ('sign025', {'momentum':.25})])]
    pool_members = []
    for stage, menu in stages:
        if stage == 'A5':
            candidates = [r for r in records if not r['inference_errors']]
            first = choose(candidates)
            different = [r for r in candidates if structure(configs[r['name']]) != structure(configs[first['name']])]
            second = choose(different)
            pool_members = [first['name'], second['name']]
            alternatives = [('A5_pool', nv.Config(components=tuple(configs[n] for n in pool_members)))]
        else:
            alternatives = []
            for suffix, changes in menu:
                config = replace(best, components=tuple(replace(c, **changes) for c in best.components)) if best.components else replace(best, **changes)
                alternatives.append((stage+'_'+suffix, config))
        eligible = []
        for name, config in alternatives:
            frame = evaluation.evaluate(config)
            rec = record(name, config, frame, best_name, previous)
            if stage == 'A5': rec['pool_members'] = pool_members
            if rec['eligible_c1'] and not any(rec['veto'].values()): eligible.append(rec)
        if eligible:
            selected = choose(eligible); selected['accepted'] = True
            best_name = selected['name']; best = configs[best_name]; previous = frames[best_name]
        (OUT/'ablations.json').write_text(json.dumps(records, indent=2)+'\n')
    frozen = {'winner':best_name, 'config':asdict(best), 'n_draws':2000,
              'source_signature':evaluation.signature, 'protocol_sha256':hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
              'protocol_commit':'da26396', 'metrics':records[[r['name'] for r in records].index(best_name)]['metrics']}
    (OUT/'frozen-selection.json').write_text(json.dumps(frozen, indent=2)+'\n')
    (OUT/'numeric_v1_1_config.json').write_text(json.dumps(asdict(best), indent=2)+'\n')
    Path('t2agent/numeric_v1_1_config.json').write_bytes((OUT/'numeric_v1_1_config.json').read_bytes())
    previous.to_csv(OUT/'cards-selected.csv', index=False)
    print('FROZEN '+json.dumps(frozen), flush=True)


if __name__ == '__main__': main()
