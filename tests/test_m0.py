from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.integrate import quad
from scipy.stats import norm

from t2agent.io import read_card, read_panels, sample_frame, write_forecast
from t2agent.m0 import Distribution, distribution, forecast, horizon_steps, resolve_seed
from t2eval.official import normalize, score
from t2eval.scales import expected_errors

UNITS = Path("vendor/track2/units")


def card(assets=("A",), horizons=(1,), target_type="level"):
    return {"task":{"id":"test-unit"},"provenance":{"data_cutoff":"2024-01-10"},
            "targets":{"asset_ids":list(assets),"horizons":list(horizons),"target_type":target_type}}


def panel(values, dates=None, asset="A"):
    dates = dates if dates is not None else pd.bdate_range("2024-01-01",periods=len(values))
    return pd.DataFrame({"date":pd.to_datetime(dates),"asset":asset,"value":values})


def test_published_worked_example(monkeypatch):
    monkeypatch.delenv("QFBENCH_SEED",raising=False)
    unit = UNITS / "t2-EXAMPLE-ust-curve-1m"
    c = read_card(unit / "card.toml")
    d = distribution(c,read_panels(unit / "panels"),"2024-06-28")
    assert resolve_seed(c,None) == 795546941
    assert d.aligned_rows == 128
    np.testing.assert_equal(d.steps,[21]*4)
    np.testing.assert_allclose(d.covariance.diagonal()**.5,[.0872,.0924,.0905,.1028],atol=.00005)
    expected = expected_errors(d)
    assert expected["marginal"] == pytest.approx(.05260,abs=5e-6)
    assert expected["joint"] == pytest.approx(.1772,abs=5e-5)
    assert expected["tail"] == pytest.approx(.006051,abs=5e-7)


def test_date_intersection_and_gap_anchor():
    c = card(("B","A"),(1,3))
    p = pd.concat([panel([0,1,4,10,100],["2024-01-01","2024-01-02","2024-01-03","2024-01-04","2024-01-10"]),
                   panel([2,4,10,12],["2024-01-01","2024-01-02","2024-01-04","2024-01-10"],"B")])
    # A's Jan10 gap is within 10 days, so a truly long gap is tested separately.
    d = distribution(c,{"p":p},"2024-01-10")
    assert d.aligned_rows == 3  # Jan2, Jan4, Jan10, never positional alignment.
    expected = np.cov([[1,2],[6,6],[90,2]],rowvar=False)
    np.testing.assert_allclose(d.step_covariance,expected)
    # Grid B@1, B@3, A@1, A@3, sorted estimates A,B.
    assert d.covariance[0,1] == pytest.approx(expected[1,1])
    assert d.covariance[0,2] == pytest.approx(expected[1,0])
    assert d.covariance[1,3] == pytest.approx(3*expected[1,0])


def test_transfer_hole_dropped_but_last_level_anchors():
    c = card();c["provenance"]["data_cutoff"]="2024-06-01"
    p = panel([0,1,4,1000],["2024-01-01","2024-01-02","2024-01-03","2024-06-01"])
    d = distribution(c,{"p":p},"2024-06-01")
    assert d.aligned_rows == 2
    assert d.mean[0] == 1002
    assert d.step_covariance[0,0] == 2


def test_returns_are_rows_and_first_row_is_dropped():
    c = card(target_type="log_return")
    p = panel([.09,.01,.02,.03])
    d = distribution(c,{"p":p},"2024-01-10")
    assert d.mean[0] == pytest.approx(.02)
    assert d.step_covariance[0,0] == pytest.approx(.0001)
    with pytest.raises(ValueError,match="tripwire"):
        distribution(c,{"p":panel([.2,.3,.4])},"2024-01-10")


def test_cutoff_trailing_window_sorted_file_precedence():
    c = card(); c["provenance"]["data_cutoff"]="2024-12-31"
    dates = pd.bdate_range("2023-01-01",periods=600)
    p = panel(np.arange(600.)**2,dates)
    d = distribution(c,{"z":panel([1,2,3]),"a":p},"2024-12-31")
    assert len(d.histories["A"]) == 300
    assert d.histories["A"].index[-1] <= pd.Timestamp("2024-12-31")
    p.loc[p.date > "2024-12-31","value"] = 99999999
    np.testing.assert_equal(distribution(c,{"a":p},"2024-12-31").mean,d.mean)


def test_duplicate_and_nonfinite_history_refused():
    p = panel([1,2,3],["2024-01-01","2024-01-01","2024-01-02"])
    with pytest.raises(ValueError,match="duplicated"):
        distribution(card(),{"p":p},"2024-01-10")
    with pytest.raises(ValueError,match="Nonfinite"):
        distribution(card(),{"p":panel([1,np.nan,3])},"2024-01-10")


def test_named_month_beats_ratio_and_respects_publication_lag():
    c = card(horizons=(3,));c["provenance"]["data_cutoff"]="2031-06-05"
    c["forecast_spec"]={"questions":[{"asset":"A","horizon":3,"observation_period":"2031-09"}]}
    p = panel([1,2,4,5],pd.date_range("2031-01-01",periods=4,freq="MS"))
    assert distribution(c,{"p":p},"2031-06-05").steps[0] == 5
    c["targets"]["target_dates"]=["2031-08-01"]
    with pytest.raises(ValueError,match="disagrees"):
        distribution(c,{"p":p},"2031-06-05")


