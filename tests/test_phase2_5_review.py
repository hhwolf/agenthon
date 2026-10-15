"""Independent edge-case invariants from the Phase 2.5 shipping review."""
from dataclasses import asdict
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import tomli_w

from t2agent import cli, numeric_v1_1 as nv
from t2eval.phase2_5 import bootstrap, choose, gates


def test_short_fhs_history_preserves_covariance_and_heavy_tails():
    covariance = np.array([[2., .7], [.7, 1.]])
    draws = nv.block_shock(np.random.default_rng(39), np.zeros((19, 2)),
                          21, covariance, 200000)
    np.testing.assert_allclose(np.cov(draws, rowvar=False), covariance,
                               rtol=.04, atol=.025)
    np.testing.assert_allclose(draws.mean(axis=0), 0., atol=.025)
    assert np.mean(abs(draws[:, 0]) > 4*np.sqrt(covariance[0, 0])) > .001


@pytest.mark.parametrize('steps', [1, 5, 21])
@pytest.mark.parametrize('constant', [False, True])
def test_rank_deficient_fhs_supplies_missing_covariance(steps, constant):
    x = np.zeros(80) if constant else np.random.default_rng(8).normal(size=80)
    residuals = np.column_stack([x, 2*x])
    covariance = np.array([[2., .7], [.7, 1.]])
    draws = nv.block_shock(np.random.default_rng(17), residuals, steps,
                          covariance, 100000)
    assert np.isfinite(draws).all()
    np.testing.assert_allclose(np.cov(draws, rowvar=False), covariance,
                               rtol=.03, atol=.025)
    np.testing.assert_allclose(draws.mean(axis=0), 0., atol=.025)


def test_filter_does_not_use_current_innovation_to_estimate_its_scale():
    dates = pd.bdate_range('2020-01-01', periods=100)
    values = np.random.default_rng(6).normal(size=100)
    # Centering may move every residual. Relative to an earlier residual, the
    # final innovation must remain linear because its scale was already known.
    differences = []
    for last_change in (0., 1., 2.):
        changed = values.copy()
        changed[-1] = last_change
        series = pd.Series(changed, index=dates)
        prepared = SimpleNamespace(histories={'A': series},
                                   increments=pd.DataFrame({'A': series}))
        residuals = nv.filtered_residuals(prepared, nv.Config(monthly=False))
        differences.append(residuals[-1, 0]-residuals[0, 0])
    assert differences[2]-differences[0] == pytest.approx(
        2*(differences[1]-differences[0]), abs=1e-12)


@pytest.mark.parametrize('corrupt', [False, True])
def test_cli_unreadable_panels_still_writes_finite_default_triplet(tmp_path, monkeypatch, corrupt):
    monkeypatch.delenv('T2_DEFAULT_FORECASTER', raising=False)
    monkeypatch.delenv('QFBENCH_SEED', raising=False)
    card = {'task': {'id': 'review-recovery'},
            'provenance': {'data_cutoff': '2024-01-05'},
            'targets': {'asset_ids': ['A', 'B'], 'horizons': [1, 5],
                        'target_type': 'level'}}
    (tmp_path/'card.toml').write_text(tomli_w.dumps(card))
    panels = tmp_path/'panels'
    panels.mkdir()
    if corrupt:
        (panels/'broken.parquet').write_bytes(b'not a parquet file')
    out = tmp_path/'output'/'forecast.parquet'
    cli.main(['--panels', str(panels), '--asof', '2024-01-05',
              '--out', str(out), '--seed', '12'])
    draws = pd.read_parquet(out)
    assert draws.draw.nunique() == 2000
    assert len(draws) == 8000 and np.isfinite(draws.value).all()
    assert draws.groupby('draw').size().eq(4).all()
    assert {p.name for p in out.parent.iterdir()} == {
        'forecast.parquet', 'forecast_meta.json', 'forecast_rationale.md'}
    assert json.loads(out.with_name('forecast_meta.json').read_text())['n_draws'] == 2000
    rationale = out.with_name('forecast_rationale.md').read_text()
    assert 'last-resort wide random walk' in rationale
    assert 'Panel load failed:' in rationale


def selection_rows(group_size=40, panel='rates_daily'):
    rows = []
    for dataset, year, count in [('historical', 2010, 100),
                                  ('historical', 2020, 50), ('practice', 2010, 50)]:
        for index in range(count):
            rows.append({'unit_id': f'{dataset}-{year}-{index}', 'dataset': dataset,
                         'year': year, 'family': 'F1', 'shape': 'single',
                         'horizon_bucket': '127+', 'score': 1.,
                         'panel': panel if index < group_size else 'fx_daily'})
    return pd.DataFrame(rows)


