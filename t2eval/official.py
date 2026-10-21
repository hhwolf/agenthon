"""Call the vendor CLI entrypoints in-process (same argv, no copied scoring math)."""
import contextlib
import importlib
import io
import json
import os
from pathlib import Path

from qfbench2_track_forecasting import cli, scoring

from t2agent.io import read_card, read_panels, write_forecast


def score(card: Path, forecast: Path, realized: Path | None = None) -> dict:
    args = ["score", "--card", str(card), "--forecast", str(forecast)]
    if realized is not None:
        args += ["--realized", str(realized)]
    capture = io.StringIO()
    with contextlib.redirect_stdout(capture):
        status = scoring._main(args)
    payload = json.loads(capture.getvalue())
    if status not in (0, 1):
        raise RuntimeError(f"Official scorer failed: {payload}")
    return payload


def run_forecaster(name: str, unit: Path, out: Path, n_draws=500, seed=None, *, text=True) -> None:
    card = read_card(unit / "card.toml")
    asof = str(card["provenance"]["data_cutoff"])
    if name == "reference":
        if seed is None:
            seed = int(os.environ.get("QFBENCH_SEED", "0"))
        args = ["--panels", str(unit / "panels"), "--text", str(unit / "text"),
                "--asof", asof, "--out", str(out), "--seed", str(seed),
                "--n-draws", str(n_draws)]
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(args)
        return
    module, function = (f"t2agent.{name}", "forecast") if name in {"m0", "numeric_v1", "numeric_v1_1", "numeric_alignment"} else name.split(":", 1)
    forecaster = getattr(importlib.import_module(module), function)
    frame = forecaster(card, read_panels(unit / "panels"), unit / "text" if text else None,
                       asof, n_draws, seed)
    write_forecast(card, frame, out)


def normalize(payload: dict, divisors: dict[str, float], cells: int) -> dict:
    if not payload.get("admissible"):
        return {"score": 8.0, "unclipped": 8.0, "failed": True}
    raw_names = {"marginal": "marginal_crps", "joint": "joint_variogram", "tail": "tail_penalty"}
    normalized = {k: payload[v] / divisors[k] for k, v in raw_names.items()}
    # Exact renormalization of 0.5/0.2; docs abbreviate these as 0.714/0.286.
    weights = {"marginal": 5/7, "joint": 0, "tail": 2/7} if cells == 1 else {
        "marginal": 0.5, "joint": 0.3, "tail": 0.2}
    value = sum(weights[k]*normalized[k] for k in weights)
    return {"score": min(8.0, max(0.0, value)), "unclipped": value, "failed": False,
            **{f"normalized_{k}": v for k, v in normalized.items()}}
