from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from t2agent.io import read_card, read_panels
from t2agent.m0 import distribution

from .data import build_union, practice, synthetic, units
from .official import normalize, run_forecaster, score
from .scales import expected_errors


# Environment read by the forecasters that can change their output. The run directory identity
# includes these so, e.g., numeric-only and card-notes practice runs never share a directory.
OUTPUT_ENV = ("QFBENCH_NETWORK", "TEXT_LAYER_MODE", "TEXT_LAYER_LAMBDA", "TEXT_LAYER_CACHE_DIR",
              "TEXT_LAYER_REPLAY_ONLY", "TEXT_LAYER_SYNTHESIS_RUNS", "TEXT_LAYER_TIME_BUDGET_S",
              "MODEL_ENDPOINT", "MODEL_NAME")


def output_env() -> dict:
    env = {name: os.environ.get(name) for name in OUTPUT_ENV}
    env["MODEL_TOKEN_set"] = bool(os.environ.get("MODEL_TOKEN"))  # presence only; never the secret
    return env


def describe(card: dict) -> dict:
    targets = card["targets"]
    horizons = targets["horizons"]
    spec = card.get("forecast_spec", {})
    panel = "+".join(sorted(p["panel_id"] for p in spec.get("panels", [])))
    return {"unit_id":card["task"]["id"], "asof":str(card["provenance"]["data_cutoff"]),
            "family":card["metadata"]["category"], "panel":panel or card["metadata"].get("asset_panel", "unknown"),
            "target_type":targets["target_type"], "n_assets":len(targets["asset_ids"]),
            "horizons":",".join(map(str,horizons)),
            "horizon_bucket":"1–21" if max(horizons) <= 21 else "22–63" if max(horizons) <= 63 else "64–126" if max(horizons) <= 126 else "127+",
            "shape":"single" if len(targets["asset_ids"])*len(horizons) == 1 else "joint"}


