"""Docker integration evidence for failures and the restricted House topology.

Run from the repository root: .venv/bin/python scripts/verify_mock_final.py
This builds local fixtures only; it never publishes an image or submits a pack.
"""
import argparse
import json
import secrets
import shutil
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from t2eval.mock_final import (ROOT, RestrictedNetwork, build_helper, build_image, docker,
                              host_limits, parser, run_unit, runtime_environment, score_rows)
from t2eval.mock_house_service import atomic_json, request_hash


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--out", type=Path)
    options = cli.parse_args()
    work = (options.out or ROOT / ".eval/mock-final" / ("verification-" + time.strftime("%Y%m%d-%H%M%S"))).resolve()
    work.mkdir(parents=True, exist_ok=False)
    helper = build_helper(work)
    limits = host_limits(json.loads(docker("info", "--format", "{{json .}}").stdout))
    context = work / "broken-build"
    context.mkdir()
    fixtures = ROOT / "tests/fixtures/mock_final"
    for filename in ["Dockerfile", "broken.py"]:
        shutil.copy2(fixtures / filename, context / filename)
    failures = []
    for mode, expected in [("crash", "container_crashed"), ("timeout", "resource_timeout"),
                           ("oversized", "no_output"), ("schema", "schema_invalid")]:
        image = build_image(context, "t2-mock-broken:" + mode, work / f"build-{mode}.log", "--build-arg", f"MODE={mode}")
        args = parser().parse_args(["--image", image, "--units", "exemplar", "--no-proxy-scores"])
        args.timeout = 1 if mode == "timeout" else 30
        folder = work / mode
        folder.mkdir()
        row = run_unit(ROOT / "vendor/track2/units/t2-EXAMPLE-ust-curve-1m", image, folder, limits, args, cached=True)
        score_rows([row], {})
        assert row["status"] == expected and row["score"] == 8, row
        failures.append(row)
        print(f"{mode}: {row['status']} = {row['score']} ({row['wall_seconds']:.2f}s)", flush=True)
    probes = []
    for mode in ["canned", "chaos", "replay"]:
        folder = work / ("probe-" + mode)
        folder.mkdir()
        cache = folder / "replay-cache"
        (cache / "probe").mkdir(parents=True)
        params = {"model": "synthetic-dev-model", "messages": [{"role": "user", "content": "hello"}], "max_tokens": 4000,
                  "temperature": 0, "top_p": 1, "seed": 20261014, "extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}
        key = request_hash("probe", "synthetic-dev-model", params)
        atomic_json(cache / "probe" / f"{key}.json", {"model": "synthetic-dev-model", "text": "synthetic cached response", "finish_reason": "stop"})
        with RestrictedNetwork(folder, helper, mode, cache, timeout_delay=.8, slow_delay=.2) as network:
            token = secrets.token_urlsafe(32)
            network.activate("probe", token, 120)
            house_info = json.loads(docker("inspect", network.house).stdout)[0]
            house_ip = house_info["NetworkSettings"]["Networks"][network.backend]["IPAddress"]
            env = dict(runtime_environment("restricted", token, 42), PROBE_MODE=mode, HOUSE_IP=house_ip)
            envfile = folder / "probe.env"
            envfile.touch(mode=0o600)
            envfile.write_text("".join(f"{k}={v}\n" for k, v in env.items()))
            name = "t2mf-probe-" + uuid.uuid4().hex[:12]
            try:
                result = docker("run", "--name", name, "--read-only", "--network", network.network,
                                "--platform", "linux/amd64", "--cpus=1", "--memory=128m", "--memory-swap=128m",
                                "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m", "--env-file", envfile,
                                "-v", f"{fixtures / 'probe.py'}:/probe.py:ro", "--entrypoint", "python", helper, "/probe.py", timeout=120, check=False)
                (folder / "probe.log").write_text(result.stdout + result.stderr)
                assert result.returncode == 0, result.stdout + result.stderr
                probe = json.loads(result.stdout)
                probe["house_stats"] = network.stats()
                probe["internal_networks"] = [json.loads(docker("network", "inspect", n).stdout)[0]["Internal"] for n in [network.network, network.backend]]
                assert all(probe["internal_networks"])
                assert not house_info["HostConfig"]["PortBindings"]
                expected = {"canned": 25, "chaos": 6, "replay": 2}[mode]
                assert probe["house_stats"]["units"] == {"probe": expected}
                assert all(e["max_tokens"] == 4000 for e in probe["house_stats"]["events"])
                probes.append(probe)
                print(f"restricted {mode}: {len(probe['checks'])} checks passed, {expected} admitted requests", flush=True)
            finally:
                docker("rm", "-f", name, check=False)
                envfile.unlink(missing_ok=True)
    report = {"failures": failures, "network_probes": probes, "helper_image_id": helper,
              "replay_fixture": "Synthetic response in teammate's exact ResponseCache format; no actual dev cache supplied."}
    atomic_json(work / "verification.json", report)
    print(f"Verification report: {work / 'verification.json'}", flush=True)


if __name__ == "__main__":
    main()
