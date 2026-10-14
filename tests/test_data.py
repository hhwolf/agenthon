from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from t2eval.data import realized_from_series, target_labels


def test_exact_target_no_nearest_date_substitution():
    s=pd.Series([1.,2.],index=pd.to_datetime(["2024-01-02","2024-01-04"]))
    with pytest.raises(ValueError,match="exact"):
        realized_from_series(s,pd.Timestamp("2024-01-01"),pd.Timestamp("2024-01-03"),"level",2)
    with pytest.raises(ValueError,match="exact"):
        realized_from_series(s,pd.Timestamp("2024-01-01"),pd.Period("2024-01",freq="M"),"level",2)


def test_cumulative_return_excludes_anchor_and_compounds():
    s=pd.Series([.9,.1,-.1],index=pd.bdate_range("2024-01-01",periods=3))
    value=realized_from_series(s,s.index[0],s.index[-1],"log_return",2)
    assert value == pytest.approx(np.log(1.1*.9))


def test_inferred_dates_are_explicitly_labelled():
    c={"provenance":{"data_cutoff":"2024-01-05"},"targets":{"asset_ids":["A"],"horizons":[1]}}
    labels,basis=target_labels(c)
    assert labels["A",1] == pd.Timestamp("2024-01-08")
    assert basis["A",1] == "inferred_bday"


def test_image_context_and_runtime_exclude_eval():
    dockerfile=Path("Dockerfile").read_text()
    assert "COPY t2agent /app/t2agent" in dockerfile
    assert "COPY . " not in dockerfile
    assert Path(".dockerignore").read_text().splitlines()[1] == "**"
    for path in Path("t2agent").glob("*.py"):
        assert "import t2eval" not in path.read_text()
        assert "from t2eval" not in path.read_text()


def test_practice_uses_sibling_and_records_source(tmp_path):
    import json
    import tomli_w
    from t2eval.data import practice
    unit=tmp_path/"units/current"
    (unit/"panels").mkdir(parents=True)
    card={"task":{"id":"current"},"provenance":{"data_cutoff":"2024-01-05"},
          "targets":{"asset_ids":["A"],"horizons":[1],"target_type":"level"}}
    (unit/"card.toml").write_text(tomli_w.dumps(card))
    (unit/"forecast_spec.json").write_text(json.dumps({"targets":card["targets"]}))
    pd.DataFrame({"date":pd.to_datetime(["2024-01-05"]),"asset":["A"],"value":[1.]}).to_parquet(unit/"panels/p.parquet",index=False)
    donors=pd.DataFrame({"panel":["p","p"],"asset":["A","A"],
                         "date":pd.to_datetime(["2024-01-08"]*2),"value":[999.,2.],
                         "source":["current","sibling"],"source_cutoff":pd.to_datetime(["2024-02-01"]*2)})
    cases,unresolved=practice(tmp_path/"units",tmp_path/"eval",donors)
    assert not unresolved and len(cases)==1
    assert pd.read_parquet(cases[0]["realized"]).value.iloc[0] == 2.
    assert cases[0]["provenance"][0]["source"] == "sibling"
    assert cases[0]["date_basis"] == "inferred_bday"
    strict,unresolved=practice(tmp_path/"units",tmp_path/"strict",donors,strict_dates=True)
    assert not strict and len(unresolved)==1
