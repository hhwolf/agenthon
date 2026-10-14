"""Contract, causality, fallback and joint-path tests for the numeric engine."""
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from t2agent import m0, numeric_v1 as nv
from t2agent.io import read_card, read_panels, write_forecast


@pytest.fixture
def input_case():
    rng=np.random.default_rng(13)
    dates=pd.bdate_range('2018-01-01',periods=900)
    values=10+np.cumsum(rng.normal(0,.05,len(dates)))
    card={'task':{'id':'numeric-test'},'provenance':{'data_cutoff':str(dates[-1].date())},
          'targets':{'asset_ids':['A','B'],'horizons':[1,5,21],'target_type':'level'}}
    frame=pd.concat([pd.DataFrame({'date':dates,'asset':a,'value':values+i}) for i,a in enumerate(['A','B'])])
    return card,{'p.parquet':frame},card['provenance']['data_cutoff']


def test_m0_control_matches_existing_implementation(input_case):
    c,p,a=input_case
    actual=nv.sample(nv.prepare(c,p,a),nv.Config(),2000,9)
    expected=m0.forecast(c,p,None,a,2000,9).value.to_numpy().reshape(actual.shape)
    np.testing.assert_allclose(actual,expected,atol=1e-12)


def test_future_rows_cannot_change_forecast(input_case):
    c,p,a=input_case;config=nv.Config(volatility='blend',variance_ratio=True,joint=True,monthly=True)
    original=nv.sample(nv.prepare(c,p,a),config,2000,7)
    future=p['p.parquet'].iloc[:2].copy();future['date']=pd.Timestamp(a)+pd.Timedelta(days=20);future['value']=1e12
    changed={'p.parquet':pd.concat([p['p.parquet'],future])}
    np.testing.assert_array_equal(original,nv.sample(nv.prepare(c,changed,a),config,2000,7))


def test_joint_continuation_and_shared_cross_asset_shocks(input_case):
    c,p,a=input_case;prepared=nv.prepare(c,p,a);config=nv.Config(joint=True)
    draws=nv.sample(prepared,config,80000,7)
    noise=draws-nv.moments(prepared,config)[0]
    increments=np.column_stack([noise[:,0],noise[:,1]-noise[:,0],noise[:,2]-noise[:,1]])
    cross=np.corrcoef(increments.T)-np.eye(3)
    assert abs(cross).max()<.015
    # Identical histories with 20% identity shrinkage should correlate at .8.
    assert np.corrcoef(noise[:,0],noise[:,3])[0,1]==pytest.approx(.8,abs=.015)
    covariance=nv.moments(prepared,config)[1]
    np.testing.assert_allclose(np.cov(noise,rowvar=False),covariance,rtol=.025,atol=.0003)


def test_neutral_hook_preserves_every_byte_and_seed(input_case,tmp_path,monkeypatch):
    from types import SimpleNamespace
    c,p,a=input_case;monkeypatch.setenv('QFBENCH_SEED','92')
    monkeypatch.setattr(nv,'selected_config',lambda:nv.Config(volatility='blend',tails='mixture'))
    neutral=SimpleNamespace(scenarios=(SimpleNamespace(weight=1.,drift_sd={'A':0.,'B':0.},vol_mult=1.),),tail_mult=1.)
    base=nv.forecast(c,p,None,a);other=nv.forecast(c,p,None,a,seed=92,text_signal=neutral)
    assert base.draw.nunique()==2000
    pd.testing.assert_frame_equal(base,other)
    for name,frame in [('base',base),('neutral',other)]:write_forecast(c,frame,tmp_path/name/'forecast.parquet')
    for filename in ('forecast.parquet','forecast_meta.json','forecast_rationale.md'):
        assert (tmp_path/'base'/filename).read_bytes()==(tmp_path/'neutral'/filename).read_bytes()


