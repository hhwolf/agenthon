"""Run immutable images against the public Final contract; score local proxies.

This is an emulator of the pinned public contract, not CodaBench's private
infrastructure. Scoring delegates to t2eval.official and the existing M0 scales.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import stat
import subprocess
import time
import unicodedata
import uuid
from collections import Counter
from pathlib import Path

from .mock_house_service import ORIGIN, atomic_json

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 64 * 1024**2
REQUIRED = ("forecast.parquet", "forecast_meta.json", "forecast_rationale.md")
DEFAULT_HELPER_BASE = "python:3.13-slim-bookworm"
SOURCE_HASHES = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
    "t2eval/mock_final.py", "t2eval/mock_house_service.py", "tests/mock_house.py",
    "t2eval/official.py", "t2eval/scales.py", "t2agent/m0.py")}


class InputError(ValueError):
    """Invalid organizer/local inputs are harness faults, never image failures."""


def output_tree(path: Path) -> dict:
    """Inspect every entry using lstat, never follow links; fail closed."""
    result = {"valid": False, "files": 0, "entries": 0, "bytes": 0, "reason": ""}
    seen = set()

    def walk(folder, depth=0):
        with os.scandir(folder) as entries:
            for entry in entries:
                rel = Path(entry.path).relative_to(path)
                name = entry.name
                name.encode("utf-8", errors="strict")
                if (unicodedata.normalize("NFC", name) != name or "\\" in name
                        or any(unicodedata.category(c) == "Cc" for c in name)
                        or (depth == 0 and re.match(r"^[A-Za-z]:", name))):
                    raise ValueError(f"invalid path name: {str(rel)!r}")
                canonical = unicodedata.normalize("NFC", str(rel)).casefold()
                if canonical in seen:
                    raise ValueError(f"case/Unicode path collision: {str(rel)!r}")
                seen.add(canonical)
                result["entries"] += 1
                if result["entries"] > 4096:
                    raise ValueError("more than 4096 files and folders")
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    raise ValueError(f"symlink: {str(rel)!r}")
                if stat.S_ISDIR(info.st_mode):
                    if depth + 1 >= 8:
                        raise ValueError("directory nested 8 or more levels")
                    walk(entry.path, depth + 1)
                elif stat.S_ISREG(info.st_mode):
                    result["files"] += 1
                    result["bytes"] += info.st_size
                    if info.st_nlink > 1:
                        raise ValueError(f"hardlink: {str(rel)!r}")
                    if info.st_mode & 0o7000:
                        raise ValueError(f"special permission bits: {str(rel)!r}")
                    if result["files"] > 256:
                        raise ValueError("more than 256 files")
                    if info.st_size > LIMIT or result["bytes"] > LIMIT:
                        raise ValueError("file or total bytes exceed 64 MiB")
                    if info.st_size > 64 * info.st_blocks * 512:
                        raise ValueError(f"heavily sparse file: {str(rel)!r}")
                else:
                    raise ValueError(f"special file: {str(rel)!r}")

    try:
        if path.is_symlink() or not path.is_dir():
            raise ValueError("output is not a regular directory")
        walk(path)
        if not result["files"]:
            raise ValueError("no files")
        result["valid"] = True
    except (OSError, ValueError, UnicodeError) as exc:
        result["reason"] = str(exc)
    return result


def outcome(exit_code, timed_out, oom, tree, missing=()):
    if timed_out:
        return "resource_timeout"
    if oom:
        return "resource_oom"
    if exit_code != 0:
        return "container_crashed"
    if not tree["valid"] or missing:
        return "no_output"
    return "pending_score"


def select_units(root: Path, selection: str) -> list[Path]:
    from .data import units
    available = units(root, exemplar=True)
    if selection == "practice":
        selected = available  # Explicitly all 103 practice units plus exemplar.
    elif selection == "exemplar":
        selected = [p for p in available if p.name.startswith("t2-EXAMPLE-")]
    elif selection.isdecimal() and int(selection) > 0:
        if int(selection) > len(available):
            raise ValueError(f"requested {selection} units; only {len(available)} available")
        selected = available[:int(selection)]
    else:
        raise ValueError("UNITS must be practice, exemplar, or a positive count")
    if not selected:
        raise ValueError("no units selected; restore vendor/track2 first")
    return selected


def stage_unit(source: Path, destination: Path) -> str:
    try:
        return _stage_unit(source, destination)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise InputError(str(exc)) from exc


def _stage_unit(source: Path, destination: Path) -> str:
    from qfbench2_common.manifest import verify_manifest
    # Public units only. Refuse answers/links rather than silently staging them.
    for file in source.rglob("*"):
        if (file.is_symlink() or "realized" in file.name.lower() or file.name == "reference"
                or not (file.is_file() or file.is_dir())):
            raise ValueError(f"unsafe input entry: {file}")
    manifest = source / "manifest.json"
    metadata = json.loads(manifest.read_text())
    errors = verify_manifest(source, metadata)
    if errors:
        raise ValueError("input manifest mismatch: " + "; ".join(errors))
    expected = {entry["path"] for entry in metadata["files"]} | {"manifest.json"}
    present = {str(file.relative_to(source)) for file in source.rglob("*") if file.is_file()}
    if present - expected:
        raise ValueError(f"input manifest contains unlisted files: {sorted(present-expected)}")
    shutil.copytree(source, destination)
    panels = destination / "panels"
    panels.mkdir(exist_ok=True)
    for file in destination.glob("*.parquet"):
        if (panels / file.name).exists():
            if file.read_bytes() != (panels / file.name).read_bytes():
                raise ValueError("conflicting root and panels inputs")
        else:
            shutil.copy2(file, panels / file.name)
    if not list(panels.glob("*.parquet")):
        raise ValueError("staged input has no panels")
    digest = hashlib.sha256()
    for file in sorted(destination.rglob("*")):
        if file.is_file():
            digest.update(str(file.relative_to(destination)).encode())
            digest.update(hashlib.sha256(file.read_bytes()).digest())
    return digest.hexdigest()


def docker(*args, timeout=60, check=True, env=None):
    return subprocess.run(["docker", *map(str, args)], text=True, capture_output=True,
                          timeout=timeout, check=check, env=env)


def image_info(image, timeout=60):
    result = docker("image", "inspect", image, check=False, timeout=timeout)
    return json.loads(result.stdout)[0] if result.returncode == 0 else None


def validate_image(info):
    if info["Os"] != "linux" or info["Architecture"] != "amd64":
        raise ValueError("image must contain linux/amd64")
    if info["Config"].get("Volumes"):
        raise ValueError("Final refuses Docker VOLUME declarations")
    if (info["Config"].get("Labels") or {}).get("qfbench2.interface_version") != "2.0":
        raise ValueError("image lacks qfbench2.interface_version=2.0")


def host_limits(info):
    # Keep room for the Docker daemon and the local proxy helpers.
    return {"cpus": min(16, info["NCPU"]), "memory_bytes": min(128 * 1024**3, int(info["MemTotal"] * .8)),
            "tmpfs_bytes": LIMIT, "platform": "linux/amd64"}


def build_image(context: Path, tag: str, log: Path, *extra):
    env = os.environ.copy()
    plugin = Path("/opt/homebrew/lib/docker/cli-plugins/docker-buildx")
    if plugin.exists():
        config = context / "docker-config"
        (config / "cli-plugins").mkdir(parents=True, exist_ok=True)
        link = config / "cli-plugins/docker-buildx"
        if not link.exists():
            link.symlink_to(plugin)
        env["DOCKER_HOST"] = env.get("DOCKER_HOST") or docker("context", "inspect", "--format", "{{.Endpoints.docker.Host}}").stdout.strip()
        env["DOCKER_CONFIG"] = str(config)
    result = docker("buildx", "build", "--platform", "linux/amd64", "--load", "-t", tag, *extra, context, timeout=600, env=env)
    log.write_text(result.stdout + result.stderr)
    return image_info(tag)["Id"]


def build_helper(work: Path, base=DEFAULT_HELPER_BASE):
    context = work / "helper-build"
    context.mkdir()
    for source in [ROOT / "t2eval/mock_house_service.py", ROOT / "tests/mock_house.py"]:
        shutil.copy2(source, context / source.name)
    (context / "Dockerfile").write_text(f"FROM {base}\nWORKDIR /service\nCOPY *.py ./\n"
                                       'ENTRYPOINT ["python", "-u", "/service/mock_house_service.py"]\n')
    return build_image(context, "t2-mock-house:" + uuid.uuid4().hex[:12], work / "helper-build.log")


class RestrictedNetwork:
    def __init__(self, work: Path, helper: str, mode="canned", replay_dir=None, timeout_delay=120, slow_delay=1):
        self.work, self.helper, self.mode, self.replay_dir = work, helper, mode, replay_dir
        self.timeout_delay, self.slow_delay = timeout_delay, slow_delay
        self.prefix = "t2mf-" + uuid.uuid4().hex[:12]
        self.network = self.prefix + "-eval"
        self.backend = self.prefix + "-backend"
        self.house, self.proxy = self.prefix + "-house", self.prefix + "-proxy"
        self.state = work / "house-state"
        self.state.mkdir(mode=0o700)
        self.created_networks, self.created_containers = [], []

    def __enter__(self):
        try:
            for name in [self.network, self.backend]:
                docker("network", "create", "--internal", name)
                self.created_networks.append(name)
            args = ["run", "-d", "--read-only", "--cpus=.5", "--memory=256m", "--memory-swap=256m",
                    "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m", "--network", self.backend]
            house_args = [*args, "--name", self.house, "--network-alias", "house", "-v", f"{self.state}:/state"]
            if self.replay_dir:
                house_args += ["-v", f"{self.replay_dir.resolve()}:/replay:ro"]
            self.created_containers.append(self.house)
            docker(*house_args, self.helper, "house", "--mode", self.mode, "--timeout-delay", self.timeout_delay,
                   "--slow-delay", self.slow_delay)
            self.created_containers.append(self.proxy)
            docker(*args, "--name", self.proxy, self.helper, "proxy")
            docker("network", "connect", "--alias", "proxy", self.network, self.proxy)
            # A local socket readiness check inside each helper; no extra HTTP API.
            for container, port in [(self.house, 8000), (self.proxy, 3128)]:
                docker("exec", container, "python", "-c",
                       f"import socket,time\nfor i in range(50):\n try:\n  socket.create_connection(('127.0.0.1',{port}),.2).close();break\n except OSError: time.sleep(.1)\nelse: raise SystemExit('service not ready')")
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def activate(self, unit_id, token, seconds):
        atomic_json(self.state / "active.json", {"unit_id": unit_id, "token": token, "expires": time.time() + max(0, seconds)})

    def deactivate(self):
        atomic_json(self.state / "active.json", {"unit_id": "expired", "token": secrets.token_urlsafe(32), "expires": 0})

    def stats(self):
        path = self.state / "stats.json"
        return json.loads(path.read_text()) if path.exists() else {"units": {}, "events": []}

    def __exit__(self, *_):
        for name in reversed(self.created_containers):
            docker("rm", "-f", name, check=False)
        for name in reversed(self.created_networks):
            docker("network", "rm", name, check=False)
        (self.state / "active.json").unlink(missing_ok=True)


def runtime_environment(network, token, seed):
    proxy = "http://proxy:3128" if network == "restricted" else ""
    return {"HTTP_PROXY": proxy, "HTTPS_PROXY": proxy, "http_proxy": proxy, "https_proxy": proxy,
            "ALL_PROXY": "", "all_proxy": "", "NO_PROXY": "localhost,127.0.0.1,::1",
            "no_proxy": "localhost,127.0.0.1,::1", "MODEL_ENDPOINT": ORIGIN,
            "MODEL_TOKEN": token, "MODEL_NAME": "house", "QFBENCH_NETWORK": network, "QFBENCH_SEED": str(seed)}


def run_unit(unit, image, work, limits, args, *, restricted=None, pull=False, cached=False, allowance=None):
    from t2agent.io import read_card
    from t2agent.m0 import resolve_seed
    started = time.monotonic()
    budget = min(args.timeout, args.platform_clock if allowance is None else max(0, allowance))
    deadline = started + budget
    card = read_card(unit / "card.toml")
    row = {"unit_id": card["task"]["id"], "unit": str(unit), "network": args.network,
           "house_mode": args.house_mode, "seed": resolve_seed(card, args.seed), "pull_seconds": 0.0,
           "image_cached_before": cached, "requests_used": 0, "exit_code": None,
           "timed_out": False, "oom_killed": False, "score": None, "reason": ""}
    folder = work / unit.name
    folder.mkdir()
    output = folder / "output"
    output.mkdir(mode=0o777)
    output.chmod(0o777)  # Permit images that correctly run as a non-root user.
    envfile = folder / "runtime.env"
    name = "t2mf-unit-" + uuid.uuid4().hex[:16]
    state = {}
    try:
        if budget <= 0:
            raise subprocess.TimeoutExpired("platform clock", 0)
        row["input_sha256"] = stage_unit(unit, folder / "input")
        token = secrets.token_urlsafe(32)
        if restricted:
            restricted.activate(row["unit_id"], token, deadline-time.monotonic())
        envfile.touch(mode=0o600)
        envfile.write_text("".join(f"{k}={v}\n" for k, v in runtime_environment(args.network, token, row["seed"]).items()))
        if pull:
            pull_start = time.monotonic()
            try:
                pulled = docker("pull", "--platform", "linux/amd64", image, timeout=max(.001, deadline-time.monotonic()))
                (folder / "pull.log").write_text(pulled.stdout + pulled.stderr)
            finally:
                row["pull_seconds"] = time.monotonic() - pull_start
        info = image_info(image, timeout=max(.001, deadline-time.monotonic()))
        if info is None:
            raise ValueError("image not available after pull")
        validate_image(info)
        row["image_id"] = info["Id"]
        row["setup_seconds"] = time.monotonic() - started
        command = ["docker", "run", "--name", name, "--platform", "linux/amd64", "--pull=never",
                   "--cpus", str(limits["cpus"]), "--memory", str(limits["memory_bytes"]),
                   "--memory-swap", str(limits["memory_bytes"]), "--read-only",
                   "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", "--network", restricted.network if restricted else "none",
                   "--env-file", str(envfile), "-v", f"{folder / 'input'}:/input:ro", "-v", f"{output}:/output",
                   image, "forecast", "--panels", "/input/panels", "--text", "/input/text",
                   "--asof", str(card["provenance"]["data_cutoff"]), "--out", "/output/forecast.parquet"]
        # Credentials are in a private ephemeral env-file, never in argv/report.
        with (folder / "container.log").open("w") as log:
            execution_start = time.monotonic()
            try:
                process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                         timeout=max(.001, deadline-time.monotonic()))
                row["exit_code"] = process.returncode
            finally:
                row["execution_seconds"] = time.monotonic() - execution_start
    except subprocess.TimeoutExpired:
        row["timed_out"], row["reason"] = True, "unit or remaining platform deadline exceeded"
    except InputError:
        raise
    except (subprocess.CalledProcessError, ValueError, OSError) as exc:
        # Input/staging and Docker errors remain visible; never manufacture a pass.
        row["reason"] = f"{type(exc).__name__}: {exc}"
    finally:
        if row["timed_out"]:
            # A timed-out Docker CLI does not stop the daemon's container.
            docker("kill", name, check=False, timeout=15)
        inspection = docker("inspect", name, check=False)
        if inspection.returncode == 0:
            state = json.loads(inspection.stdout)[0]["State"]
            row["oom_killed"] = bool(state.get("OOMKilled"))
            if not state.get("Running"):
                row["exit_code"] = state.get("ExitCode", row["exit_code"])
        # Kill before reading output, including when the Docker client timed out.
        docker("rm", "-f", name, check=False)
        envfile.unlink(missing_ok=True)
        if restricted:
            restricted.deactivate()
            row["requests_used"] = restricted.stats()["units"].get(row["unit_id"], 0)
    tree = output_tree(output)
    row["output_tree"] = tree
    missing = [name for name in REQUIRED if not (output / name).is_file()]
    row["status"] = outcome(row["exit_code"], row["timed_out"], row["oom_killed"], tree, missing)
    if row["status"] != "pending_score":
        row["score"] = 8.0
        row["reason"] = row["reason"] or tree["reason"] or ("missing: " + ", ".join(missing) if missing else "nonzero container exit")
    row["wall_seconds"] = time.monotonic() - started
    row["output"] = str(output)
    atomic_json(folder / "ingestion.json", row)
    return row


def proxy_roster(args):
    if args.no_proxy_scores:
        return {}
    if args.proxy_roster:
        cases = json.loads(args.proxy_roster.read_text())
    else:
        # Reuse restored Phase 1 provenance; otherwise regenerate using existing code.
        archived = ROOT / ".eval/runs/eval-practice-m0-b158bfdafa1a/roster.json"
        if archived.exists() and args.units_root.resolve() == ROOT / "vendor/track2/units":
            cases = json.loads(archived.read_text())
        else:
            from .data import build_union, practice
            donors, _ = build_union(args.units_root, ROOT / ".eval/union")
            cases, _ = practice(args.units_root, ROOT / ".eval/practice", donors)
    roster = {}
    for row in cases:
        path = Path(row["realized"])
        if not path.is_absolute():
            path = ROOT / path
        if not path.is_file():
            raise ValueError(f"missing proxy label {path}; restore .eval per reports/EVALUATION_DATA.md")
        roster[Path(row["unit"]).name] = dict(row, realized=str(path))
    return roster


def score_rows(rows, roster):
    from t2agent.io import read_card, read_panels
    from t2agent.m0 import distribution
    from .official import score, normalize
    from .scales import expected_errors
    for row in rows:
        unit, out = Path(row["unit"]), Path(row["output"])
        proxy = roster.get(unit.name)
        row["proxy_available"] = bool(proxy)
        row["date_basis"] = proxy["date_basis"] if proxy else "unresolved"
        if row["status"] != "pending_score":
            continue
        # Official gates return admissible=false for malformed participant files.
        # Raised exceptions signal harness/organizer faults, not an image failure.
        verdict = score(unit / "card.toml", out / "forecast.parquet", Path(proxy["realized"]) if proxy else None)
        row["official"] = verdict
        if not verdict.get("admissible"):
            row.update(status="schema_invalid", score=8.0, reason="official admissibility gate failed")
            continue
        row["status"] = "passed"
        if proxy:
            card = read_card(unit / "card.toml")
            if card["scoring"]["params"].get("tail_metric", "pinball") != "pinball":
                raise ValueError("M0 expected tail error is defined for pinball only")
            model = distribution(card, read_panels(unit / "panels"), str(card["provenance"]["data_cutoff"]))
            divisors = expected_errors(model, card["scoring"]["params"].get("tail_levels", [.01, .05, .95, .99]))
            row["m0_divisors"] = divisors
            row.update(normalize(verdict, divisors, len(model.mean)))


def aggregate(rows, platform_clock=43200):
    scores = [r["score"] for r in rows if r["score"] is not None]
    proxies = [r["score"] for r in rows if r.get("proxy_available") and r["score"] is not None]
    wall = sum(r["wall_seconds"] for r in rows)
    mean_time = wall / len(rows) if rows else 0
    return {"units": len(rows), "statuses": dict(Counter(r["status"] for r in rows)),
            "requests_used": sum(r["requests_used"] for r in rows), "scored_units": len(scores),
            "mean": sum(scores)/len(scores) if scores else None, "caps": sum(s >= 8 for s in scores),
            "proxy_units": len(proxies), "proxy_mean": sum(proxies)/len(proxies) if proxies else None,
            "proxy_caps": sum(s >= 8 for s in proxies),
            "sum_unit_wall_seconds": wall, "mean_unit_wall_seconds": mean_time,
            "pull_seconds": sum(r["pull_seconds"] for r in rows),
            "projection_104_seconds": 104 * mean_time, "platform_clock_seconds": platform_clock,
            "over_half_platform_clock": 104 * mean_time > platform_clock / 2,
            "score_denominator": "resolved practice proxies plus all failures; successful unlabeled units excluded"}


def write_csv(path, rows, fields):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run_image(image, args, destination, roster, helper=None):
    selected = select_units(args.units_root, args.units)
    source_commit = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    source_dirty = bool(subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain"], text=True).strip())
    destination.mkdir()
    cached = image_info(image)
    if cached and (cached["Os"], cached["Architecture"]) != ("linux", "amd64"):
        # A multi-platform digest cached for ARM still needs its amd64 variant.
        cached = None
    if cached:
        validate_image(cached)
    host = json.loads(docker("info", "--format", "{{json .}}").stdout)
    limits = host_limits(host)
    restricted = None
    infra_start = time.monotonic()
    if args.network == "restricted":
        helper = helper or build_helper(destination)
        restricted = RestrictedNetwork(destination, helper, args.house_mode, args.replay_dir,
                                       args.chaos_timeout, args.chaos_slow)
        restricted.__enter__()
    infra_seconds = time.monotonic() - infra_start
    rows = []
    available = bool(cached)
    ingestion_start = time.monotonic()
    try:
        for index, unit in enumerate(selected):
            allowance = args.platform_clock - (time.monotonic()-ingestion_start)
            row = run_unit(unit.resolve(), image, destination, limits, args, restricted=restricted,
                           pull=(not available or (index == 0 and args.pull_policy == "always")),
                           cached=available, allowance=allowance)
            # A timed-out initial pull must not make later units assume a cache
            # hit. They get their own deadline to retry the still-missing image.
            available = available or bool(row.get("image_id"))
            rows.append(row)
            print(f"[{index+1}/{len(selected)}] {unit.name}: {row['status']} {row['wall_seconds']:.2f}s requests={row['requests_used']}", flush=True)
        ingestion_seconds = time.monotonic() - ingestion_start
    finally:
        if restricted:
            atomic_json(destination / "house-stats.json", restricted.stats())
            restricted.__exit__(None, None, None)
    scoring_start = time.monotonic()
    score_rows(rows, roster)
    summary = aggregate(rows, args.platform_clock)
    summary.update(image=image, network=args.network, house_mode=args.house_mode, limits=limits,
                   helper_image_id=helper, host={k: host[k] for k in ["NCPU", "MemTotal", "Architecture", "ServerVersion"]},
                   infrastructure_seconds=infra_seconds, ingestion_seconds=ingestion_seconds,
                   scoring_seconds=time.monotonic()-scoring_start, image_cached_before=bool(cached),
                   pull_policy=args.pull_policy, unit_timeout_seconds=args.timeout,
                   vendor_commit=subprocess.check_output(["git", "-C", str(ROOT / "vendor/track2"), "rev-parse", "HEAD"], text=True).strip(),
                   source_commit=source_commit, source_dirty=source_dirty, harness_source_sha256=SOURCE_HASHES)
    atomic_json(destination / "summary.json", summary)
    (destination / "cards.json").write_text(json.dumps(rows, indent=2, allow_nan=False) + "\n")
    write_csv(destination / "cards.csv", rows, ["unit_id", "status", "requests_used", "wall_seconds", "pull_seconds",
                                               "score", "proxy_available", "date_basis", "reason", "exit_code", "timed_out", "oom_killed"])
    print(json.dumps(summary, indent=2), flush=True)
    return summary, rows


def compare(left, right, destination):
    left_summary, left_rows = left
    right_summary, right_rows = right
    paired = []
    right_by_unit = {r["unit_id"]: r for r in right_rows}
    for a in left_rows:
        b = right_by_unit[a["unit_id"]]
        paired.append({"unit_id": a["unit_id"], "status_a": a["status"], "status_b": b["status"],
                       "score_a": a["score"], "score_b": b["score"],
                       "delta_b_minus_a": b["score"]-a["score"] if a["score"] is not None and b["score"] is not None else None,
                       "seconds_a": a["wall_seconds"], "seconds_b": b["wall_seconds"],
                       "requests_a": a["requests_used"], "requests_b": b["requests_used"]})
    deltas = [r["delta_b_minus_a"] for r in paired if r["delta_b_minus_a"] is not None]
    result = {"a": left_summary, "b": right_summary, "paired_scored_units": len(deltas),
              "paired_mean_delta_b_minus_a": sum(deltas)/len(deltas) if deltas else None}
    atomic_json(destination / "comparison.json", result)
    write_csv(destination / "comparison.csv", paired, list(paired[0]))
    lines = ["# Mock Final digest comparison", "", f"A: `{left_summary['image']}`", f"B: `{right_summary['image']}`", "",
             "| Metric | A | B |", "|---|---:|---:|"]
    for key in ["units", "statuses", "proxy_units", "proxy_mean", "caps", "requests_used", "ingestion_seconds", "projection_104_seconds", "over_half_platform_clock"]:
        lines.append(f"| {key} | {left_summary[key]} | {right_summary[key]} |")
    lines += ["", f"Paired mean B − A: {result['paired_mean_delta_b_minus_a']} ({len(deltas)} units).",
              "Scores are local practice proxies. Successful units without labels have no score.",
              "Pull time is measured; a cached pull is not a cold layer download."]
    (destination / "COMPARISON.md").write_text("\n".join(lines)+"\n")
    return result


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--image", required=True)
    p.add_argument("--compare-image")
    p.add_argument("--units", default="practice", help="all 104 supplied units, exemplar, or first N sorted units")
    p.add_argument("--units-root", type=Path, default=ROOT / "vendor/track2/units")
    p.add_argument("--network", choices=["none", "restricted"], default="none")
    p.add_argument("--house-mode", choices=["canned", "chaos", "replay"], default="canned")
    p.add_argument("--replay-dir", type=Path)
    p.add_argument("--chaos-timeout", type=float, default=120)
    p.add_argument("--chaos-slow", type=float, default=1)
    p.add_argument("--timeout", type=float, default=1800)
    p.add_argument("--platform-clock", type=float, default=43200)
    p.add_argument("--seed", type=int, help="default: existing per-card CRC32 seed (or QFBENCH_SEED)")
    p.add_argument("--pull-policy", choices=["missing", "always"], default="missing")
    p.add_argument("--proxy-roster", type=Path)
    p.add_argument("--no-proxy-scores", action="store_true")
    p.add_argument("--out", type=Path)
    p.add_argument("--allow-local-image", action="store_true", help="test fixtures only; resolves local tag to image ID")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    if (not all(math.isfinite(x) for x in [args.timeout, args.platform_clock, args.chaos_timeout, args.chaos_slow])
            or args.timeout <= 0 or args.platform_clock <= 0 or args.timeout > 1800 or args.platform_clock > 43200
            or args.chaos_timeout < 0 or args.chaos_slow < 0):
        raise SystemExit("timeouts must be positive and no greater than Final's 1800/43200 seconds")
    if args.house_mode == "replay" and (not args.replay_dir or not args.replay_dir.is_dir()):
        raise SystemExit("replay requires an existing --replay-dir")
    for attr in ["image", "compare_image"]:
        image = getattr(args, attr)
        if not image:
            continue
        if not re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", image):
            info = image_info(image) if args.allow_local_image else None
            if not info:
                raise SystemExit("use an immutable published name@sha256:digest (or --allow-local-image for fixtures)")
            setattr(args, attr, info["Id"])
    select_units(args.units_root, args.units)
    roster = proxy_roster(args)
    destination = (args.out or ROOT / ".eval/mock-final" / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    left = run_image(args.image, args, destination / "a", roster)
    if args.compare_image:
        right = run_image(args.compare_image, args, destination / "b", roster, helper=left[0]["helper_image_id"])
        compare(left, right, destination)
    print(f"Reports: {destination}", flush=True)
    return 1 if any(r["status"] != "passed" for r in left[1]) or (args.compare_image and any(r["status"] != "passed" for r in right[1])) else 0


if __name__ == "__main__":
    raise SystemExit(main())
