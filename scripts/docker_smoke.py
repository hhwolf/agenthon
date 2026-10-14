"""Build exact upstream, toolkit-pinned reference, and our inference-only image for amd64."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import argparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--forecaster', choices=['m0', 'numeric_v1'], default='m0')
args = parser.parse_args()

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
stage = ROOT / ".context/reference-build"
stage.mkdir(parents=True, exist_ok=True)
shutil.copytree(ROOT / "vendor/track2/qfbench2_track_forecasting", stage / "qfbench2_track_forecasting",
                dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
original = (ROOT / "vendor/track2/Dockerfile").read_text()
env = os.environ.copy()
plugin = Path("/opt/homebrew/lib/docker/cli-plugins/docker-buildx")
if plugin.exists():
    config = ROOT / ".context/docker-config"
    plugins = config / "cli-plugins"
    plugins.mkdir(parents=True,exist_ok=True)
    link = plugins / "docker-buildx"
    if not link.exists():
        link.symlink_to(plugin)
    env["DOCKER_CONFIG"] = str(config)
    if "DOCKER_HOST" not in env:
        endpoint = subprocess.check_output(["docker","context","inspect","--format","{{.Endpoints.docker.Host}}"],text=True).strip()
        env["DOCKER_HOST"] = endpoint


def run(args, log):
    print(" ".join(map(str,args)),flush=True)
    with log.open("w") as f:
        subprocess.run(list(map(str,args)),env=env,stdout=f,stderr=subprocess.STDOUT,check=True)


results = []
for label, version, context in [("upstream",None,stage),("pinned","2.6.0",stage),(args.forecaster,None,ROOT)]:
    if context == stage:
        text = original if version is None else original.replace("v2.6.1.tar.gz","v2.6.0.tar.gz")
        (stage / "Dockerfile").write_text(text)
    tag = f"t2-{label}:local"
    run(["docker","buildx","build","--platform","linux/amd64","--load","-t",tag,context],
        ROOT / f".context/docker-{label}-build.log")
    arch = subprocess.check_output(["docker","image","inspect","--format","{{.Os}}/{{.Architecture}}",tag],env=env,text=True).strip()
    assert arch == "linux/amd64", arch
    unit = ROOT / "vendor/track2/units/t2-EXAMPLE-ust-curve-1m"
    out = ROOT / f".context/docker-{label}-output"
    out.mkdir(exist_ok=True)
    run(["docker","run","--rm","--platform","linux/amd64","--network=none","--cpus=4","--memory=4g",
         "--read-only","--tmpfs","/tmp:rw,noexec,nosuid,size=64m",
         "-v",f"{unit}:/input:ro","-v",f"{out}:/output",tag,"forecast","--panels","/input/panels",
         "--text","/input/text","--asof","2024-06-28","--out","/output/forecast.parquet"]
        + (["--forecaster",args.forecaster] if context == ROOT else []),
        ROOT / f".context/docker-{label}-run.log")
    from t2eval.official import score
    payload = score(unit / "card.toml",out / "forecast.parquet")
    assert payload["admissible"],payload
    image_id = subprocess.check_output(["docker","image","inspect","--format","{{.Id}}",tag],env=env,text=True).strip()
    results.append({"image":tag,"image_id":image_id,"platform":arch,"network":"none","verdict":payload})
    print(json.dumps(results[-1],indent=2),flush=True)
(ROOT / ".context/docker-results.json").write_text(json.dumps(results,indent=2)+"\n")
