"""Coverage audit: runner failures must not become fabricated model results."""
import hashlib
import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import t2eval.mock_final as runner
from t2eval.mock_house_service import HouseState, atomic_json, replay_response, request_hash


def image_info():
    return {"Os": "linux", "Architecture": "amd64", "Id": "sha256:fixture",
            "Config": {"Labels": {"qfbench2.interface_version": "2.0"}}}


def make_unit(tmp_path, name="unit"):
    unit = tmp_path / name
    (unit / "panels").mkdir(parents=True)
    (unit / "panels/rates.parquet").write_bytes(b"panel bytes")
    (unit / "card.toml").write_text('[task]\nid = "' + name + '"\n[provenance]\ndata_cutoff = "2024-01-01"\n')
    files = [{"path": str(path.relative_to(unit)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
             for path in sorted(unit.rglob("*")) if path.is_file()]
    (unit / "manifest.json").write_text(json.dumps({"files": files}))
    return unit


@pytest.mark.parametrize("invalid", ["hash", "escape", "conflicting_panel", "unlisted"])
def test_manifest_and_panel_conflicts_refused_before_execution(tmp_path, invalid):
    unit = make_unit(tmp_path)
    panel = unit / "panels/rates.parquet"
    manifest = {"files": [{"path": "panels/rates.parquet",
                           "sha256": hashlib.sha256(panel.read_bytes()).hexdigest()},
                          {"path": "card.toml", "sha256": hashlib.sha256((unit / "card.toml").read_bytes()).hexdigest()}]}
    if invalid == "hash":
        manifest["files"][0]["sha256"] = "0" * 64
    elif invalid == "escape":
        manifest["files"][0]["path"] = "../../outside"
    elif invalid == "conflicting_panel":
        (unit / "rates.parquet").write_bytes(b"conflicting root bytes")
        manifest["files"].append({"path": "rates.parquet",
                                   "sha256": hashlib.sha256((unit / "rates.parquet").read_bytes()).hexdigest()})
    else:
        (unit / "unlisted.txt").write_text("bytes absent from the organizer manifest")
    (unit / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match={"hash": "manifest mismatch", "escape": "unsafe manifest path",
                                        "conflicting_panel": "conflicting root",
                                        "unlisted": "unlisted|manifest"}[invalid]):
        runner.stage_unit(unit, tmp_path / "stage")


def install_docker_stubs(monkeypatch, *, oom=False):
    calls = []

    def docker(*args, **kwargs):
        calls.append(args)
        state = {"Running": False, "ExitCode": 137 if oom else 0, "OOMKilled": oom}
        return SimpleNamespace(returncode=0 if oom and args[0] == "inspect" else 1,
                               stdout=json.dumps([{"State": state}]), stderr="")

    monkeypatch.setattr(runner, "docker", docker)
    monkeypatch.setattr(runner, "image_info", lambda *_, **__: image_info())
    return calls


def test_exhausted_platform_clock_does_not_pull_or_start_container(monkeypatch, tmp_path):
    unit = make_unit(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    calls = install_docker_stubs(monkeypatch)

    def forbidden(*_, **__):
        raise AssertionError("an exhausted platform must not start a container")

    monkeypatch.setattr(runner.subprocess, "run", forbidden)
    args = runner.parser().parse_args(["--image", "fixture"])
    row = runner.run_unit(unit, "fixture", work, {"cpus": 1, "memory_bytes": 1024**3},
                          args, pull=True, allowance=0)
    assert row["status"] == "resource_timeout" and row["score"] == 8
    assert not any(call[0] == "pull" for call in calls)
    assert not (work / "unit/input").exists()


def test_missing_manifest_is_harness_error_without_launching_or_scoring(monkeypatch, tmp_path):
    unit = make_unit(tmp_path)
    (unit / "manifest.json").unlink()
    work = tmp_path / "work"
    work.mkdir()
    calls = install_docker_stubs(monkeypatch)

    def forbidden(*_, **__):
        raise AssertionError("invalid organizer input must not launch Docker")

    monkeypatch.setattr(runner.subprocess, "run", forbidden)
    args = runner.parser().parse_args(["--image", "fixture"])
    with pytest.raises(runner.InputError, match="manifest.json"):
        runner.run_unit(unit, "fixture", work, {"cpus": 1, "memory_bytes": 1024**3}, args, pull=True)
    assert not any(call[0] == "pull" for call in calls)
    assert not list(work.rglob("ingestion.json"))


def test_registry_pull_timeout_is_unit_timeout_before_container_launch(monkeypatch, tmp_path):
    unit = make_unit(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    calls = []

    def docker(*args, **kwargs):
        calls.append(args)
        if args[0] == "pull":
            raise subprocess.TimeoutExpired("registry pull", kwargs["timeout"])
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    def forbidden(*_, **__):
        raise AssertionError("failed pull must not launch image")

    monkeypatch.setattr(runner, "docker", docker)
    monkeypatch.setattr(runner.subprocess, "run", forbidden)
    args = runner.parser().parse_args(["--image", "fixture"])
    row = runner.run_unit(unit, "fixture", work, {"cpus": 1, "memory_bytes": 1024**3}, args, pull=True)
    assert row["status"] == "resource_timeout" and row["score"] == 8
    assert row["pull_seconds"] >= 0 and any(call[0] == "rm" for call in calls)
    assert not (work / "unit/runtime.env").exists()


def test_helper_startup_failure_removes_only_created_resources(monkeypatch, tmp_path):
    calls = []

    def docker(*args, **kwargs):
        calls.append(args)
        if args[0] == "run":
            raise subprocess.CalledProcessError(125, ["docker", *args])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner, "docker", docker)
    network = runner.RestrictedNetwork(tmp_path, "helper-fixture")
    with pytest.raises(subprocess.CalledProcessError):
        network.__enter__()
    assert ("rm", "-f", network.house) in calls
    removed = [call[2] for call in calls if call[:2] == ("network", "rm")]
    assert removed == [network.backend, network.network]
    assert not any(call[:2] == ("network", "prune") for call in calls)


@pytest.mark.parametrize("failure", ["startup", "oom"])
def test_runtime_failures_preserve_label_and_destroy_credentials(monkeypatch, tmp_path, failure):
    unit = make_unit(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    calls = install_docker_stubs(monkeypatch, oom=failure == "oom")
    active = []
    restricted = SimpleNamespace(network="eval", activate=lambda *args: active.append(args),
                                 deactivate=lambda: active.clear(), stats=lambda: {"units": {"unit": 2}})

    def execute(*args, **kwargs):
        assert (work / "unit/runtime.env").exists()
        if failure == "startup":
            raise OSError("daemon connection disappeared")
        return SimpleNamespace(returncode=137)

    monkeypatch.setattr(runner.subprocess, "run", execute)
    args = runner.parser().parse_args(["--image", "fixture", "--network", "restricted"])
    row = runner.run_unit(unit, "fixture", work, {"cpus": 1, "memory_bytes": 1024**3}, args,
                          restricted=restricted)
    assert row["status"] == ("resource_oom" if failure == "oom" else "container_crashed")
    assert row["score"] == 8 and row["requests_used"] == 2
    assert not active and not (work / "unit/runtime.env").exists()
    assert any(call[0] == "rm" for call in calls)


def score_row(tmp_path, name="unit", status="pending_score"):
    return {"unit": str(tmp_path / name), "output": str(tmp_path / (name + "-output")),
            "status": status, "score": None if status == "pending_score" else 8.0}


def test_official_organizer_failures_propagate_instead_of_penalizing_image(monkeypatch, tmp_path):
    import t2eval.official as official

    def failed(*_, **__):
        raise RuntimeError("Official scorer failed: {'organizer_failure': 'bad realized grid'}")

    monkeypatch.setattr(official, "score", failed)
    row = score_row(tmp_path)
    with pytest.raises(RuntimeError, match="organizer_failure"):
        runner.score_rows([row], {})
    assert row["score"] is None


def test_unlabeled_success_gate_failure_and_prior_runtime_failure(monkeypatch, tmp_path):
    import t2eval.official as official
    calls = []

    def score(card, forecast, realized):
        calls.append((card.parent.name, realized))
        return {"admissible": card.parent.name == "unlabeled", "scored": False}

    monkeypatch.setattr(official, "score", score)
    rows = [score_row(tmp_path, "unlabeled"), score_row(tmp_path, "bad_schema"),
            score_row(tmp_path, "crashed", "container_crashed")]
    runner.score_rows(rows, {})
    assert calls == [("unlabeled", None), ("bad_schema", None)]
    assert [(r["status"], r["score"]) for r in rows] == [
        ("passed", None), ("schema_invalid", 8.), ("container_crashed", 8.)]


def test_proxy_scoring_calls_existing_normalizer_and_propagates_scale_errors(monkeypatch, tmp_path):
    import t2agent.io as io
    import t2agent.m0 as m0
    import t2eval.official as official
    import t2eval.scales as scales
    payload = {"admissible": True, "marginal_crps": 2., "joint_variogram": 2., "tail_penalty": 2.}
    calls = []
    monkeypatch.setattr(official, "score", lambda *args: payload)
    monkeypatch.setattr(io, "read_card", lambda _: {"provenance": {"data_cutoff": "2024-01-01"},
                                                  "scoring": {"params": {}}})
    monkeypatch.setattr(io, "read_panels", lambda path: calls.append(path) or {})
    monkeypatch.setattr(m0, "distribution", lambda *_: SimpleNamespace(mean=[0.]))
    monkeypatch.setattr(scales, "expected_errors", lambda *_: {"marginal": 2., "joint": 2., "tail": 2.})
    roster = {"unit": {"realized": str(tmp_path / "realized.parquet"), "date_basis": "fixture"}}
    row = score_row(tmp_path)
    runner.score_rows([row], roster)
    assert row["score"] == 1. and row["proxy_available"] and row["date_basis"] == "fixture"
    assert calls == [tmp_path / "unit/panels"]

    def broken_scale(*_):
        raise ValueError("invalid normalization reference")

    monkeypatch.setattr(scales, "expected_errors", broken_scale)
    with pytest.raises(ValueError, match="normalization reference"):
        runner.score_rows([score_row(tmp_path)], roster)


def test_token_rotation_does_not_reset_unit_quota(tmp_path):
    atomic_json(tmp_path / "active.json", {"unit_id": "same", "token": "first", "expires": time.time()+60})
    state = HouseState(tmp_path)
    for _ in range(25):
        assert state.admit("Bearer first", {"model": "house", "messages": []})[0] == 200
    atomic_json(tmp_path / "active.json", {"unit_id": "same", "token": "rotated", "expires": time.time()+60})
    assert state.admit("Bearer first", {"model": "house", "messages": []})[0] == 401
    assert state.admit("Bearer rotated", {"model": "house", "messages": []})[0] == 429
    assert state.stats["units"] == {"same": 25}


def test_replay_ignores_non_object_cache_files_without_hiding_valid_response(tmp_path):
    folder = tmp_path / "unit"
    folder.mkdir()
    (folder / "corrupted.json").write_text("[]")
    params = {"model": "dev", "messages": [], "max_tokens": 4000}
    key = request_hash("unit", "dev", params)
    cached = {"model": "dev", "text": "valid cached reply", "finish_reason": "stop"}
    atomic_json(folder / (key + ".json"), cached)
    assert replay_response(tmp_path, "unit", dict(params, model="house")) == (cached, key)


@pytest.mark.parametrize("tokens", [False, 0, -1, "10", 1.5])
def test_invalid_secondary_completion_limit_never_consumes_budget(tmp_path, tokens):
    atomic_json(tmp_path / "active.json", {"unit_id": "unit", "token": "token", "expires": time.time()+60})
    state = HouseState(tmp_path)
    status, _, _ = state.admit("Bearer token", {"model": "house", "messages": [],
                                               "max_completion_tokens": tokens})
    assert status == 400 and not state.stats["units"]
