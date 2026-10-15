#!/usr/bin/env python
"""Run the text layer on every practice unit and save each TextSignal as JSON.

    .venv/bin/python scripts/run_text_layer_practice.py --mode dev        # NVIDIA dev endpoint via .env
    .venv/bin/python scripts/run_text_layer_practice.py --mode mock       # in-process mock House, no network
    .venv/bin/python scripts/run_text_layer_practice.py --mode offline    # QFBENCH_NETWORK=none -> all neutral

Outputs under ``--out`` (default ``.eval/text_signals/``): ``<unit_id>.json`` + ``<unit_id>.md``
(the rationale), ``summary.json`` and ``summary.md`` (calls used, fallbacks, signal distribution by
family). Dev responses are cached under ``--cache-dir`` (default ``.eval/llm_cache/``).
The forecaster is not touched; the numeric owner wires ``apply_text_signal``.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from t2agent.contracts import CallBudget, TextSignal  # noqa: E402
from t2agent.text_layer import constants as C  # noqa: E402
from t2agent.text_layer import read_text  # noqa: E402
from t2agent.text_layer.summary import numeric_summary_for_unit  # noqa: E402


def load_env_file(path: Path) -> dict[str, str]:
    """Minimal .env reader: KEY=VALUE lines, '#' comments, optional quotes. Never overrides os.environ."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def signal_to_dict(signal: TextSignal) -> dict:
    return {
        "scenarios": [dataclasses.asdict(s) for s in signal.scenarios],
        "tail_mult": signal.tail_mult,
        "evidence": [dataclasses.asdict(e) for e in signal.evidence],
        "rationale_md": signal.rationale_md,
        "calls_used": signal.calls_used,
        "fallback_reason": signal.fallback_reason,
    }


def summarise(rows: list[dict]) -> dict:
    calls = [r["calls_used"] for r in rows]
    fallbacks = Counter(r["fallback_reason"].split(":")[0] if r["fallback_reason"] else "none" for r in rows)
    by_family: dict[str, dict] = {}
    for fam, group in sorted(_group(rows, "family").items()):
        drift = [abs(r["mean_drift_abs"]) for r in group]
        by_family[fam] = {
            "units": len(group),
            "neutral": sum(1 for r in group if r["fallback_reason"]),
            "non_neutral": sum(1 for r in group if not r["fallback_reason"]),
            "calls_mean": round(statistics.mean(r["calls_used"] for r in group), 2),
            "mean_abs_weighted_drift": round(statistics.mean(drift), 4) if drift else 0.0,
            "max_abs_weighted_drift": round(max(drift), 4) if drift else 0.0,
            "mean_mixture_vol_mult": round(statistics.mean(r["mixture_vol_mult"] for r in group), 4),
            "vol_below_one": sum(1 for r in group if r["min_vol_mult"] < 1.0),
            "mean_tail_mult": round(statistics.mean(r["tail_mult"] for r in group), 4),
            "mean_scenarios": round(statistics.mean(r["n_scenarios"] for r in group), 2),
            "mean_evidence": round(statistics.mean(r["n_evidence"] for r in group), 1),
            "mean_established": round(statistics.mean(r["n_established"] for r in group), 1),
            "elapsed_mean_s": round(statistics.mean(r["elapsed_s"] for r in group), 2),
        }
    return {
        "units": len(rows),
        "calls_total": sum(calls),
        "calls_mean": round(statistics.mean(calls), 2) if calls else 0,
        "calls_median": statistics.median(calls) if calls else 0,
        "calls_max": max(calls) if calls else 0,
        "calls_histogram": dict(sorted(Counter(calls).items())),
        "over_hard_cap": sum(1 for c in calls if c > C.HARD_REQUEST_CAP),
        "fallbacks": dict(fallbacks),
        "fallback_reasons": sorted({r["fallback_reason"] for r in rows if r["fallback_reason"]})[:40],
        "cache_hits_total": sum(r.get("cache_hits", 0) for r in rows),
        "elapsed_total_s": round(sum(r["elapsed_s"] for r in rows), 1),
        "elapsed_max_s": round(max(r["elapsed_s"] for r in rows), 1) if rows else 0,
        "by_family": by_family,
    }


