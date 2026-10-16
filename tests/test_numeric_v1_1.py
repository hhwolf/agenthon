"""Phase 2.5 distribution invariants and protocol gates, without outcome tuning."""
from dataclasses import replace
from copy import deepcopy
import json

import numpy as np
import pandas as pd
import pytest

from t2agent import numeric_v1 as old, numeric_v1_1 as nv
from t2agent.io import write_forecast
from test_numeric_v1 import input_case


def test_baseline_is_bit_identical(input_case):
    c, p, a = input_case; prep = old.prepare(c, p, a)
    np.testing.assert_array_equal(nv.sample(prep, nv.Config(), 2000, 7),
                                  old.sample(prep, old.selected_config(), 2000, 7))


@pytest.mark.parametrize('kind', ['student_unit', 'mixture_unit'])
def test_tails_have_unit_variance_and_heavy_extremes(kind):
    rng = np.random.default_rng(91)
    z = rng.normal(size=500000)*nv.tail_scale(rng, 500000, kind)
    assert z.var() == pytest.approx(1., abs=.025)
    assert np.mean(abs(z) > 4) > .001


def test_fhs_normalizes_block_variance_and_joint_dependence():
    rng = np.random.default_rng(3)
    x = rng.standard_t(5, (500, 2))
    x[1:] += .5*x[:-1]
    covariance = np.array([[2., .7], [.7, 1.]])
    z = nv.block_shock(rng, x, 21, covariance, 90000)
    np.testing.assert_allclose(np.cov(z, rowvar=False), covariance, rtol=.025, atol=.02)
    np.testing.assert_allclose(z.mean(axis=0), 0., atol=.02)


@pytest.mark.parametrize('config', [nv.Config(term_tau=126, vol_floor=.5),
                                    nv.Config(tails='fhs5'), nv.Config(momentum=.25)])
def test_causal_deterministic_and_shared_paths(input_case, config):
    c, p, a = input_case
    prep = old.prepare(c, p, a)
    expected = nv.sample(prep, config, 2000, 91)
    future = p['p.parquet'].iloc[:2].copy()
    future['date'] = pd.Timestamp(a)+pd.Timedelta(days=10); future['value'] = 1e20
    altered = {'p.parquet':pd.concat([p['p.parquet'], future])}
    np.testing.assert_array_equal(expected, nv.sample(old.prepare(c, altered, a), config, 2000, 91))
    draws = nv.sample(prep, config, 40000, 2)-nv.moments(prep, config)[0]
    increments = np.column_stack([draws[:, 0], draws[:, 1]-draws[:, 0], draws[:, 2]-draws[:, 1]])
    assert np.max(abs(np.corrcoef(increments.T)-np.eye(3))) < .03


def test_term_structure_floor_and_momentum(input_case):
    c, p, a = input_case; prep = old.prepare(c, p, a)
    base = nv.moments(prep, nv.Config())[1]
    config = nv.Config(term_tau=126, vol_floor=.5, momentum=.1)
    mean, cov, _, _ = nv.moments(prep, config)
    for k, asset in enumerate(['A']*3+['B']*3):
        h = prep.baseline.steps[k]
        long = prep.increments[asset].var()
        recent = base[k,k]/h
        wanted = max(np.exp(-h/126)*recent + (1-np.exp(-h/126))*long, .5*long)*h
        assert cov[k,k] == pytest.approx(wanted, abs=1e-10)
        direction = np.sign(prep.increments[asset].dropna().tail(126).sum())
        assert mean[k] == pytest.approx(prep.histories[asset].iloc[-1]+direction*.1*np.sqrt(cov[k,k]))


