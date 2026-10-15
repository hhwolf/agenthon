"""Phase 4 integration invariants, tested without any provider or realized outcomes."""
import ast
from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from t2agent import numeric_v1 as old, numeric_v1_1 as nv
from t2agent.contracts import CallBudget, Evidence, Scenario, TextSignal
from t2agent.text_layer import read_text
from t2agent.text_overlay import apply_text_map, lambda_from_env
from t2eval.phase4 import cached_signal, decide
from test_numeric_v1 import input_case
from test_text_layer import make_summary, _labelled


def binary_signal(disagreement=False):
    return _labelled(regime='crisis', event_in_horizon='scheduled_binary', disagreement=disagreement,
        assets={'GBP':{'direction':'strong_down'}, 'EUR':{'direction':'up'}},
        branches=[{'label':'a','prob':.99,'signs':{'GBP':-1,'EUR':1}},
                  {'label':'b','prob':.01,'signs':{'GBP':1,'EUR':-1}}])


def test_map_file_has_constants_only():
    nodes = ast.parse(Path('t2agent/text_map.py').read_text()).body
    assert all(isinstance(n, (ast.Expr, ast.Assign)) for n in nodes)
    for node in nodes:
        if isinstance(node, ast.Assign):
            ast.literal_eval(node.value)


@pytest.mark.parametrize('lam', [.5, 1.])
def test_disagreement_suppresses_every_binary_drift_and_asymmetric_tail(lam):
    signal = apply_text_map(binary_signal(True), make_summary(assets=('GBP','EUR')), lam)
    assert all(v == 0 for s in signal.scenarios for v in s.drift_sd.values())
    assert all(s.vol_mult >= 1+lam*.15 for s in signal.scenarios)
    assert signal.tail_signs == {} and not signal.branch_mixture


@pytest.mark.parametrize('lam', [.5, 1.])
def test_binary_branches_are_shared_across_assets_and_horizons(lam):
    summary = make_summary(assets=('GBP','EUR'))
    signal = apply_text_map(binary_signal(), summary, lam)
    signal = replace(signal, scenarios=tuple(replace(s,vol_mult=1) for s in signal.scenarios), tail_mult=1)
    assert signal.scenarios[0].drift_sd == {'GBP':-lam, 'EUR':lam}
    samples = np.random.default_rng(7).normal(size=(20000,4))
    card = {'targets':{'asset_ids':['GBP','EUR'],'horizons':[5,21]}}
    out = old.apply_text_signal(samples, card, signal, 12)
    shift = (out-samples)/samples.std(axis=0,ddof=1)
    np.testing.assert_allclose(shift[:,0], shift[:,1], atol=1e-12)
    np.testing.assert_allclose(shift[:,0], -shift[:,2], atol=1e-12)
    np.testing.assert_allclose(shift[:,2], shift[:,3], atol=1e-12)
    np.testing.assert_allclose(abs(shift), lam, atol=1e-12)
    assert np.mean(shift[:,0] < 0) == pytest.approx(.8, abs=.015)
    np.testing.assert_array_equal(out, old.apply_text_signal(samples, card, signal, 12))


def test_binary_rise_versus_unchanged_retains_the_fixed_branch_shift():
    labels = _labelled(event_in_horizon='scheduled_binary',
        branches=[{'prob':.8, 'signs':{'GBP':1}}, {'prob':.2, 'signs':{'GBP':0}}])
    signal = apply_text_map(labels, make_summary(), 1.)
    assert [s.drift_sd['GBP'] for s in signal.scenarios] == [1., 0.]
    signal = replace(signal, scenarios=tuple(replace(s,vol_mult=1) for s in signal.scenarios),tail_mult=1)
    samples = np.linspace(-3,3,2000)[:,None]
    result = old.apply_text_signal(samples, {'targets':{'asset_ids':['GBP'],'horizons':[1]}},signal,1)
    shifts = (result-samples)/samples.std(ddof=1)
    assert np.isclose(shifts,1).sum() > 1500
    assert np.isclose(shifts,0).sum() > 300