@pytest.mark.parametrize('panel,threshold', [('rates_daily', 40), ('macro_monthly', 20)])
@pytest.mark.parametrize('at_threshold', [False, True])
def test_c1_enforces_major_group_thresholds(panel, threshold, at_threshold):
    base = selection_rows(threshold if at_threshold else threshold-1, panel)
    candidate = base.copy()
    cv = (candidate.dataset == 'historical') & (candidate.year == 2010)
    candidate.loc[cv, 'score'] = .8
    candidate.loc[cv & candidate.panel.eq(panel), 'score'] = 1.11
    eligible, reasons, veto = gates(candidate, base, base)
    assert eligible is not at_threshold
    assert any(f'panel={panel} >10%' in reason for reason in reasons) is at_threshold
    assert not any(veto.values())


def test_c1_allows_exact_ten_percent_group_boundary():
    base = selection_rows()
    candidate = base.copy()
    cv = (candidate.dataset == 'historical') & (candidate.year == 2010)
    candidate.loc[cv, 'score'] = .8
    candidate.loc[cv & candidate.panel.eq('rates_daily'), 'score'] = 1.1
    assert gates(candidate, base, base)[0]


def test_c1_rejects_cap_increase_despite_better_mean():
    base = selection_rows()
    candidate = base.copy()
    candidate.loc[(candidate.dataset == 'historical') & (candidate.year == 2010), 'score'] = .8
    candidate.loc[0, 'score'] = 8.
    eligible, reasons, _ = gates(candidate, base, base)
    assert not eligible and 'CV+practice caps rose' in reasons


@pytest.mark.parametrize('mean_increase,eligible', [(.005, True), (.005001, False)])
def test_c1_cap_tradeoff_has_fixed_mean_tolerance(mean_increase, eligible):
    base = selection_rows()
    base.loc[0, 'score'] = 8.
    candidate = base.copy()
    candidate.loc[0, 'score'] = 7.9
    candidate.loc[1:99, 'score'] += (100*mean_increase+.1)/99
    actual, reasons, _ = gates(candidate, base, base)
    assert actual is eligible
    assert ('CV mean/cap tradeoff failed' in reasons) is not eligible


def choice(name, mean, *, config=None, caps=0):
    return {'name': name, 'config': asdict(config or nv.Config()),
            'metrics': {'cv': {'mean': mean, 'capped': caps},
                        'practice': {'capped': 0}}}


def test_selection_ties_use_complexity_then_caps_then_name():
    complex_best = choice('complex', 1., config=nv.Config(tails='fhs5'))
    simpler = choice('simple', 1.0004, caps=10)
    assert choose([complex_best, simpler])['name'] == 'simple'
    outside_tie = choice('outside', 1.000501)
    assert choose([complex_best, outside_tie])['name'] == 'complex'
    assert choose([choice('a', 1., caps=2), choice('z', 1., caps=1)])['name'] == 'z'
    assert choose([choice('z', 1.), choice('a', 1.)])['name'] == 'a'


def test_year_bootstrap_preserves_card_weights_for_unequal_years(monkeypatch):
    base = pd.DataFrame({'unit_id': ['a', 'b', 'c', 'd'],
                         'year': [2010, 2011, 2011, 2011], 'score': [2.]*4})
    candidate = base.copy()
    candidate['score'] = [0., 3., 3., 3.]
    # Fix the sampled years to one of each, isolating aggregation from RNG.
    # Equal weighting of the year means would give -.5 instead of .25.
    rng = SimpleNamespace(integers=lambda high, size: np.tile([0, 1], (size[0], 1)))
    monkeypatch.setattr(np.random, 'default_rng', lambda seed: rng)
    result = bootstrap(candidate.sample(frac=1, random_state=7), base)
    assert result['delta'] == pytest.approx(.25)
    assert result['years'] == 2 and result['year_wins'] == 1
    np.testing.assert_allclose(result['ci95'], [.25, .25])
    assert result['resamples'] == 10000


@pytest.mark.parametrize('comparison', ['bootstrap', 'gates'])
@pytest.mark.parametrize('problem', ['missing', 'duplicate', 'null_id', 'nonfinite', 'year', 'panel'])
def test_comparisons_reject_unpaired_or_changed_rosters(comparison, problem):
    base = selection_rows()
    candidate = base.copy()
    candidate['score'] *= .9
    if problem == 'missing':
        candidate = candidate.iloc[1:]
    elif problem == 'duplicate':
        candidate = pd.concat([candidate, candidate.iloc[:1]], ignore_index=True)
    elif problem == 'null_id':
        candidate.loc[0, 'unit_id'] = None
    elif problem == 'nonfinite':
        candidate.loc[0, 'score'] = np.nan
    elif problem == 'year':
        candidate.loc[0, 'year'] = 2020
    else:
        candidate.loc[0, 'panel'] = 'changed-panel'
    with pytest.raises(ValueError, match='unique|roster|finite|metadata'):
        if comparison == 'bootstrap':
            bootstrap(candidate, base)
        else:
            gates(candidate, base, base)