def report(rows: list[dict], out: Path, metadata: dict, *, admissibility=False) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(out / "cards.csv", index=False)
    keys = ["family", "panel", "target_type", "horizon_bucket", "shape", "date_basis"]
    summary = {"cards":len(df),"failed":int(df.failed.sum()),
               "forecast_seconds_total":float(df.forecast_seconds.sum()),
               "forecast_seconds_max":float(df.forecast_seconds.max()), "metadata":metadata}
    if not admissibility:
        summary.update(mean=float(df.score.mean()), median=float(df.score.median()),
                       clipped=int((df.unclipped >= 8).sum()))
        if metadata["mode"] == "calibration" and len(df) > 1:
            summary["monte_carlo_standard_error"] = float(df.score.std(ddof=1)/np.sqrt(len(df)))
        summary["breakdowns"] = {k: df.groupby(k).agg(cards=("score","size"), mean=("score","mean"),
                                                      failures=("failed","sum")).reset_index().to_dict("records")
                                 for k in keys if k in df}
        print(f"\n{metadata['mode']} / {metadata['forecaster']}: {len(df)} cards, "
              f"mean {summary['mean']:.6f}, median {summary['median']:.6f}, "
              f"failures {summary['failed']}, clipped {summary['clipped']}")
        for key, records in summary["breakdowns"].items():
            print(f"\nBy {key}\n" + pd.DataFrame(records).to_string(index=False, float_format=lambda x:f"{x:.6f}"))
    else:
        print(f"Admissibility / {metadata['forecaster']}: {len(df)-summary['failed']}/{len(df)} passed; "
              f"max forecast time {summary['forecast_seconds_max']:.3f}s")
    (out / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False)+"\n")
    print(f"\nReport: {out / 'summary.json'}", flush=True)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local Track 2 measurement; never loads answers in inference")
    parser.add_argument("mode", choices=["backtest", "eval-practice", "admissibility", "calibration", "generate"])
    parser.add_argument("--forecaster", default="m0", help="m0, numeric_v1, numeric_v1_1, reference, or module:function")
    parser.add_argument("--units", type=Path, default=Path("vendor/track2/units"))
    parser.add_argument("--work", type=Path, default=Path(".eval"))
    parser.add_argument("--cards", type=int, default=2060)
    parser.add_argument("--dataset-seed", type=int, default=20261014)
    parser.add_argument("--seed", type=int, default=None, help="forecast seed; otherwise QFBENCH_SEED or model default")
    parser.add_argument("--n-draws", type=int, default=None)
    parser.add_argument("--limit", type=int, help="debug subset, explicitly recorded in reports")
    parser.add_argument("--strict-dates", action="store_true", help="practice: refuse inferred business-day targets")
    args = parser.parse_args(argv)
    if args.n_draws is None:
        args.n_draws = 2000 if args.forecaster in {"numeric_v1", "numeric_v1_1"} else 500
    if args.cards <= 0 or args.n_draws < 200 or (args.limit is not None and args.limit <= 0):
        parser.error("cards/limit must be positive and n-draws >=200")
    if importlib.metadata.version("qfbench2-common") != "2.6.0":
        parser.error("This measurement environment requires qfbench2-common==2.6.0")
    args.work.mkdir(parents=True, exist_ok=True)
    metadata = {"mode":args.mode,"forecaster":args.forecaster,"n_draws":args.n_draws,
                "forecast_seed":args.seed,"QFBENCH_SEED":os.environ.get("QFBENCH_SEED"),"output_env":output_env(),
                "dataset_seed":args.dataset_seed,"limit":args.limit,"strict_dates":args.strict_dates,
                "packages":{p:importlib.metadata.version(p) for p in
                            ["qfbench2-common","qfbench2-track-forecasting","numpy","pandas","scipy","pyarrow"]}}
    project = Path(__file__).resolve().parents[1]
    source_hash = hashlib.sha256()
    # Runtime configs and the text_layer subpackage change output too, so hash them as well.
    for source in sorted([*project.glob("t2agent/**/*.py"), *project.glob("t2agent/**/*.json"),
                          *project.glob("t2eval/*.py")]):
        source_hash.update(str(source.relative_to(project)).encode())
        source_hash.update(source.read_bytes())
    metadata["source_sha256"] = source_hash.hexdigest()
    metadata["toolkit_source"] = json.loads(importlib.metadata.distribution("qfbench2-common").read_text("direct_url.json") or "null")
    try:
        metadata["vendor_commit"] = subprocess.check_output(
            ["git","-C",str(args.units.parent),"rev-parse","HEAD"], text=True).strip()
    except subprocess.CalledProcessError:
        metadata["vendor_commit"] = "unknown"
    unresolved = []
    if args.mode == "admissibility":
        cases = [{"unit":str(u)} for u in units(args.units, exemplar=True)]
    else:
        donors, union_meta = build_union(args.units, args.work / "union")
        metadata["union"] = union_meta
        if args.mode == "eval-practice":
            cases, unresolved = practice(args.units, args.work / "practice", donors, strict_dates=args.strict_dates)
            metadata["unresolved"] = unresolved
            metadata["eligible_roster"] = len(cases)
            metadata["practice_total"] = len(units(args.units))
        else:
            dataset = args.work / f"synthetic-{args.dataset_seed}-{args.cards}-{union_meta['input_sha256'][:12]}"
            manifest = dataset / "manifest.json"
            if manifest.exists():
                cases = json.loads(manifest.read_text())
            else:
                cases = synthetic(args.units, dataset, donors, args.cards, args.dataset_seed)
                manifest.write_text(json.dumps(cases, indent=2)+"\n")
            metadata["dataset_manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
        del donors
    if args.mode == "generate":
        print(f"Generated {len(cases)} cards")
        return 0
    if args.limit:
        cases = cases[:args.limit]
    if not cases:
        print("No resolvable cards. Reasons: " + json.dumps(unresolved,indent=2))
        return 1
    # One directory per run configuration, so a debug run never overwrites a full run.
    identity = hashlib.sha256(json.dumps(metadata,sort_keys=True).encode()).hexdigest()[:12]
    out = args.work / "runs" / f"{args.mode}-{args.forecaster.replace(':','_')}-{identity}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "roster.json").write_text(json.dumps(cases,indent=2)+"\n")
    rows = []
    for i, case in enumerate(cases):
        unit = Path(case["unit"])
        card = read_card(unit / "card.toml")
        row = {**describe(card),"date_basis":case.get("date_basis","not_applicable")}
        output = out / "outputs" / row["unit_id"] / "forecast.parquet"
        started = time.perf_counter()
        duration = None
        with warnings.catch_warnings(record=True) as captured:
            try:
                run_forecaster(args.forecaster, unit, output, args.n_draws, args.seed,
                               text=args.mode in {"eval-practice","admissibility"})
                duration = time.perf_counter()-started
                if args.mode == "admissibility":
                    payload = score(unit / "card.toml", output)
                    row.update(failed=not payload["admissible"],gates=json.dumps(payload["gates"]))
                else:
                    model = distribution(card, read_panels(unit / "panels"), row["asof"])
                    if card["scoring"]["params"].get("tail_metric", "pinball") != "pinball":
                        raise ValueError("M0 §5 expected tail error is defined for pinball only")
                    divisors = expected_errors(model, card["scoring"]["params"].get("tail_levels",[.01,.05,.95,.99]))
                    realized = Path(case["realized"])
                    if args.mode == "calibration":
                        # Independent RNG, not any submitted draw; historical outcomes unused.
                        rng = np.random.default_rng(np.random.SeedSequence([args.dataset_seed, i, 0xCA11B]))
                        y = model.mean + model.factor @ rng.standard_normal(len(model.mean))
                        realized = out / "calibration-realized" / f"{row['unit_id']}.parquet"
                        realized.parent.mkdir(parents=True,exist_ok=True)
                        pd.DataFrame([{"asset":a,"horizon":h,"value":float(y[k])}
                                      for k,(a,h) in enumerate((a,h) for a in card["targets"]["asset_ids"]
                                                             for h in card["targets"]["horizons"])]).to_parquet(realized,index=False)
                    payload = score(unit / "card.toml", output, realized)
                    row.update(normalize(payload,divisors,len(model.mean)))
                    row.update({f"divisor_{k}":v for k,v in divisors.items()})
                    row.update({k:payload.get(k) for k in ("marginal_crps","joint_variogram","tail_penalty")})
                (out / "outputs" / f"{row['unit_id']}.score.json").write_text(json.dumps(payload,indent=2)+"\n")
            except (Exception, SystemExit) as exc:
                row.update(failed=True,score=8.0,unclipped=8.0,error=f"{type(exc).__name__}: {exc}")
            row["warnings"] = " | ".join(sorted({str(w.message) for w in captured}))
        row["forecast_seconds"] = duration if duration is not None else time.perf_counter()-started
        row["total_seconds"] = time.perf_counter()-started
        rows.append(row)
        if row["failed"]:
            print(f"FAILED {row['unit_id']}: {row.get('error',row.get('gates','gate refusal'))}",flush=True)
        if (i+1) % 100 == 0:
            print(f"{args.mode}: {i+1}/{len(cases)} scored",flush=True)
    summary = report(rows,out,metadata,admissibility=args.mode=="admissibility")
    return int(summary["failed"] != 0)


if __name__ == "__main__":
    raise SystemExit(main())
