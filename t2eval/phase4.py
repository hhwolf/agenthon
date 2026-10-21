"""Frozen Phase 4 replay ablation. Never sends requests or fits mapping values."""
import argparse
from dataclasses import replace
from datetime import date
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from t2agent import m0, numeric_v1, numeric_v1_1
from t2agent.contracts import Evidence, TextSignal
from t2agent.io import read_card, read_panels, sample_frame, write_forecast
from t2agent.text_layer.summary import numeric_summary_from
from t2agent.text_overlay import apply_text_map, evidence_ledger
from .cli import describe
from .official import score, normalize
from .scales import expected_errors

DEFAULT_ROSTER = Path('.eval/runs/eval-practice-numeric_v1-743299aa1923/roster.json')
ARMS = ('numeric_v1_1', 'text_l05', 'text_l10', 'card_notes_l05')


def cached_signal(path, card):
    """Read teammate's sweep artifact, rejecting mock, failed, or mismatched labels."""
    obj = json.loads(path.read_text())
    signal = obj['signal']
    if (obj.get('mode') not in ('dev', 'replay') or not obj.get('model')
            or obj.get('unit_id') != card['task']['id']
            or obj.get('asof') != str(card['provenance']['data_cutoff'])
            or obj.get('assets') != card['targets']['asset_ids']
            or signal.get('fallback_reason') or signal.get('labels', {}).get('mode') != 'llm'):
        raise ValueError('Cache is not a successful dev/replay label artifact for this card')
    evidence = tuple(Evidence(**dict(e, assets=tuple(e['assets']))) for e in signal.get('evidence', []))
    cutoff = date.fromisoformat(obj['asof'])
    for e in evidence:
        if not e.doc_id or date.fromisoformat(e.timestamp[:10]) > cutoff:
            raise ValueError('Cache evidence has a missing ID or future timestamp')
    # Phase 3 emits neutral numerical scenarios. Only categorical labels are replayed.
    return replace(TextSignal.neutral(tuple(card['targets']['asset_ids'])), evidence=evidence,
        labels=signal['labels'], rationale_md=signal.get('rationale_md', ''), calls_used=0)


def metrics(frame):
    return dict(cards=len(frame), mean=float(frame.score.mean()), median=float(frame.score.median()),
                caps=int((frame.score >= 8).sum()), failures=int(frame.failed.sum()))


def decide(frames, *, expected=88):
    for frame in frames.values():
        if (len(frame) != expected or not frame.unit_id.is_unique or frame.unit_id.isna().any()
                or frame.family.isna().any() or frame.failed.any()
                or not np.isfinite(frame.score).all() or not frame.score.between(0, 8).all()):
            raise ValueError('Ship decision needs complete, unique, successful arm rosters')
    baseline = frames['numeric_v1_1'].set_index('unit_id')
    for frame in frames.values():
        if set(frame.unit_id) != set(baseline.index):
            raise ValueError('Unpaired arm roster')
        aligned = frame.set_index('unit_id').loc[baseline.index]
        if not (aligned.family == baseline.family).all():
            raise ValueError('Family assignments differ across arms')
    base = metrics(baseline)
    def improves(name):
        m = metrics(frames[name])
        return m['mean'] < base['mean'] and m['caps'] <= base['caps']
    chosen = 'numeric_v1_1'
    if 'text_l05' in frames and improves('text_l05'):
        chosen = 'text_l05'
        if 'text_l10' in frames:
            low, high = frames['text_l05'], frames['text_l10']
            a, b = metrics(low), metrics(high)
            bf = baseline.groupby('family').score.mean()
            lf = low.groupby('family').score.mean().reindex(bf.index)
            hf = high.groupby('family').score.mean().reindex(bf.index)
            if (b['mean'] < a['mean'] and b['caps'] <= min(a['caps'], base['caps'])
                    and (hf < bf).all() and (hf <= lf).all()):
                chosen = 'text_l10'
    elif improves('card_notes_l05'):
        chosen = 'card_notes_l05'
    return dict(selected=chosen, provisional=not all(a in frames for a in ARMS),
                mode={'numeric_v1_1':'numeric_only', 'text_l05':'labels',
                      'text_l10':'labels', 'card_notes_l05':'card_notes_only'}[chosen],
                **{'lambda': 1. if chosen == 'text_l10' else .5})


