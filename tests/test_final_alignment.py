from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from t2agent import m0, numeric_alignment as alignment, numeric_v1 as v1, numeric_v1_1 as nv
from t2agent.io import read_card, read_panels, write_forecast
from t2eval.final_alignment import metric
from t2eval.scales import expected_errors
from t2eval.official import score, normalize


def fixture():
    dates=pd.bdate_range('2020-01-01',periods=500)
    rng=np.random.default_rng(19)
    values=rng.normal(size=(500,2))*.01
    values[-60:]*=3
    panels={'rates_daily.parquet':pd.DataFrame({'date':np.tile(dates,2),
        'asset':np.repeat(['UST_2Y','UST_5Y'],500),'value':(2+values.cumsum(axis=0)).T.ravel()})}
    card={'task':{'id':'alignment-fixture'},'provenance':{'data_cutoff':str(dates[-1].date())},
          'targets':{'asset_ids':['UST_5Y','UST_2Y'],'horizons':[1,2,3,4],'target_type':'level'}}
    return card,panels


def test_strict_current_boundary_preserves_frozen_release():
    c,p=fixture();hist={'UST_2Y':pd.Series([1.,2.,3.],index=pd.date_range('2024-01-01',periods=3))}
    c['targets']=dict(asset_ids=['UST_2Y'],horizons=[2],target_type='level',target_dates=['2024-01-07'])
    assert m0.horizon_steps(c,hist).tolist()==[4.]  # Demonstrated old behavior.
    assert m0.horizon_steps(c,hist,strict_ratio=True).tolist()==[2.]
    c['targets']['target_dates']=['2024-01-08']
    assert m0.horizon_steps(c,hist,strict_ratio=True).tolist()==[5.]
    c['targets']['target_dates']=['2024-01-04']  # Reverse ratio exactly 2.
    assert m0.horizon_steps(c,hist).tolist()==[1.]
    assert m0.horizon_steps(c,hist,strict_ratio=True).tolist()==[2.]


def test_ewma_blend_preserves_psd_correlations_and_segment_marginals():
    c,panels=fixture();p=v1.prepare(c,panels,c['provenance']['data_cutoff']);cfg=nv.selected_config()
    mean,cov,logs,segments=nv.moments(p,cfg)
    bm,bc,bl,bs=nv.moments(p,replace(cfg,volatility='short_blend20'))
    recent=np.maximum(np.diag(p.baseline.step_covariance),1e-15)
    prior=np.array([p.increments[a].ewm(halflife=20,min_periods=20).var().shift(1).iloc[-1] for a in sorted(p.histories)])
    scale=np.sqrt((.5*recent+.5*prior)/recent)
    gridscale=scale[segments[2]]
    np.testing.assert_array_equal(mean,bm);np.testing.assert_array_equal(logs,bl)
    np.testing.assert_allclose(bc-np.eye(len(bc))*1e-12,(cov-np.eye(len(cov))*1e-12)*np.outer(gridscale,gridscale),rtol=1e-12,atol=1e-16)
    assert np.linalg.eigvalsh(bc).min()>0
    for a,b in zip(segments[1],bs[1]):
        np.testing.assert_allclose(b,a*np.outer(scale,scale),rtol=1e-12,atol=1e-16)
        assert np.linalg.eigvalsh(b).min()>=-1e-14
    # Explicitly verify the last increment is not included in lagged EWMA.
    for a,value in zip(sorted(p.histories),prior):
        assert value==pytest.approx(p.increments[a].iloc[:-1].ewm(halflife=20,min_periods=20).var().iloc[-1])


@pytest.mark.parametrize('arm',['A','B','C'])
def test_unaffected_cards_identical_and_future_rows_ignored(arm):
    c,panels=fixture();c['targets']['horizons']=[5,21]
    asof=c['provenance']['data_cutoff']
    old=nv.forecast(c,panels,None,asof,2000,1111)
    new=alignment.forecast(c,panels,None,asof,2000,1111,arm=arm)
    pd.testing.assert_frame_equal(old,new)
    assert old.attrs['rationale']==new.attrs['rationale']
    c['targets']['horizons']=[1,4]
    before=alignment.forecast(c,panels,None,asof,2000,1111,arm=arm)
    changed=deepcopy(panels)
    changed['rates_daily.parquet']=pd.concat([changed['rates_daily.parquet'],pd.DataFrame(dict(date=[pd.Timestamp(asof)+pd.offsets.BDay(1)],asset=['UST_2Y'],value=[1e9]))])
    after=alignment.forecast(c,changed,None,asof,2000,1111,arm=arm)
    pd.testing.assert_frame_equal(before,after)