@pytest.mark.parametrize('family,regime', [('T2-F1','crisis'),('T2-F4','elevated')])
def test_named_crisis_or_f4_tail_expands_only_adverse_side(family, regime):
    summary = make_summary(family=family)
    signal = apply_text_map(_labelled(regime=regime, assets={'GBP':{'direction':'down'}}), summary, 1)
    assert signal.tail_mult == 1.5 and signal.tail_signs == {'GBP':-1}
    signal = replace(signal, scenarios=(Scenario('test',1,{'GBP':0},1),))
    samples = np.linspace(-3,3,2000)[:,None]
    result = old.apply_text_signal(samples, {'targets':{'asset_ids':['GBP'],'horizons':[21]}}, signal, 7)
    np.testing.assert_allclose(result[samples[:,0] > 0], samples[samples[:,0] > 0], atol=1e-15)
    assert (result[:100] < samples[:100]).all()
    np.testing.assert_allclose(result[100:], samples[100:], atol=1e-15)


def test_lambda_zero_neutralizes_non_neutral_supplied_signal():
    summary = make_summary()
    signal = replace(_labelled(regime='crisis'), scenarios=(Scenario('wide',1,{'GBP':.5},1.6),), tail_mult=1.5)
    mapped = apply_text_map(signal, summary, 0)
    x = np.arange(2000.)[:,None]
    assert old.apply_text_signal(x, {'targets':{'asset_ids':['GBP'],'horizons':[1]}}, mapped, 1) is x
    for bad in ('nan', 'inf', 'invalid'):
        assert lambda_from_env({'TEXT_LAYER_LAMBDA':bad}) == .5
    with pytest.raises(ValueError):
        apply_text_map(signal, summary, float('nan'))


def test_card_notes_never_load_corpus_or_use_house(monkeypatch, tmp_path):
    import t2agent.text_layer.pipeline as pipeline
    def forbidden(*args, **kwargs):
        raise AssertionError('Corpus/House touched in card-only mode')
    monkeypatch.setattr(pipeline, 'load_corpus', forbidden)
    monkeypatch.setattr(pipeline, 'HouseClient', forbidden)
    summary = replace(make_summary(), card_description='A financial crisis and emergency liquidity intervention.', card_text_notes='')
    budget = CallBudget()
    result = read_text(tmp_path, summary, budget, mode='card_notes_only')
    assert result.fallback_reason is None and result.labels['regime'] == 'elevated'
    assert budget.used == result.calls_used == 0
    assert result.evidence == ()


@pytest.mark.parametrize('engine',[old, nv])
def test_read_text_runs_after_sample_and_rationale_has_evidence(engine, input_case, monkeypatch, tmp_path):
    from t2agent import text_layer
    from t2agent.io import write_forecast
    card,panels,asof = input_case
    seen = []
    sample = engine.sample
    def sampled(*args, **kwargs):
        out = sample(*args, **kwargs); seen.append(out.copy()); return out
    def reader(unit, summary, budget, **kwargs):
        assert len(seen) == 1
        np.testing.assert_allclose(list(summary.horizon_sd.values()), seen[0].std(axis=0,ddof=1))
        return replace(TextSignal.neutral(summary.assets), labels={'mode':'llm','regime':'elevated'},
            evidence=(Evidence('decision-1',asof,'Policy decision',('A',),1,True),
                      Evidence('speech-2',asof,'Tone inferred',('B',),0,False)))
    monkeypatch.setattr(engine, 'sample', sampled)
    monkeypatch.setattr(text_layer, 'read_text', reader)
    out = engine.forecast(card, panels, tmp_path/'text', asof, 2000, 9, text_mode='labels', text_lambda=.5)
    assert out.attrs['fallback'] is None and out.attrs['text_signal'] is not None
    assert not np.array_equal(out.value.to_numpy().reshape(seen[0].shape),seen[0])
    write_forecast(card, out, tmp_path/'out'/'forecast.parquet')
    rationale = (tmp_path/'out'/'forecast_rationale.md').read_text()
    assert 'decision-1' in rationale and 'speech-2' in rationale and 'established' in rationale and 'inferred' in rationale


