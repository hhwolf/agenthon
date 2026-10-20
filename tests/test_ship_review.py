"""Boundary and recovery checks for the local measurement workflow."""
import json
import sys
from types import ModuleType

import numpy as np
import pandas as pd
import pytest
import tomli_w

from t2agent.io import sample_frame, write_forecast
from t2agent.m0 import cell_metadata
from t2eval.data import build_union, panel_frames, realized_from_series
from t2eval.official import run_forecaster, score


def make_unit(root, name="unit", cutoff="2024-01-05", values=(1., 2., 3.)):
    unit = root / name
    (unit / "panels").mkdir(parents=True)
    card = {"task": {"id": name}, "provenance": {"data_cutoff": cutoff},
            "metadata": {"category": "F1", "asset_panel": "p"},
            "targets": {"asset_ids": ["A"], "horizons": [1], "target_type": "level"}}
    (unit / "card.toml").write_text(tomli_w.dumps(card))
    (unit / "forecast_spec.json").write_text(json.dumps({"targets": card["targets"]}))
    panel = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=len(values)),
                          "asset": "A", "value": values})
    panel.to_parquet(unit / "panels/p.parquet", index=False)
    return unit, card


@pytest.mark.parametrize("problem", ["too_few", "missing_cell", "duplicate", "nonfinite",
                                     "fractional_draw", "blank_rationale"])
def test_writer_rejects_invalid_triplet_without_publishing(tmp_path, problem):
    card = {"task": {"id": "test"}, "provenance": {"data_cutoff": "2024-01-05"},
            "targets": {"asset_ids": ["A", "B"], "horizons": [1]}}
    frame = sample_frame(card, np.ones((200, 2)))
    rationale = "Numeric baseline with a fixed seed."
    if problem == "too_few":
        frame = frame[frame.draw < 199]
    elif problem == "missing_cell":
        frame = frame.iloc[:-1]
    elif problem == "duplicate":
        frame = pd.concat([frame.iloc[:-1], frame.iloc[[0]]], ignore_index=True)
    elif problem == "nonfinite":
        frame.loc[0, "value"] = np.inf
    elif problem == "fractional_draw":
        frame = frame.astype({"draw": "float64"})
        frame.loc[0, "draw"] = 0.5
    else:
        rationale = " "
    out = tmp_path / "out/forecast.parquet"
    with pytest.raises(ValueError):
        write_forecast(card, frame, out, rationale)
    assert not out.exists()
    assert not out.with_name("forecast_meta.json").exists()


def test_union_latest_vintage_and_content_change_invalidate_cache(tmp_path):
    root = tmp_path / "units"
    make_unit(root, "early", "2024-01-05", (1., 2., 3.))
    late, _ = make_unit(root, "late", "2024-01-06", (1., 2., 4.))
    out = tmp_path / "union"
    donors, meta = build_union(root, out)
    assert meta["source_rows"] == 6 and meta["union_rows"] == 3
    assert meta["conflicting_keys"] == {"p": 1}
    assert panel_frames(donors)["p.parquet"].value.tolist() == [1., 2., 4.]
    cached, cached_meta = build_union(root, out)
    # Parquet may change timestamp precision; donor values and ordering are the contract.
    pd.testing.assert_frame_equal(cached, donors, check_dtype=False)
    assert cached_meta == meta
    path = late / "panels/p.parquet"
    changed = pd.read_parquet(path)
    changed.loc[2, "value"] = 5.
    changed.to_parquet(path, index=False)
    refreshed, refreshed_meta = build_union(root, out)
    assert refreshed_meta["input_sha256"] != meta["input_sha256"]
    assert panel_frames(refreshed)["p.parquet"].value.tolist() == [1., 2., 5.]


@pytest.mark.parametrize("problem", ["post_cutoff", "duplicate", "nonfinite"])
def test_union_refuses_unsafe_donor_rows(tmp_path, problem):
    root = tmp_path / "units"
    unit, _ = make_unit(root)
    path = unit / "panels/p.parquet"
    panel = pd.read_parquet(path)
    if problem == "post_cutoff":
        panel.loc[2, "date"] = pd.Timestamp("2024-01-06")
    elif problem == "duplicate":
        panel.loc[2, "date"] = panel.loc[1, "date"]
    else:
        panel.loc[2, "value"] = np.nan
    panel.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="post-cutoff|Ambiguous/nonfinite"):
        build_union(root, tmp_path / "union")
    assert not (tmp_path / "union/donors.parquet").exists()


def test_custom_forecaster_receives_numeric_only_inputs_and_writes_contract(tmp_path, monkeypatch):
    unit, card = make_unit(tmp_path / "units")
    plugin = ModuleType("ship_test_plugin")
    calls = []

    def forecast(received_card, panels, text_dir, asof, n_draws, seed):
        calls.append((received_card, panels, text_dir, asof, n_draws, seed))
        frame = sample_frame(received_card, np.full((n_draws, 1), 42.))
        frame.attrs["rationale"] = "Fixed diagnostic forecast."
        return frame

    plugin.forecast = forecast
    monkeypatch.setitem(sys.modules, plugin.__name__, plugin)
    out = tmp_path / "out/forecast.parquet"
    run_forecaster("ship_test_plugin:forecast", unit, out, 200, 7, text=False)
    assert len(calls) == 1
    assert calls[0][0]["targets"] == card["targets"]
    assert set(calls[0][1]) == {"p.parquet"}
    assert calls[0][2:] == (None, "2024-01-05", 200, 7)
    assert pd.read_parquet(out).value.tolist() == [42.] * 200
    assert json.loads(out.with_name("forecast_meta.json").read_text())["n_draws"] == 200
    assert out.with_name("forecast_rationale.md").read_text().strip()