def test_short_fhs_is_finite_deterministic_and_uses_shared_path():
    c,panels=fixture();p=v1.prepare(c,panels,c['provenance']['data_cutoff']);cfg=nv.selected_config()
    r=nv.filtered_residuals(p,cfg)
    assert len(r)>20
    draws=nv.sample(p,cfg,2000,1111)
    np.testing.assert_array_equal(draws,nv.sample(p,cfg,2000,1111))
    assert np.isfinite(draws).all()
    assert np.corrcoef(draws[:,0],draws[:,1])[0,1]>.5


def test_normalization_matches_official_cli_on_single_and_joint(tmp_path):
    unit=Path('vendor/track2/units/t2-EXAMPLE-ust-curve-1m')
    for assets in [['UST_2Y'],['UST_2Y','UST_5Y']]:
        c=read_card(unit/'card.toml');c.pop('forecast_spec',None);c['targets']['asset_ids']=assets
        import tomli_w
        card_path=tmp_path/'card.toml';card_path.write_text(tomli_w.dumps(c))
        panels=read_panels(unit/'panels');cutoff=c['provenance']['data_cutoff']
        baseline=m0.distribution(c,panels,cutoff,strict_ratio=True);div=expected_errors(baseline)
        f=nv.forecast(c,panels,None,cutoff,2000,1111)
        from t2eval.final_alignment import matrix
        draws=matrix(f,c);y=baseline.mean+np.sqrt(np.diag(baseline.covariance))
        output=tmp_path/'out/forecast.parquet';write_forecast(c,f,output)
        pd.DataFrame({'asset':assets,'horizon':[21]*len(assets),'value':y}).to_parquet(tmp_path/'answer.parquet')
        expected=normalize(score(card_path,output,tmp_path/'answer.parquet'),div,len(y))
        actual=metric(draws,y,div)
        for k in ['score','normalized_marginal','normalized_joint','normalized_tail']:
            assert actual[k]==pytest.approx(expected[k],rel=1e-12,abs=1e-12)


@pytest.mark.parametrize('fallback',['M0','wide'])
def test_strict_boundary_survives_both_fallbacks(monkeypatch,fallback):
    from test_alignment_review import numeric_fixture
    c,panels=numeric_fixture();cutoff=c['provenance']['data_cutoff']
    c['targets'].update(horizons=[2],target_dates=[str((pd.Timestamp(cutoff)+pd.Timedelta(days=4)).date())])
    def broken(*args,**kwargs): raise RuntimeError('injected numeric fault')
    monkeypatch.setattr(nv,'sample',broken)
    if fallback=='M0':
        expected=m0.forecast(c,panels,None,cutoff,2000,1111,strict_ratio=True)
    else:
        expected=v1._wide_random_walk(c,panels,cutoff,2000,1111,strict_ratio=True)
        monkeypatch.setattr(m0,'forecast',broken)
    actual=alignment.forecast(c,panels,None,cutoff,2000,1111)
    np.testing.assert_array_equal(actual.value,expected.value)
    assert actual.attrs['fallback']==('M0 fallback' if fallback=='M0' else 'last-resort wide random walk')


def test_compatibility_profile_is_available_to_existing_eval_adapter(tmp_path):
    from t2eval.official import run_forecaster
    unit=Path('vendor/track2/units/t2-EXAMPLE-ust-curve-1m')
    out=tmp_path/'forecast.parquet'
    run_forecaster('numeric_alignment',unit,out,n_draws=2000,seed=1111)
    assert score(unit/'card.toml',out)['admissible']
    assert pd.read_parquet(out).draw.nunique()==2000


def test_evaluation_crc_and_text_policy_ignore_ambient_overrides(tmp_path,monkeypatch):
    from t2eval.final_alignment import evaluate_case
    import tomli_w
    c,p=fixture();c['targets']['asset_ids']=['UST_2Y'];c['targets']['horizons']=[1]
    c['text']={'notes':'Elevated crisis risk.'}
    unit=tmp_path/'unit';(unit/'panels').mkdir(parents=True);(unit/'text').mkdir()
    (unit/'card.toml').write_text(tomli_w.dumps(c))
    p['rates_daily.parquet'].to_parquet(unit/'panels/rates_daily.parquet')
    answer=tmp_path/'answer.parquet';pd.DataFrame({'asset':['UST_2Y'],'horizon':[1],'value':[2.]}).to_parquet(answer)
    case={'id':c['task']['id'],'unit':str(unit),'realized':str(answer),'asof':c['provenance']['data_cutoff'],
          'year':2021,'week':'2021-W48','group':'UST_other','cohort':'fixture','shape':'single_asset','split':'development'}
    first=evaluate_case((case,[None],['release'],'current'))[0][0]
    monkeypatch.setenv('QFBENCH_SEED','999');monkeypatch.setenv('TEXT_LAYER_MODE','numeric_only');monkeypatch.setenv('TEXT_LAYER_LAMBDA','0')
    second=evaluate_case((case,[None],['release'],'current'))[0][0]
    for key in ['score','normalized_marginal','normalized_joint','normalized_tail','coverage90','coverage98']:
        assert first[key]==second[key]