def paired_ci(delta, years):
    rng = np.random.default_rng(20261015)
    blocks = [np.asarray(delta)[np.asarray(years) == year] for year in np.unique(years)]
    sums = np.array([b.sum() for b in blocks]); sizes = np.array([len(b) for b in blocks])
    picks = rng.integers(len(blocks), size=(10000, len(blocks)))
    return np.quantile(sums[picks].sum(axis=1)/sizes[picks].sum(axis=1), [.025, .975]).tolist()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--roster', type=Path, default=DEFAULT_ROSTER)
    parser.add_argument('--labels-dir', type=Path, default=Path('.eval/text_signals'))
    parser.add_argument('--out', type=Path, default=Path('reports/phase4'))
    parser.add_argument('--work', type=Path, default=Path('.eval/phase4'))
    args = parser.parse_args(argv)
    if version('qfbench2-common') != '2.6.0':
        parser.error('The frozen comparison requires qfbench2-common==2.6.0')
    roster = json.loads(args.roster.read_text())
    if len(roster) != 88 or len({Path(c['unit']).name for c in roster}) != 88:
        raise ValueError('Expected the frozen 88-card practice roster')
    args.out.mkdir(parents=True, exist_ok=True)
    args.work.mkdir(parents=True, exist_ok=True)
    labels, missing, label_hashes = {}, {}, {}
    for case in roster:
        unit = Path(case['unit']); card = read_card(unit/'card.toml'); uid = card['task']['id']
        path = args.labels_dir/(uid+'.json')
        try:
            labels[uid] = cached_signal(path, card)
            label_hashes[uid] = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            missing[uid] = f'{type(exc).__name__}: {exc}'
    active = list(ARMS) if not missing else ['numeric_v1_1', 'card_notes_l05']
    records = {arm:[] for arm in active}
    inputs = hashlib.sha256(args.roster.read_bytes())
    for i, case in enumerate(roster, 1):
        unit = Path(case['unit']); card = read_card(unit/'card.toml'); panels = read_panels(unit/'panels')
        uid = card['task']['id']; asof = str(card['provenance']['data_cutoff']); seed = m0.resolve_seed(card, None)
        for path in sorted(set([unit/'card.toml', *unit.glob('*.json'), *unit.glob('*.parquet'),
                                *(unit/'panels').glob('*.parquet'), Path(case['realized'])])):
            inputs.update(str(path).encode()); inputs.update(path.read_bytes())
        numeric = numeric_v1_1.forecast(card, panels, None, asof, 2000, seed, text_mode='numeric_only')
        draws = numeric.value.to_numpy().reshape(2000, -1)
        summary = numeric_summary_from(card, panels, asof, samples=draws)
        divisors = expected_errors(m0.distribution(card, panels, asof))
        for arm in active:
            mapped = None
            if arm == 'numeric_v1_1':
                frame = numeric
            elif arm == 'card_notes_l05':
                frame = numeric_v1_1.forecast(card, panels, unit/'text', asof, 2000, seed,
                                             text_mode='card_notes_only', text_lambda=.5)
                mapped = frame.attrs.get('text_signal')
                if mapped is None or mapped.fallback_reason or mapped.labels.get('mode') != 'card_notes_only':
                    raise RuntimeError(f'Card notes silently failed: {uid}')
            else:
                mapped = apply_text_map(labels[uid], summary, .5 if arm == 'text_l05' else 1.)
                adjusted = numeric_v1.apply_text_signal(draws, card, mapped, seed)
                frame = sample_frame(card, adjusted)
                frame.attrs['rationale'] = numeric.attrs['rationale'] + '\n\n' + mapped.rationale_md + '\n' + evidence_ledger(mapped)
            if mapped is not None and mapped.calls_used:
                raise RuntimeError('A replay/card-notes ablation cannot send requests')
            out = args.work/arm/uid/'forecast.parquet'
            write_forecast(card, frame, out)
            payload = score(unit/'card.toml', out, Path(case['realized']))
            row = {**describe(card), **normalize(payload, divisors, draws.shape[1]),
                   'requests_used':0, 'numeric_fallback':numeric.attrs.get('fallback'),
                   'regime':mapped.labels.get('regime') if mapped else '',
                   'event':mapped.labels.get('event_in_horizon') if mapped else ''}
            records[arm].append(row)
        if i % 20 == 0 or i == len(roster):
            print(f'Phase 4: {i}/{len(roster)} cards, {len(active)} arms', flush=True)
    frames = {k:pd.DataFrame(v).sort_values('unit_id').reset_index(drop=True) for k,v in records.items()}
    decision = decide(frames)
    source = hashlib.sha256()
    for path in sorted([*Path('t2agent').rglob('*.py'), *Path('t2agent').glob('*.json'),
                        Path(__file__), Path('reports/phase4/VALIDATION.md')]):
        source.update(str(path).encode()); source.update(path.read_bytes())
    result = dict(decision=decision, available_labels=len(labels), missing_labels=missing,
                  label_hashes=label_hashes, input_sha256=inputs.hexdigest(), source_sha256=source.hexdigest(),
                  packages={p:version(p) for p in ('qfbench2-common','qfbench2-track-forecasting','numpy','pandas','scipy','pyarrow')},
                  QFBENCH_SEED=os.environ.get('QFBENCH_SEED'), n_draws=2000, arms={}, paired_ci={})
    baseline = frames['numeric_v1_1']
    deltas = baseline[['unit_id','asof','family']].copy()
    caps = []
    family_rows = []
    for arm, frame in frames.items():
        frame.to_csv(args.out/(arm+'.csv'), index=False, lineterminator='\n')
        result['arms'][arm] = metrics(frame)
        delta = frame.score-baseline.score
        deltas[arm+'_score'] = frame.score; deltas[arm+'_delta'] = delta
        result['paired_ci'][arm] = paired_ci(delta, pd.to_datetime(frame['asof']).dt.year)
        for family, group in frame.groupby('family'):
            family_rows.append(dict(arm=arm, family=family, **metrics(group)))
        for row, before in zip(frame.itertuples(), baseline.score):
            if (row.score >= 8) != (before >= 8):
                caps.append(dict(arm=arm, unit_id=row.unit_id, change='new' if row.score >= 8 else 'removed',
                                 baseline_score=before, score=row.score))
    deltas.to_csv(args.out/'per-card-deltas.csv', index=False, lineterminator='\n')
    pd.DataFrame(family_rows).to_csv(args.out/'families.csv', index=False, lineterminator='\n')
    pd.DataFrame(caps, columns=['arm','unit_id','change','baseline_score','score']).to_csv(args.out/'cap-changes.csv', index=False)
    (args.out/'results.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    lines = ['# Phase 4 practice ablation', '',
             f"Decision: **{decision['selected']}**" + (' (provisional: full model-label replay unavailable).' if decision['provisional'] else '.'),
             '', f"88 paired practice proxies; 2,000 draws; {len(labels)}/88 successful cached model labels available.", '',
             '| arm | mean | median | caps | mean delta 95% year-block CI |', '|---|---:|---:|---:|---|']
    for arm in ARMS:
        if arm not in frames:
            lines.append(f'| {arm} | unavailable | unavailable | unavailable | missing validated cache |')
        else:
            m = result['arms'][arm]; lo,hi = result['paired_ci'][arm]
            lines.append(f"| {arm} | {m['mean']:.6f} | {m['median']:.6f} | {m['caps']} | [{lo:+.6f}, {hi:+.6f}] |")
    lines += ['', '| family | arm | cards | mean | caps |', '|---|---|---:|---:|---:|']
    for row in family_rows:
        lines.append(f"| {row['family']} | {row['arm']} | {row['cards']} | {row['mean']:.6f} | {row['caps']} |")
    lines += ['', 'No model requests were sent. Per-card deltas and new/removed caps are in the accompanying CSVs.',
              'The B4 v2 rules inherited prior practice exposure; this is a development comparison, not an untouched holdout.',
              'Coefficients and decision gates were frozen in VALIDATION.md before this run. No competition pack/upload.', '']
    (args.out/'RESULTS.md').write_text('\n'.join(lines))
    print('\n'.join(lines), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