def test_horizon_threshold_and_missing_date_fallback():
    hist = {"A":pd.Series([1.,2.,3.],index=pd.date_range("2024-01-01",periods=3))}
    c = card(horizons=(2,))
    assert horizon_steps(c,hist)[0] == 2
    c["targets"]["target_dates"]=["invalid"]
    assert horizon_steps(c,hist)[0] == 2
    c["targets"]["target_dates"]=["2024-01-06"]
    assert horizon_steps(c,hist)[0] == 2 # ratio 1.5
    c["targets"]["target_dates"]=["2024-01-07"]
    assert horizon_steps(c,hist)[0] == 4 # ratio exactly 2


@pytest.mark.parametrize("name,steps",[
    ("t2-F1-cpi-glidepath-2023",[8,9]), ("t2-F1-sahm-watch-2024",[7,8]),
    ("t2-F4-covid-nfp-2020",[2]), ("t2-F4-cpi-vintage-2022",[2]),
])
def test_current_monthly_practice_inputs(name,steps):
    unit=UNITS/name;c=read_card(unit/"card.toml")
    d=distribution(c,read_panels(unit/"panels"),c["provenance"]["data_cutoff"])
    np.testing.assert_equal(d.steps,steps)


def model(mean,cov):
    cov=np.asarray(cov,dtype=float)
    return Distribution(np.asarray(mean,dtype=float),cov,np.linalg.cholesky(cov),np.ones(len(mean)),{},np.array([]),np.array([]),0,False)


def test_expected_errors_single_cell_and_zero_pair():
    scales=expected_errors(model([0],[[.01]]))
    assert scales["marginal"] == pytest.approx(.1/np.sqrt(np.pi))
    assert scales["tail"] == pytest.approx(.00648939,abs=1e-8)
    assert scales["joint"] == 1


@pytest.mark.parametrize("delta",[0,.4,10.,200.])
def test_joint_divisor_against_independent_integration(delta):
    d=model([delta,0],[[.6,.1],[.1,.6]]) # difference variance 1
    centre=np.sqrt(delta) if delta else 0
    # Centre the integrand before squaring to keep quadrature stable at large delta.
    f=lambda z: np.sqrt(abs(delta+z))-centre
    points=sorted(set([-12.,12.]+([-delta] if -12 < -delta < 12 else [])))
    m=sum(quad(lambda z:f(z)*norm.pdf(z),a,b,epsabs=1e-11)[0] for a,b in zip(points,points[1:]))
    second=sum(quad(lambda z:f(z)**2*norm.pdf(z),a,b,epsabs=1e-11)[0] for a,b in zip(points,points[1:]))
    assert expected_errors(d)["joint"] == pytest.approx(2*(second-m*m),rel=2e-7)


def test_seed_and_triplet_reproducibility(tmp_path,monkeypatch):
    c=card();p={"p":panel([1,2,4,3])}
    monkeypatch.setenv("QFBENCH_SEED","24")
    a=forecast(c,p,None,"2024-01-10",500,None)
    b=forecast(c,p,None,"2024-01-10",500,24)
    pd.testing.assert_frame_equal(a,b)
    write_forecast(c,a,tmp_path/"a/forecast.parquet")
    write_forecast(c,b,tmp_path/"b/forecast.parquet")
    for name in ("forecast.parquet","forecast_meta.json","forecast_rationale.md"):
        assert (tmp_path/"a"/name).read_bytes() == (tmp_path/"b"/name).read_bytes()
    assert a.draw.dtype == np.dtype("int32")
    assert a.horizon.dtype == np.dtype("int32")
    assert not np.array_equal(a.value,forecast(c,p,None,"2024-01-10",500,25).value)


def test_official_score_and_failure_retained(tmp_path):
    unit=UNITS/"t2-EXAMPLE-ust-curve-1m";c=read_card(unit/"card.toml")
    p=read_panels(unit/"panels");d=distribution(c,p,c["provenance"]["data_cutoff"])
    frame=forecast(c,p,None,c["provenance"]["data_cutoff"],500,1)
    out=tmp_path/"output/forecast.parquet";write_forecast(c,frame,out)
    y=sample_frame(c,d.mean[None,:]).drop(columns="draw")
    realized=tmp_path/"realized.parquet";y.to_parquet(realized,index=False)
    payload=score(unit/"card.toml",out,realized)
    assert payload["admissible"] and len(payload["gates"]) == 4
    assert normalize(payload,expected_errors(d),4)["score"] < 1
    out.with_name("forecast_rationale.md").write_text(" ")
    failed=score(unit/"card.toml",out,realized)
    assert normalize(failed,expected_errors(d),4) == {"score":8.,"unclipped":8.,"failed":True}


def test_single_cell_weights():
    payload={"admissible":True,"marginal_crps":1,"joint_variogram":0,"tail_penalty":1}
    assert normalize(payload,{"marginal":1,"joint":1,"tail":1},1)["score"] == 1
    payload["marginal_crps"]=100
    assert normalize(payload,{"marginal":1,"joint":1,"tail":1},1)["score"] == 8