def test_text_exception_and_zero_lambda_preserve_numeric_draws(input_case, monkeypatch, tmp_path):
    from t2agent import text_layer
    c,p,a = input_case
    def bad(*args, **kwargs):
        raise RuntimeError('Broken text reader')
    monkeypatch.setattr(text_layer, 'read_text', bad)
    base = nv.forecast(c,p,None,a,seed=44)
    failed = nv.forecast(c,p,tmp_path/'text',a,seed=44,text_mode='labels')
    np.testing.assert_array_equal(base.value, failed.value)
    assert 'Broken text reader' in failed.attrs['rationale'] and failed.attrs['fallback'] is None
    zero = nv.forecast(c,p,tmp_path/'text',a,seed=44,text_mode='labels',text_lambda=0)
    np.testing.assert_array_equal(base.value, zero.value)
    assert 'Broken text reader' not in zero.attrs['rationale']


def test_inferred_signal_cannot_narrow_width():
    x = np.linspace(-2,2,2000)[:,None]
    c = {'targets':{'asset_ids':['GBP'],'horizons':[1]}}
    signal = TextSignal((Scenario('narrow',1,{},.8),))
    np.testing.assert_allclose(old.apply_text_signal(x,c,signal,1),x,atol=1e-15)
    signal = replace(signal, evidence=(Evidence('doc','2020-01-01','established',('GBP',),0,True),))
    assert old.apply_text_signal(x,c,signal,1).std() == pytest.approx(.8*x.std())
    hook = {'drift_sd':{}, 'vol_mult':.8, 'evidence':[{'doc_id':'dict-doc', 'timestamp':'2020-01-01',
            'claim':'explicit dictionary hook', 'assets':['GBP'], 'established':True}]}
    returned, ledger = old.read_forecast_text(c, {}, None, '2020-01-01', x, text_signal=hook)
    assert returned is hook and 'dict-doc' in ledger and 'established' in ledger


def test_replay_rejects_mock_mismatched_or_future_labels(tmp_path):
    card = {'task':{'id':'unit'},'provenance':{'data_cutoff':'2020-01-01'},'targets':{'asset_ids':['GBP']}}
    record = dict(mode='dev',model='dev-model',unit_id='unit',asof='2020-01-01',assets=['GBP'],
                  signal=dict(labels={'mode':'llm','regime':'elevated'},evidence=[]))
    path = tmp_path/'unit.json'; path.write_text(json.dumps(record))
    assert cached_signal(path,card).labels['regime'] == 'elevated'
    for change in ({'mode':'mock'}, {'unit_id':'other'}, {'asof':'2021-01-01'}, {'assets':['EUR']}):
        path.write_text(json.dumps(dict(record,**change)))
        with pytest.raises(ValueError): cached_signal(path,card)
    record['signal']['evidence'] = [dict(doc_id='doc',timestamp='2020-01-02',claim='future',assets=['GBP'],direction=0,established=True)]
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError): cached_signal(path,card)


def test_balanced_decision_checks_caps_families_and_full_pairing():
    def frame(scores):
        return pd.DataFrame(dict(unit_id=['a','b'],family=['F1','F2'],score=scores,failed=False))
    frames = {'numeric_v1_1':frame([2.,2.]),'card_notes_l05':frame([1.9,2.])}
    assert decide(frames,expected=2)['selected'] == 'card_notes_l05'
    assert decide(frames,expected=2)['provisional']
    frames.update(text_l05=frame([1.9,1.9]),text_l10=frame([1.4,1.95]))
    assert decide(frames,expected=2)['selected'] == 'text_l05'  # one family worse than lambda .5
    frames['text_l10'] = frame([1.8,1.8])
    assert decide(frames,expected=2)['selected'] == 'text_l10'
    frames['text_l10'].loc[0,'unit_id'] = 'wrong'
    with pytest.raises(ValueError): decide(frames,expected=2)
    frames = {'numeric_v1_1':frame([7.,7.]),'card_notes_l05':frame([6.,7.]),'text_l05':frame([8.,0.])}
    assert decide(frames,expected=2)['selected'] == 'card_notes_l05'  # lower mean but added cap
    frames['text_l05'].loc[0,'score'] = float('nan')
    with pytest.raises(ValueError): decide(frames,expected=2)