def test_scenarios_use_one_label_for_whole_joint_draw(input_case):
    c,_,_=input_case
    z=np.random.default_rng(1).normal(size=(2000,1));samples=np.repeat(z,6,axis=1)
    signal={'scenarios':[{'weight':.5,'drift_sd':{'A':.5,'B':.5}},
                         {'weight':.5,'drift_sd':{'A':-.5,'B':-.5}}]}
    result=nv.apply_text_signal(samples,c,signal,7)
    np.testing.assert_array_equal(result[:,0],result[:,5])
    shifts=(result-samples)[:,0]
    assert (shifts>0).sum()>800 and (shifts<0).sum()>800


@pytest.mark.parametrize('bad',[{'drift_sd':{'A':float('nan')}},{'scenarios':[]}])
def test_bad_hook_keeps_numeric_samples(input_case,monkeypatch,bad):
    c,p,a=input_case
    monkeypatch.setattr(nv,'selected_config',lambda:nv.Config())
    original=nv.forecast(c,p,None,a,seed=7)
    result=nv.forecast(c,p,None,a,seed=7,text_signal=bad)
    np.testing.assert_array_equal(result.value,original.value)
    assert 'Text hook ignored' in result.attrs['rationale']


def test_numeric_failure_falls_back_to_m0(input_case,monkeypatch,tmp_path):
    c,p,a=input_case
    def fail(*args,**kwargs):raise ArithmeticError('injected failure')
    monkeypatch.setattr(nv,'sample',fail)
    result=nv.forecast(c,p,None,a,seed=7)
    np.testing.assert_array_equal(result.value,m0.forecast(c,p,None,a,2000,7).value)
    assert result.attrs['fallback']=='M0 fallback'
    write_forecast(c,result,tmp_path/'forecast.parquet')
    assert len(list(tmp_path.iterdir()))==3


def test_missing_panels_still_writes_finite_joint_triplet(input_case,tmp_path):
    c,_,a=input_case
    result=nv.forecast(c,{},None,a,seed=7)
    assert result.attrs['fallback']=='last-resort wide random walk'
    assert np.isfinite(result.value).all() and result.draw.nunique()==2000
    write_forecast(c,result,tmp_path/'forecast.parquet')
    assert len(list(tmp_path.iterdir()))==3
    assert json.loads((tmp_path/'forecast_meta.json').read_text())['n_draws']==2000


def test_monthly_uses_released_anchor_named_period_and_log_trend():
    dates=pd.date_range('2020-01-01',periods=36,freq='MS')
    c={'task':{'id':'monthly-test'},'provenance':{'data_cutoff':'2023-02-01'},
       'targets':{'asset_ids':['INDEX'],'horizons':[140],'target_type':'level','observation_periods':['2023-06']}}
    p={'macro_monthly.parquet':pd.DataFrame({'date':dates,'asset':'INDEX','value':100*np.exp(np.arange(36)*.002)})}
    prep=nv.prepare(c,p,'2023-02-01')
    assert prep.baseline.steps.tolist()==[6.]
    mean,_,logs,_=nv.moments(prep,nv.Config(monthly=True))
    assert logs.tolist()==[True]
    assert np.exp(mean[0])==pytest.approx(100*np.exp(41*.002))
    c['targets']['asset_ids']=['UNRATE'];p['macro_monthly.parquet']['asset']='UNRATE'
    prep=nv.prepare(c,p,'2023-02-01')
    mean,_,logs,_=nv.moments(prep,nv.Config(monthly=True))
    assert not logs.any() and mean[0]==p['macro_monthly.parquet'].value.iloc[-1]


def test_ten_asset_output_under_limit(tmp_path):
    for unit in Path('vendor/track2/units').iterdir():
        if not (unit/'card.toml').exists():continue
        c=read_card(unit/'card.toml')
        if len(c['targets']['asset_ids'])==10:break
    else:pytest.fail('No 10-asset practice card')
    result=nv.forecast(c,read_panels(unit/'panels'),None,c['provenance']['data_cutoff'],seed=7)
    assert result.attrs['fallback'] is None
    write_forecast(c,result,tmp_path/'forecast.parquet')
    assert sum(p.stat().st_size for p in tmp_path.iterdir())<8*1024**2
