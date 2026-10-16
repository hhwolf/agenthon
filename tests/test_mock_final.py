import json
import hashlib
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from t2eval.mock_final import (LIMIT, aggregate, compare, host_limits, outcome,
                              output_tree, runtime_environment, select_units, stage_unit, validate_image)


def test_tree_accepts_deepest_valid_file_and_empty_file(tmp_path):
    nested = tmp_path.joinpath(*list("abcdefg"))
    nested.mkdir(parents=True)
    (nested / "file").write_text("hello")
    (tmp_path / "empty").touch()
    tree = output_tree(tmp_path)
    assert tree == {"valid": True, "files": 2, "entries": 9, "bytes": 5, "reason": ""}
    (nested / "h").mkdir()
    assert "8 or more" in output_tree(tmp_path)["reason"]


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "permissions", "large", "sparse", "empty", "too_many", "backslash", "control", "drive"])
def test_invalid_output_trees(tmp_path, kind):
    file = tmp_path / "file"
    if kind != "empty":
        file.write_text("hello")
    if kind == "symlink":
        (tmp_path / "link").symlink_to(file)
    elif kind == "hardlink":
        os.link(file, tmp_path / "link")
    elif kind == "fifo":
        os.mkfifo(tmp_path / "pipe")
    elif kind == "permissions":
        file.chmod(0o1644)
    elif kind in {"large", "sparse"}:
        with file.open("wb") as stream:
            stream.truncate(LIMIT+1 if kind == "large" else LIMIT//2)
    elif kind == "too_many":
        for i in range(256):
            (tmp_path / str(i)).touch()
    elif kind in {"backslash", "control", "drive"}:
        (tmp_path / {"backslash": "a\\b", "control": "a\nb", "drive": "C:data"}[kind]).touch()
    assert not output_tree(tmp_path)["valid"]


def test_total_size_limit_and_directory_entry_limit(tmp_path):
    for i in range(2):
        (tmp_path / str(i)).write_bytes(b"x"*(LIMIT//2+1))
    assert "64 MiB" in output_tree(tmp_path)["reason"]
    for file in tmp_path.iterdir():
        file.unlink()
    for i in range(4097):
        (tmp_path / str(i)).mkdir()
    assert "4096" in output_tree(tmp_path)["reason"]


def test_name_canonicalization_with_virtual_directory(monkeypatch, tmp_path):
    # APFS normalizes Unicode and may fold case; inject scandir names so the
    # Linux rules are still exercised on a Mac rather than skipping those tests.
    info = SimpleNamespace(st_mode=0o100644, st_nlink=1, st_size=1, st_blocks=8)
    class Entries(list):
        def __enter__(self): return self
        def __exit__(self, *_): pass
    def check(names):
        entries = Entries(SimpleNamespace(name=n, path=str(tmp_path / n), stat=lambda **_: info) for n in names)
        monkeypatch.setattr(os, "scandir", lambda _: entries)
        return output_tree(tmp_path)
    assert not check(["Notes", "notes"])["valid"]
    assert not check(["e\u0301"])["valid"]
    assert not check(["bad\udcff"])["valid"]
    assert check(["é"])["valid"]


def test_failure_precedence_and_missing_triplet():
    bad = {"valid": False}
    assert outcome(1, True, True, bad) == "resource_timeout"
    assert outcome(137, False, True, bad) == "resource_oom"
    assert outcome(1, False, False, bad) == "container_crashed"
    assert outcome(0, False, False, bad) == "no_output"
    assert outcome(0, False, False, {"valid": True}, ["forecast.parquet"]) == "no_output"
    assert outcome(0, False, False, {"valid": True}) == "pending_score"


def test_stage_input_creates_panels_and_refuses_answers_or_links(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "rates.parquet").write_bytes(b"panel fixture")
    (source / "card.toml").write_text("fixture")
    (source / "manifest.json").write_text(json.dumps({"manifest_version": "2.0", "files": [
        {"path": file.name, "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}
        for file in source.iterdir()]}))
    dest = tmp_path / "staged"
    assert len(stage_unit(source, dest)) == 64
    assert (dest / "panels/rates.parquet").read_bytes() == b"panel fixture"
    (source / "realized.parquet").touch()
    with pytest.raises(ValueError, match="unsafe input"):
        stage_unit(source, tmp_path / "bad")
    (source / "realized.parquet").unlink()
    (source / "link").symlink_to("card.toml")
    with pytest.raises(ValueError, match="unsafe input"):
        stage_unit(source, tmp_path / "bad2")


def test_limits_environment_and_image_preflight():
    limits = host_limits({"NCPU": 4, "MemTotal": 8*1024**3})
    assert limits["cpus"] == 4 and limits["memory_bytes"] < 8*1024**3
    assert host_limits({"NCPU": 64, "MemTotal": 256*1024**3})["cpus"] == 16
    env = runtime_environment("restricted", "secret", 42)
    assert env["MODEL_ENDPOINT"] == "http://house.internal:8000"
    assert env["MODEL_NAME"] == "house" and env["QFBENCH_SEED"] == "42"
    assert "house" not in env["NO_PROXY"]
    assert runtime_environment("none", "secret", 42)["HTTP_PROXY"] == ""
    info = {"Os": "linux", "Architecture": "amd64", "Config": {"Labels": {"qfbench2.interface_version": "2.0"}}}
    validate_image(info)
    info["Config"]["Volumes"] = {"/output": {}}
    with pytest.raises(ValueError, match="VOLUME"):
        validate_image(info)


def test_summary_does_not_invent_unlabeled_scores_or_include_scoring_time(tmp_path):
    rows = [{"unit_id": str(i), "status": status, "score": score, "proxy_available": proxy,
             "wall_seconds": 220, "pull_seconds": i, "requests_used": i}
            for i, (status, score, proxy) in enumerate([("passed", 1., True), ("passed", None, False),
                                                       ("no_output", 8., False)])]
    summary = aggregate(rows)
    assert summary["mean"] == 4.5 and summary["scored_units"] == 2
    assert summary["proxy_mean"] == 1 and summary["proxy_units"] == 1
    assert summary["caps"] == 1 and summary["requests_used"] == 3
    assert summary["over_half_platform_clock"]
    summary.update(image="digest", ingestion_seconds=660)
    result = compare((summary, rows), (summary, rows), tmp_path)
    assert result["paired_scored_units"] == 2
    assert result["paired_mean_delta_b_minus_a"] == 0


def test_unit_selection_has_all_104_and_exemplar():
    root = Path("vendor/track2/units")
    if not root.exists():
        pytest.skip("vendor not restored")
    assert len(select_units(root, "practice")) == 104
    assert len(select_units(root, "exemplar")) == 1
    assert len(select_units(root, "3")) == 3
    with pytest.raises(ValueError):
        select_units(root, "105")


@pytest.mark.parametrize("timeout", [False, True])
def test_unit_deadline_includes_pull_and_kills_daemon_container(monkeypatch, tmp_path, timeout):
    import t2eval.mock_final as runner
    unit = Path("vendor/track2/units/t2-EXAMPLE-ust-curve-1m").resolve()
    if not unit.exists():
        pytest.skip("vendor not restored")
    now = [100.0]
    calls, execution = [], []
    monkeypatch.setattr(runner.time, "monotonic", lambda: now[0])
    def fake_docker(*args, **kwargs):
        calls.append(args)
        if args[0] == "pull":
            now[0] += 7
        state = {"Running": timeout, "OOMKilled": False, "ExitCode": 0}
        return SimpleNamespace(returncode=0, stdout=json.dumps([{"State": state}]) if args[0] == "inspect" else "", stderr="")
    def fake_run(command, **kwargs):
        execution.append((command, kwargs["timeout"]))
        now[0] += kwargs["timeout"] if timeout else 1
        if timeout:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runner, "docker", fake_docker)
    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(runner, "image_info", lambda *_, **__: {"Os": "linux", "Architecture": "amd64", "Id": "sha256:fixture",
                                                               "Config": {"Labels": {"qfbench2.interface_version": "2.0"}}})
    args = runner.parser().parse_args(["--image", "fixture", "--timeout", "10"])
    row = runner.run_unit(unit, "fixture", tmp_path, {"cpus": 4, "memory_bytes": 1024**3}, args, pull=True)
    assert row["pull_seconds"] == 7
    assert execution[0][1] == 3  # Not a fresh ten seconds after pulling.
    command = execution[0][0]
    assert "--read-only" in command and "--memory-swap" in command and "--pull=never" in command
    assert any(str(x).endswith(":/input:ro") for x in command)
    assert row["wall_seconds"] == (10 if timeout else 8)
    assert not list(tmp_path.rglob("runtime.env"))
    if timeout:
        assert row["status"] == "resource_timeout" and row["score"] == 8
        operations = [c[0] for c in calls]
        assert operations.index("kill") < operations.index("inspect") < operations.index("rm")


@pytest.mark.parametrize("initial_arm,failed_pull", [(True, False), (False, True)])
def test_image_sweep_pulls_target_platform_and_retries_failed_pull(monkeypatch, tmp_path, initial_arm, failed_pull):
    import t2eval.mock_final as runner
    units = [tmp_path / "first", tmp_path / "second"]
    monkeypatch.setattr(runner, "select_units", lambda *_: units)
    monkeypatch.setattr(runner, "image_info", lambda *_: {"Os": "linux", "Architecture": "arm64"} if initial_arm else None)
    monkeypatch.setattr(runner, "docker", lambda *_, **__: SimpleNamespace(stdout=json.dumps(
        {"NCPU": 2, "MemTotal": 8*1024**3, "Architecture": "amd64", "ServerVersion": "fixture"})))
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *_, **__: "fixture\n")
    monkeypatch.setattr(runner, "score_rows", lambda *_: None)
    calls = []
    def unit_run(unit, *_, **kwargs):
        calls.append((kwargs["pull"], kwargs["cached"]))
        failed = failed_pull and len(calls) == 1
        return {"unit_id": unit.name, "status": "resource_timeout" if failed else "passed", "score": 8. if failed else None,
                "proxy_available": False, "requests_used": 0, "pull_seconds": .5, "wall_seconds": 1,
                **({} if failed else {"image_id": "sha256:amd64"})}
    monkeypatch.setattr(runner, "run_unit", unit_run)
    args = runner.parser().parse_args(["--image", "registry/image@sha256:fixture", "--units", "2"])
    runner.run_image(args.image, args, tmp_path / "run", {})
    assert calls == ([(True, False), (True, False)] if failed_pull else [(True, False), (False, True)])


@pytest.mark.parametrize("option,value", [("--timeout", "nan"), ("--timeout", "1801"),
                                         ("--platform-clock", "inf"), ("--chaos-slow", "-1")])
def test_cli_refuses_invalid_deadlines_before_docker(monkeypatch, option, value):
    import t2eval.mock_final as runner
    monkeypatch.setattr(runner, "image_info", lambda *_: pytest.fail("must reject before Docker"))
    with pytest.raises(SystemExit, match="timeouts must be"):
        runner.main(["--image", "fixture", option, value])
