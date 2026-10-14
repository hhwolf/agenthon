from __future__ import annotations

import json
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd


def read_card(path: Path) -> dict:
    card = tomllib.loads(path.read_text())
    spec = path.with_name("forecast_spec.json")
    if spec.exists():
        card["forecast_spec"] = json.loads(spec.read_text())
    return card


def read_panels(path: Path) -> dict[str, pd.DataFrame]:
    files = sorted(path.glob("*.parquet"))
    if not files:
        files = sorted(path.parent.glob("*.parquet"))
    if not files:
        raise ValueError(f"No panels found at {path}")
    return {p.name: pd.read_parquet(p) for p in files}


def sample_frame(card: dict, samples: np.ndarray) -> pd.DataFrame:
    assets, horizons = card["targets"]["asset_ids"], card["targets"]["horizons"]
    samples = np.asarray(samples, dtype=np.float64).reshape(-1, len(assets) * len(horizons))
    n, d = samples.shape
    return pd.DataFrame({
        "draw": np.repeat(np.arange(n, dtype=np.int32), d),
        "asset": np.tile(np.repeat(assets, len(horizons)), n),
        "horizon": np.tile(np.tile(np.asarray(horizons, dtype=np.int32), len(assets)), n),
        "value": samples.ravel(),
    })


def write_forecast(card: dict, frame: pd.DataFrame, out: Path, rationale: str | None = None) -> None:
    """Write the contract triplet; reject incomplete or nonfinite joint draws."""
    rationale = rationale or frame.attrs.get("rationale")
    if not rationale or not rationale.strip():
        raise ValueError("A non-blank forecast rationale is required")
    assets, horizons = card["targets"]["asset_ids"], card["targets"]["horizons"]
    frame = frame[["draw", "asset", "horizon", "value"]].copy()
    for name in ("draw", "horizon"):
        values = frame[name].to_numpy()
        if not np.isfinite(values).all() or not np.equal(values, values.astype(np.int32)).all():
            raise ValueError(f"{name} must contain int32 values")
    frame = frame.astype({"draw": "int32", "asset": "str", "horizon": "int32", "value": "float64"})
    n = frame.draw.nunique()
    floor = max(200, card.get("scoring", {}).get("params", {}).get("n_draws_min", 200))
    if n < floor or frame.draw.min() < 0 or not np.isfinite(frame.value).all():
        raise ValueError("Invalid draw count, IDs, or nonfinite values")
    grid = {(a, h) for a in assets for h in horizons}
    if (set(zip(frame.asset, frame.horizon)) != grid
            or frame.duplicated(["draw", "asset", "horizon"]).any()
            or len(frame) != n * len(grid)):
        raise ValueError("Every joint draw must contain the exact card grid")
    out.parent.mkdir(parents=True, exist_ok=True)
    # DataFrame attrs contain a rationale and are not part of the parquet contract.
    frame.attrs = {}
    frame.to_parquet(out, index=False)
    out.with_name("forecast_meta.json").write_text(json.dumps({
        "unit_id": card["task"]["id"], "asof": str(card["provenance"]["data_cutoff"]),
        "asset_ids": assets, "horizons": horizons, "representation": "samples", "n_draws": n,
    }, indent=2) + "\n")
    out.with_name("forecast_rationale.md").write_text(rationale.rstrip() + "\n")
    if sum(p.stat().st_size for p in out.parent.iterdir() if p.is_file()) > 64 * 1024**2:
        raise ValueError("Output exceeds 64 MiB")
