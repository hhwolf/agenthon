#!/usr/bin/env python
"""Run the text layer on every practice unit and save each TextSignal (labels) as JSON.

    .venv/bin/python scripts/run_text_layer_practice.py --mode dev          # NVIDIA dev endpoint via .env, cached
    .venv/bin/python scripts/run_text_layer_practice.py --mode replay       # cached dev responses only, no network
    .venv/bin/python scripts/run_text_layer_practice.py --mode mock         # in-process mock House, no network
    .venv/bin/python scripts/run_text_layer_practice.py --mode notes_only   # deterministic pre-pass labels, no LLM
    .venv/bin/python scripts/run_text_layer_practice.py --mode offline      # QFBENCH_NETWORK=none -> all neutral

Outputs under ``--out`` (default ``.eval/text_signals/``): ``<unit_id>.json`` + ``<unit_id>.md`` (rationale),
``summary.json`` and ``summary.md`` with label distributions by family, calls used, fallbacks and
run-to-run agreement. ``--repeat N`` re-runs each unit N times to measure rerun stability of the
majority labels (dev mode: with a fresh cache dir per repeat, otherwise it just replays).
The forecaster is not touched; ``t2agent/text_v1.py`` wires the signal through ``apply_text_signal``.
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

LABEL_FIELDS = ("regime", "event_in_horizon", "disagreement")


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        values[key] = value.strip().strip('"').strip("'")
    return values


def signal_to_dict(signal: TextSignal) -> dict:
    return {"scenarios": [dataclasses.asdict(s) for s in signal.scenarios], "tail_mult": signal.tail_mult,
            "evidence": [dataclasses.asdict(e) for e in signal.evidence], "rationale_md": signal.rationale_md,
            "calls_used": signal.calls_used, "fallback_reason": signal.fallback_reason, "labels": signal.labels}


def _group(rows: list[dict], key: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        out[r[key]].append(r)
    return dict(sorted(out.items()))


def _dist(rows: list[dict], key: str) -> dict:
    return dict(sorted(Counter(str(r["labels"].get(key)) for r in rows).items()))


def summarise(rows: list[dict]) -> dict:
    calls = [r["calls_used"] for r in rows]
    agree = [r["agreement"] for r in rows if r["agreement"] is not None]
    by_family = {}
    for fam, group in _group(rows, "family").items():
        directions = Counter(d for r in group for d in r["directions"].values())
        ga = [r["agreement"] for r in group if r["agreement"] is not None]
        by_family[fam] = {
            "units": len(group),
            "llm_labels": sum(1 for r in group if r["labels"].get("mode") == "llm"),
            "notes_only": sum(1 for r in group if r["labels"].get("mode") == "notes_only"),
            "neutral": sum(1 for r in group if r["fallback_reason"]),
            "calls_mean": round(statistics.mean(r["calls_used"] for r in group), 2),
            "calls_max": max(r["calls_used"] for r in group),
            "regime": _dist(group, "regime"), "event_in_horizon": _dist(group, "event_in_horizon"),
            "disagreement": _dist(group, "disagreement"), "direction": dict(sorted(directions.items())),
            "direction_established": sum(1 for r in group for v in r["established"].values() if v),
            "binary_prepass": sum(1 for r in group if (r["labels"].get("prepass") or {}).get("binary_event_inside")),
            "agreement_mean": round(statistics.mean(ga), 3) if ga else None,
            "agreement_min": round(min(ga), 3) if ga else None,
            "evidence_mean": round(statistics.mean(r["n_evidence"] for r in group), 1),
            "established_mean": round(statistics.mean(r["n_established"] for r in group), 1),
            "elapsed_mean_s": round(statistics.mean(r["elapsed_s"] for r in group), 2),
            "elapsed_max_s": round(max(r["elapsed_s"] for r in group), 2),
        }
    rerun = [r["rerun_agreement"] for r in rows if r.get("rerun_agreement") is not None]
    return {
        "units": len(rows), "calls_total": sum(calls), "calls_mean": round(statistics.mean(calls), 2) if calls else 0,
        "calls_median": statistics.median(calls) if calls else 0, "calls_max": max(calls) if calls else 0,
        "calls_histogram": dict(sorted(Counter(calls).items())), "over_hard_cap": sum(1 for c in calls if c > C.HARD_REQUEST_CAP),
        "over_soft_target": sum(1 for r in rows if r["elapsed_s"] > C.SOFT_TARGET_S),
        "fallbacks": dict(Counter(r["fallback_reason"].split(":")[0] if r["fallback_reason"] else "none" for r in rows)),
        "fallback_reasons": sorted({r["fallback_reason"] for r in rows if r["fallback_reason"]})[:40],
        "agreement_mean": round(statistics.mean(agree), 3) if agree else None,
        "agreement_below_0_8": sum(1 for a in agree if a < 0.8),
        "rerun_agreement_mean": round(statistics.mean(rerun), 3) if rerun else None,
        "regime": _dist(rows, "regime"), "event_in_horizon": _dist(rows, "event_in_horizon"), "disagreement": _dist(rows, "disagreement"),
        "elapsed_total_s": round(sum(r["elapsed_s"] for r in rows), 1), "elapsed_max_s": round(max(r["elapsed_s"] for r in rows), 1) if rows else 0,
        "by_family": by_family,
    }


def summary_markdown(summary: dict, mode: str, model: str) -> str:
    lines = [f"# Text layer practice sweep ({mode}, model {model or 'n/a'})", "",
             f"Units: {summary['units']}; requests: total {summary['calls_total']}, mean {summary['calls_mean']}, median {summary['calls_median']}, "
             f"max {summary['calls_max']} (hard cap {C.HARD_REQUEST_CAP}; over cap: {summary['over_hard_cap']}); wall time {summary['elapsed_total_s']} s "
             f"(max per unit {summary['elapsed_max_s']} s; units over the {C.SOFT_TARGET_S:.0f} s soft target: {summary['over_soft_target']}).", "",
             f"Requests histogram: {summary['calls_histogram']}; fallbacks: {summary['fallbacks']}", "",
             f"Labels overall: regime {summary['regime']}; event {summary['event_in_horizon']}; disagreement {summary['disagreement']}; "
             f"self-consistency agreement mean {summary['agreement_mean']} (units below 0.8: {summary['agreement_below_0_8']})"
             + (f"; rerun agreement (modal share of label sets across repeats) mean {summary['rerun_agreement_mean']}" if summary.get("rerun_agreement_mean") is not None else ""), ""]
    if summary["fallback_reasons"]:
        lines += ["Fallback reasons:"] + [f"- {r}" for r in summary["fallback_reasons"]] + [""]
    lines += ["| family | units | llm / notes / neutral | calls mean/max | regime | event | disagreement | directions | est. dirs | binary pre-pass | agreement mean/min | evidence (est.) | s/unit mean/max |",
              "|---|---:|---|---|---|---|---|---|---:|---:|---|---|---|"]
    for fam, s in summary["by_family"].items():
        lines.append(f"| {fam} | {s['units']} | {s['llm_labels']} / {s['notes_only']} / {s['neutral']} | {s['calls_mean']} / {s['calls_max']} | "
                     f"{s['regime']} | {s['event_in_horizon']} | {s['disagreement']} | {s['direction']} | {s['direction_established']} | "
                     f"{s['binary_prepass']} | {s['agreement_mean']} / {s['agreement_min']} | {s['evidence_mean']} ({s['established_mean']}) | "
                     f"{s['elapsed_mean_s']} / {s['elapsed_max_s']} |")
    return "\n".join(lines) + "\n"


def labels_key(labels: dict) -> tuple:
    return (labels.get("regime"), labels.get("event_in_horizon"), bool(labels.get("disagreement")),
            tuple(sorted((a, v.get("direction")) for a, v in (labels.get("assets") or {}).items())))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--units", type=Path, default=ROOT / "vendor" / "track2" / "units")
    p.add_argument("--out", type=Path, default=ROOT / ".eval" / "text_signals")
    p.add_argument("--cache-dir", type=Path, default=ROOT / ".eval" / "llm_cache")
    p.add_argument("--env-file", type=Path, default=ROOT / ".env")
    p.add_argument("--mode", choices=["dev", "replay", "mock", "notes_only", "offline"], default="dev")
    p.add_argument("--mock-scenario", default="auto")
    p.add_argument("--limit", type=int)
    p.add_argument("--only", nargs="*", help="unit ids (or substrings) to run")
    p.add_argument("--budget", type=int, default=C.HARD_REQUEST_CAP)
    p.add_argument("--time-budget", type=float, default=C.TIME_BUDGET_S)
    p.add_argument("--repeat", type=int, default=1, help="run each unit N times and report rerun agreement of the labels")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    env = dict(os.environ)
    server = None
    text_mode = None
    if args.mode in ("dev", "replay"):
        for k, v in load_env_file(args.env_file).items():
            env.setdefault(k, v)
        if args.mode == "dev":
            missing = [k for k in ("MODEL_ENDPOINT", "MODEL_TOKEN", "MODEL_NAME") if not env.get(k)]
            if missing:
                print(f"dev mode needs {', '.join(missing)} in the environment or {args.env_file} (docs/TEXT_LAYER.md §4); "
                      "use --mode replay/mock/notes_only/offline to run without a key.", file=sys.stderr)
                return 2
        else:
            env.setdefault("MODEL_ENDPOINT", "http://127.0.0.1:9")
            env.setdefault("MODEL_TOKEN", "replay")
            env.setdefault("MODEL_NAME", env.get("MODEL_NAME") or "nvidia/nemotron-3-super-120b-a12b")
            env["TEXT_LAYER_REPLAY_ONLY"] = "1"
        env.setdefault("QFBENCH_NETWORK", "restricted")
        env["TEXT_LAYER_CACHE_DIR"] = str(args.cache_dir)
    elif args.mode == "mock":
        from mock_house import MockHouse
        server = MockHouse(scenario=args.mock_scenario).start()
        env.update(server.env())
        env.pop("TEXT_LAYER_CACHE_DIR", None)
    elif args.mode == "notes_only":
        text_mode = "notes_only"
        env["QFBENCH_NETWORK"] = "none"
    else:
        env["QFBENCH_NETWORK"] = "none"
    if args.no_cache:
        env.pop("TEXT_LAYER_CACHE_DIR", None)

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
            except Exception as exc:  # noqa: BLE001
                rows.append({"unit_id": unit.name, "family": "unknown", "calls_used": 0, "elapsed_s": 0.0, "labels": {}, "agreement": None,
                             "fallback_reason": f"NumericSummary failed: {type(exc).__name__}: {exc}", "directions": {}, "established": {},
                             "n_evidence": 0, "n_established": 0})
                print(f"[{i}/{len(units)}] {unit.name}: numeric summary failed: {exc}", file=sys.stderr)
                continue
            signals = []
            for rep in range(max(1, args.repeat)):
                if server is not None:
                    server.reset_accounting()      # the real House issues a fresh per-unit token and allowance
                budget = CallBudget(limit=args.budget)
                run_env = dict(env)
                if args.repeat > 1 and args.mode == "dev" and rep > 0:   # repeat 0 fills the shared cache
                    run_env["TEXT_LAYER_CACHE_DIR"] = str(args.cache_dir / f"repeat{rep}")
                signals.append((read_text(unit, summary, budget, env=run_env, time_budget_s=args.time_budget, mode=text_mode), budget))
            signal, budget = signals[0]
            elapsed = time.monotonic() - t0
            L = signal.labels or {}
            agreement = (L.get("agreement") or {}).get("overall")
            keys = [labels_key(s.labels or {}) for s, _ in signals]
            rerun_agreement = (max(Counter(keys).values()) / len(keys)) if len(keys) > 1 else None   # modal share
            row = {
                "unit_id": summary.unit_id, "family": summary.family, "asof": summary.asof.isoformat(), "assets": list(summary.assets),
                "calls_used": signal.calls_used, "budget_used": budget.used, "elapsed_s": round(elapsed / max(1, args.repeat), 2),
                "fallback_reason": signal.fallback_reason, "labels": L, "agreement": agreement, "rerun_agreement": rerun_agreement,
                "directions": {a: v.get("direction") for a, v in (L.get("assets") or {}).items()},
                "established": {a: bool(v.get("direction_established")) for a, v in (L.get("assets") or {}).items()},
                "n_evidence": len(signal.evidence), "n_established": sum(e.established for e in signal.evidence),
            }
            rows.append(row)
            payload = {k: v for k, v in row.items() if k != "labels"}
            payload.update({"mode": args.mode, "model": env.get("MODEL_NAME", ""),
                            "numeric_summary": {"spot": summary.spot, "horizon_sd": {f"{a}@{h}": v for (a, h), v in summary.horizon_sd.items()},
                                                "vol_ratio": summary.vol_ratio, "target_type": summary.target_type, "value_unit": summary.value_unit},
                            "signal": signal_to_dict(signal)})
            (args.out / f"{summary.unit_id}.json").write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
            (args.out / f"{summary.unit_id}.md").write_text(signal.rationale_md)
            if not args.quiet:
                status = signal.fallback_reason or (f"{L.get('regime')}/{L.get('event_in_horizon')}/dis={L.get('disagreement')} "
                                                    f"dirs={row['directions']} agree={agreement}")
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