def _group(rows: list[dict], key: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        out[r[key]].append(r)
    return out


def summary_markdown(summary: dict, mode: str, model: str) -> str:
    lines = [f"# Text layer practice sweep ({mode}, model {model or 'n/a'})", "",
             f"Units: {summary['units']}; requests: total {summary['calls_total']}, mean {summary['calls_mean']}, "
             f"median {summary['calls_median']}, max {summary['calls_max']} (hard cap {C.HARD_REQUEST_CAP}; "
             f"units over cap: {summary['over_hard_cap']}); cache hits: {summary['cache_hits_total']}; "
             f"wall time {summary['elapsed_total_s']} s (max per unit {summary['elapsed_max_s']} s).", "",
             f"Requests histogram: {summary['calls_histogram']}", "",
             f"Fallbacks: {summary['fallbacks']}", ""]
    if summary["fallback_reasons"]:
        lines += ["Fallback reasons:"] + [f"- {r}" for r in summary["fallback_reasons"]] + [""]
    lines += ["| family | units | non-neutral | calls/unit | mean abs drift (sd) | max abs drift | mean vol_mult | vol<1 | mean tail | scenarios | evidence (est.) | s/unit |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for fam, s in summary["by_family"].items():
        lines.append(f"| {fam} | {s['units']} | {s['non_neutral']} | {s['calls_mean']} | {s['mean_abs_weighted_drift']} | "
                     f"{s['max_abs_weighted_drift']} | {s['mean_mixture_vol_mult']} | {s['vol_below_one']} | {s['mean_tail_mult']} | "
                     f"{s['mean_scenarios']} | {s['mean_evidence']} ({s['mean_established']}) | {s['elapsed_mean_s']} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--units", type=Path, default=ROOT / "vendor" / "track2" / "units")
    p.add_argument("--out", type=Path, default=ROOT / ".eval" / "text_signals")
    p.add_argument("--cache-dir", type=Path, default=ROOT / ".eval" / "llm_cache")
    p.add_argument("--env-file", type=Path, default=ROOT / ".env")
    p.add_argument("--mode", choices=["dev", "mock", "offline"], default="dev")
    p.add_argument("--mock-scenario", default="auto")
    p.add_argument("--limit", type=int)
    p.add_argument("--only", nargs="*", help="unit ids (or substrings) to run")
    p.add_argument("--budget", type=int, default=C.HARD_REQUEST_CAP)
    p.add_argument("--time-budget", type=float, default=C.TIME_BUDGET_S)
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    env = dict(os.environ)
    server = None
    if args.mode == "dev":
        for k, v in load_env_file(args.env_file).items():
            env.setdefault(k, v)
        missing = [k for k in ("MODEL_ENDPOINT", "MODEL_TOKEN", "MODEL_NAME") if not env.get(k)]
        if missing:
            print(f"dev mode needs {', '.join(missing)} in the environment or {args.env_file} "
                  "(see docs/TEXT_LAYER.md §4); use --mode mock or --mode offline to run without a key.", file=sys.stderr)
            return 2
        env.setdefault("QFBENCH_NETWORK", "restricted")
    elif args.mode == "mock":
        from mock_house import MockHouse
        server = MockHouse(scenario=args.mock_scenario).start()
        env.update(server.env())
    else:
        env["QFBENCH_NETWORK"] = "none"
    if args.no_cache or args.mode != "dev":
        env.pop("TEXT_LAYER_CACHE_DIR", None)
    else:
        env["TEXT_LAYER_CACHE_DIR"] = str(args.cache_dir)

    units = sorted(d for d in args.units.iterdir() if (d / "card.toml").is_file())
    if args.only:
        units = [u for u in units if any(o in u.name for o in args.only)]
    if args.limit:
        units = units[: args.limit]
    args.out.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    try:
        for i, unit in enumerate(units, 1):
            t0 = time.monotonic()
            try:
                summary = numeric_summary_for_unit(unit)
            except Exception as exc:  # noqa: BLE001 - record and continue
                rows.append({"unit_id": unit.name, "family": "unknown", "calls_used": 0, "elapsed_s": 0.0,
                             "fallback_reason": f"NumericSummary failed: {type(exc).__name__}: {exc}", "mean_drift_abs": 0.0,
                             "mixture_vol_mult": 1.0, "min_vol_mult": 1.0, "tail_mult": 1.0, "n_scenarios": 1,
                             "n_evidence": 0, "n_established": 0})
                print(f"[{i}/{len(units)}] {unit.name}: numeric summary failed: {exc}", file=sys.stderr)
                continue
            budget = CallBudget(limit=args.budget)
            if server is not None:
                before = len(server.requests)
            signal = read_text(unit, summary, budget, env=env, time_budget_s=args.time_budget)
            elapsed = time.monotonic() - t0
            weights = [s.weight for s in signal.scenarios]
            mean_drift = {a: sum(s.weight * s.drift_sd.get(a, 0.0) for s in signal.scenarios) for a in summary.assets}
            cache_hits = signal.rationale_md.count("served from the dev cache")
            row = {
                "unit_id": summary.unit_id, "family": summary.family, "asof": summary.asof.isoformat(),
                "assets": list(summary.assets), "horizons": list(summary.horizons),
                "calls_used": signal.calls_used, "budget_used": budget.used, "elapsed_s": round(elapsed, 2),
                "fallback_reason": signal.fallback_reason,
                "mean_drift": {a: round(v, 4) for a, v in mean_drift.items()},
                "mean_drift_abs": round(max(abs(v) for v in mean_drift.values()), 4) if mean_drift else 0.0,
                "mixture_vol_mult": round(sum(w * s.vol_mult for w, s in zip(weights, signal.scenarios)), 4),
                "min_vol_mult": min(s.vol_mult for s in signal.scenarios),
                "tail_mult": signal.tail_mult, "n_scenarios": len(signal.scenarios),
                "n_evidence": len(signal.evidence), "n_established": sum(e.established for e in signal.evidence),
                "cache_hits": cache_hits,
            }
            rows.append(row)
            payload = {
                **{k: v for k, v in row.items() if k != "cache_hits"},
                "mode": args.mode, "model": env.get("MODEL_NAME", ""),
                "numeric_summary": {"spot": summary.spot, "horizon_sd": {f"{a}@{h}": v for (a, h), v in summary.horizon_sd.items()},
                                    "vol_ratio": summary.vol_ratio, "target_type": summary.target_type,
                                    "value_unit": summary.value_unit},
                "signal": signal_to_dict(signal),
            }
            (args.out / f"{summary.unit_id}.json").write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
            (args.out / f"{summary.unit_id}.md").write_text(signal.rationale_md)
            if not args.quiet:
                status = signal.fallback_reason or f"{len(signal.scenarios)} scenarios, drift {row['mean_drift']}, vol {row['mixture_vol_mult']}, tail {signal.tail_mult}"
                print(f"[{i}/{len(units)}] {summary.unit_id} ({summary.family}): calls {signal.calls_used}, {elapsed:.1f}s: {status}")
    finally:
        if server is not None:
            server.stop()
    summary_obj = summarise(rows)
    summary_obj.update({"mode": args.mode, "model": env.get("MODEL_NAME", ""), "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "constants": {k: getattr(C, k) for k in dir(C) if k.isupper() and not k.startswith("ENV_") and not isinstance(getattr(C, k), dict)}})
    (args.out / "summary.json").write_text(json.dumps(summary_obj, indent=1) + "\n")
    md = summary_markdown(summary_obj, args.mode, env.get("MODEL_NAME", ""))
    (args.out / "summary.md").write_text(md)
    print("\n" + md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