def test_monthly_damping_and_release_mapping():
    dates = pd.date_range('2020-01-01', periods=36, freq='MS')
    c = {'task':{'id':'monthly-test'}, 'provenance':{'data_cutoff':'2023-02-01'},
         'targets':{'asset_ids':['INDEX'],'horizons':[140],'target_type':'level','observation_periods':['2023-06']}}
    p = {'macro_monthly.parquet':pd.DataFrame({'date':dates,'asset':'INDEX','value':100*np.exp(np.arange(36)*.002)})}
    prep = old.prepare(c, p, '2023-02-01')
    assert prep.baseline.steps[0] == 6
    for damping in (.25, .5):
        mean = nv.moments(prep, nv.Config(monthly_damping=damping))[0]
        assert np.exp(mean[0]) == pytest.approx(100*np.exp((35+6*damping)*.002))


def test_pool_splits_whole_joint_draws_and_roundtrips(input_case):
    c, p, a = input_case; prep = old.prepare(c, p, a)
    cfg = nv.Config(components=(nv.Config(tails='student_unit'), nv.Config(monthly=False)))
    assert nv.config_from_dict(json.loads(json.dumps(nv.asdict(cfg)))) == cfg
    seeds = np.random.SeedSequence([7, 0x2511]).generate_state(2)
    draws = nv.sample(prep, cfg, 2001, 7)
    np.testing.assert_array_equal(draws[:1000], nv.sample(prep, cfg.components[0], 1000, int(seeds[0])))
    np.testing.assert_array_equal(draws[1000:], nv.sample(prep, cfg.components[1], 1001, int(seeds[1])))


def test_neutral_hook_and_recovery_write_triplets(input_case, monkeypatch, tmp_path):
    c, p, a = input_case
    monkeypatch.setattr(nv, 'selected_config', lambda:nv.Config(tails='student_unit'))
    monkeypatch.setenv('QFBENCH_SEED', '9')
    base = nv.forecast(c, p, None, a)
    neutral = nv.forecast(c, p, None, a, seed=9, text_signal={'drift_sd':{}, 'vol_mult':1})
    for name, frame in [('base', base), ('neutral', neutral)]:
        write_forecast(c, frame, tmp_path/name/'forecast.parquet')
    for path in (tmp_path/'base').iterdir():
        assert path.read_bytes() == (tmp_path/'neutral'/path.name).read_bytes()
    def fail(*args, **kwargs): raise ValueError('injected')
    monkeypatch.setattr(nv, 'sample', fail)
    fallback = nv.forecast(c, p, None, a, seed=9)
    assert fallback.attrs['fallback'] == 'M0 fallback'
    wide = nv.forecast(c, {}, None, a, seed=9)
    assert wide.attrs['fallback'] == 'last-resort wide random walk'
    write_forecast(c, wide, tmp_path/'wide'/'forecast.parquet')
    assert len(list((tmp_path/'wide').iterdir())) == 3


def test_cli_selects_new_default_and_preserves_old_image_default(input_case, monkeypatch, tmp_path):
    from t2agent import cli
    c, p, a = input_case
    monkeypatch.setattr(cli, 'read_card', lambda path:c)
    monkeypatch.setattr(cli, 'read_panels', lambda path:p)
    seen = []
    def result(name):
        def run(card, panels, text, asof, n_draws, seed):
            seen.append((name, n_draws))
            frame = nv.sample_frame(card, np.zeros((n_draws, 6)))
            frame.attrs['rationale'] = 'CLI routing test'
            return frame
        return run
    monkeypatch.setattr(cli.numeric_v1_1, 'forecast', result('v1.1'))
    monkeypatch.setattr(cli.numeric_v1, 'forecast', result('v1'))
    monkeypatch.delenv('T2_DEFAULT_FORECASTER', raising=False)
    args = ['--panels',str(tmp_path),'--card',str(tmp_path/'card.toml'),'--asof',a,'--out',str(tmp_path/'forecast.parquet')]
    cli.main(args)
    monkeypatch.setenv('T2_DEFAULT_FORECASTER', 'numeric_v1')
    cli.main(args)
    assert seen == [('v1.1', 2000), ('v1', 2000)]