def test_eval_retains_plugin_failure_and_continues_roster(tmp_path, monkeypatch):
    from t2eval import cli

    root = tmp_path / "units"
    make_unit(root, "a-fails")
    make_unit(root, "b-passes")
    seen = []

    def run(name, unit, out, *args, **kwargs):
        seen.append(unit.name)
        if unit.name == "a-fails":
            raise SystemExit("deliberate plugin failure")
        out.parent.mkdir(parents=True)

    monkeypatch.setattr(cli, "run_forecaster", run)
    monkeypatch.setattr(cli, "score", lambda *args: {"admissible": True, "gates": []})
    monkeypatch.setattr(cli.subprocess, "check_output", lambda *args, **kwargs: "test-revision\n")
    work = tmp_path / "eval"
    assert cli.main(["admissibility", "--units", str(root), "--work", str(work)]) == 1
    assert seen == ["a-fails", "b-passes"]
    summary_path, = (work / "runs").glob("*/summary.json")
    summary = json.loads(summary_path.read_text())
    assert summary["cards"] == 2 and summary["failed"] == 1
    rows = pd.read_csv(summary_path.with_name("cards.csv"))
    assert rows.loc[0, "score"] == 8.
    assert "SystemExit: deliberate plugin failure" in rows.loc[0, "error"]
    assert not rows.loc[1, "failed"]


def test_eval_run_directory_separates_text_modes(tmp_path, monkeypatch):
    """numeric-only and card-notes runs once shared one directory and overwrote each other."""
    from t2eval import cli

    root = tmp_path / "units"
    make_unit(root, "a-unit")
    seen = []

    def run(name, unit, out, *args, **kwargs):
        seen.append(cli.os.environ.get("TEXT_LAYER_MODE"))
        out.parent.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(cli, "run_forecaster", run)
    monkeypatch.setattr(cli, "score", lambda *args: {"admissible": True, "gates": []})
    monkeypatch.setattr(cli.subprocess, "check_output", lambda *args, **kwargs: "test-revision\n")
    monkeypatch.setenv("MODEL_TOKEN", "secret-token-value")
    work = tmp_path / "eval"
    directories = {}
    for mode in ["numeric_only", "card_notes_only", "numeric_only"]:
        monkeypatch.setenv("TEXT_LAYER_MODE", mode)
        before = set((work / "runs").glob("*")) if (work / "runs").exists() else set()
        assert cli.main(["admissibility", "--units", str(root), "--work", str(work),
                         "--forecaster", "numeric_v1_1"]) == 0
        new = set((work / "runs").glob("*")) - before
        directories.setdefault(mode, new.pop() if new else directories.get(mode))
    assert seen == ["numeric_only", "card_notes_only", "numeric_only"]
    assert directories["numeric_only"] != directories["card_notes_only"]
    assert len(list((work / "runs").glob("*"))) == 2  # same mode reuses its own directory
    summary = json.loads((directories["card_notes_only"] / "summary.json").read_text())
    assert summary["metadata"]["output_env"]["TEXT_LAYER_MODE"] == "card_notes_only"
    assert summary["metadata"]["output_env"]["MODEL_TOKEN_set"] is True
    assert "secret-token-value" not in json.dumps(summary)

    monkeypatch.setenv("TEXT_LAYER_MODE", "card_notes_only")
    monkeypatch.setenv("TEXT_LAYER_LAMBDA", "1.0")
    assert cli.main(["admissibility", "--units", str(root), "--work", str(work),
                     "--forecaster", "numeric_v1_1"]) == 0
    assert len(list((work / "runs").glob("*"))) == 3  # lambda changes output, so it changes identity


@pytest.mark.parametrize("values,dates,message", [
    ([.1, .2, .3], ["2024-01-01", "2024-01-02", "2024-01-12"], "Incomplete"),
    ([.1, .2, -1.], ["2024-01-01", "2024-01-02", "2024-01-03"], "Invalid simple"),
])
def test_realized_returns_reject_holes_and_total_loss(values, dates, message):
    series = pd.Series(values, index=pd.to_datetime(dates))
    with pytest.raises(ValueError, match=message):
        realized_from_series(series, series.index[0], series.index[-1], "log_return", 2)


def test_conflicting_grid_metadata_cannot_override_the_card():
    card = {"targets": {"asset_ids": ["A"], "horizons": [1], "target_dates": ["2024-01-08"]},
            "forecast_spec": {"questions": [{"asset": "A", "horizon": 1,
                                                "target_date": "2024-01-09"}]}}
    with pytest.raises(ValueError, match="Conflicting target_dates"):
        cell_metadata(card, "target_dates", "target_date")


def test_official_scorer_process_error_is_not_treated_as_a_score(tmp_path, monkeypatch):
    from t2eval import official

    def fail(args):
        print(json.dumps({"error": "invalid invocation"}))
        return 2

    monkeypatch.setattr(official.scoring, "_main", fail)
    with pytest.raises(RuntimeError, match="Official scorer failed"):
        score(tmp_path / "card.toml", tmp_path / "forecast.parquet")
