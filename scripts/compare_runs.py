#!/usr/bin/env python
"""Paired comparison of t2eval runs (e.g. numeric_v1 vs text_v1 arms) on the same roster.

    .venv/bin/python scripts/compare_runs.py numeric_v1 t2agent.text_v1:forecast_notes_only_l05 [more ...]
    .venv/bin/python scripts/compare_runs.py .eval/runs/eval-practice-numeric_v1-xxxx .eval/runs/eval-practice-...

Arguments are forecaster names (latest ``eval-practice`` run under ``.eval/runs`` is used) or run
directories. The first is the baseline. Reports mean, median, caps (score == 8), paired mean delta
with a bootstrap 95% CI over cards, wins/losses, and breakdowns by family; writes markdown + JSON
to ``--out`` (default ``.eval/ablations/text_<timestamp>.md``).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / ".eval" / "runs"


def resolve(arg: str, mode: str) -> Path:
    p = Path(arg)
    if p.is_dir():
        return p
    key = f"{mode}-{arg.replace(':', '_')}-"
    cands = sorted((d for d in RUNS.iterdir() if d.name.startswith(key)), key=lambda d: d.stat().st_mtime)
    if not cands:
        sys.exit(f"no {mode} run found for {arg!r} under {RUNS}")
    return cands[-1]


def load(run: Path) -> pd.DataFrame:
    df = pd.read_csv(run / "cards.csv")
    df["score"] = df["score"].astype(float)
    df["capped"] = df["score"] >= 8.0 - 1e-9
    return df.set_index("unit_id")


def bootstrap_ci(delta: np.ndarray, n: int = 4000, seed: int = 20261015) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    means = np.array([rng.choice(delta, len(delta), replace=True).mean() for _ in range(n)])
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def compare(base: pd.DataFrame, other: pd.DataFrame, label: str) -> dict:
    common = base.index.intersection(other.index)
    b, o = base.loc[common], other.loc[common]
    delta = (o["score"] - b["score"]).to_numpy()
    lo, hi = bootstrap_ci(delta) if len(delta) > 1 else (float("nan"), float("nan"))
    rows = {}
    for fam, idx in b.groupby("family").groups.items():
        d = (o.loc[idx, "score"] - b.loc[idx, "score"]).to_numpy()
        rows[fam] = {"cards": int(len(idx)), "base_mean": round(float(b.loc[idx, "score"].mean()), 4),
                     "mean": round(float(o.loc[idx, "score"].mean()), 4), "delta": round(float(d.mean()), 4),
                     "base_caps": int(b.loc[idx, "capped"].sum()), "caps": int(o.loc[idx, "capped"].sum()),
                     "wins": int((d < -1e-9).sum()), "losses": int((d > 1e-9).sum())}
    worst = (o["score"] - b["score"]).sort_values(ascending=False).head(5)
    best = (o["score"] - b["score"]).sort_values().head(5)
    return {
        "label": label, "cards": int(len(common)),
        "base_mean": round(float(b["score"].mean()), 4), "mean": round(float(o["score"].mean()), 4),
        "base_median": round(float(b["score"].median()), 4), "median": round(float(o["score"].median()), 4),
        "delta_mean": round(float(delta.mean()), 4), "delta_ci95": [round(lo, 4), round(hi, 4)],
        "base_caps": int(b["capped"].sum()), "caps": int(o["capped"].sum()),
        "wins": int((delta < -1e-9).sum()), "losses": int((delta > 1e-9).sum()), "ties": int((np.abs(delta) <= 1e-9).sum()),
        "changed_cards": int((np.abs(delta) > 1e-9).sum()),
        "by_family": rows,
        "worst_cards": {k: round(float(v), 4) for k, v in worst.items() if v > 1e-9},
        "best_cards": {k: round(float(v), 4) for k, v in best.items() if v < -1e-9},
    }


def markdown(results: list[dict], base_name: str) -> str:
    lines = [f"# Paired practice comparison vs `{base_name}`", "",
             "| arm | cards | base mean | mean | Δ mean | 95% CI | base caps | caps | wins | losses | changed |",
             "|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|"]
    for r in results:
        lines.append(f"| {r['label']} | {r['cards']} | {r['base_mean']} | {r['mean']} | {r['delta_mean']:+.4f} | "
                     f"[{r['delta_ci95'][0]:+.4f}, {r['delta_ci95'][1]:+.4f}] | {r['base_caps']} | {r['caps']} | {r['wins']} | {r['losses']} | {r['changed_cards']} |")
    for r in results:
        lines += ["", f"## {r['label']} by family", "", "| family | cards | base mean | mean | Δ | base caps | caps | wins | losses |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for fam, s in r["by_family"].items():
            lines.append(f"| {fam} | {s['cards']} | {s['base_mean']} | {s['mean']} | {s['delta']:+.4f} | {s['base_caps']} | {s['caps']} | {s['wins']} | {s['losses']} |")
        if r["worst_cards"]:
            lines.append(f"\nLargest regressions: {r['worst_cards']}")
        if r["best_cards"]:
            lines.append(f"\nLargest gains: {r['best_cards']}")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("runs", nargs="+", help="baseline first: forecaster names or run directories")
    p.add_argument("--mode", default="eval-practice")
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)
    paths = [resolve(a, args.mode) for a in args.runs]
    frames = [load(p) for p in paths]
    results = [compare(frames[0], f, Path(args.runs[i]).name if Path(args.runs[i]).is_dir() else args.runs[i]) for i, f in enumerate(frames) if i]
    md = markdown(results, args.runs[0])
    out = args.out or (ROOT / ".eval" / "ablations" / f"compare_{time.strftime('%Y%m%d-%H%M%S')}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)
    out.with_suffix(".json").write_text(json.dumps({"baseline": str(paths[0]), "runs": [str(x) for x in paths], "results": results}, indent=1) + "\n")
    print(md)
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
