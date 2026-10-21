"""Build a ``NumericSummary`` from the numeric engine (used by text_v1 and the dev sweep).

The numeric owner may build the summary differently in production; this mirrors numeric_v1's own
moments so the text layer sees the same horizon sd the engine will scale.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np

from .. import m0, numeric_v1
from ..contracts import NumericSummary
from ..io import read_card, read_panels

RECENT_WINDOW = 63


def _vol_ratio(series, level: bool) -> float:
    """Recent (63 obs) / long-run sd of the steps numeric_v1 models: level changes, published returns, or log
    changes for a positive monthly index (numeric_v1 models those in log space)."""
    if level:
        gaps = series.index.to_series().diff().dt.days.dropna()
        monthly_index = len(gaps) > 0 and float(gaps.median()) > 20 and bool((series > 0).all())
        increments = (np.log(series).diff() if monthly_index else series.diff()).dropna()
    else:
        increments = series.dropna()
    if len(increments) < RECENT_WINDOW + 5:
        return 1.0
    long_run = float(increments.std(ddof=1))
    recent = float(increments.tail(RECENT_WINDOW).std(ddof=1))
    if not np.isfinite(long_run) or long_run <= 0 or not np.isfinite(recent):
        return 1.0
    return float(np.clip(recent / long_run, 0.2, 5.0))


def numeric_summary_from(card: dict, panels: dict, asof: str, *, samples=None) -> NumericSummary:
    targets = card["targets"]
    assets = tuple(targets["asset_ids"])
    horizons = tuple(int(h) for h in targets["horizons"])
    level = targets.get("target_type", "level") == "level"
    grid = [(a, h) for a in assets for h in horizons]
    try:
        prepared = numeric_v1.prepare(card, panels, asof)
        mean, cov, log_cells, _ = numeric_v1.moments(prepared, numeric_v1.selected_config())
        histories = prepared.histories
    except Exception:
        dist = m0.distribution(card, panels, asof)
        mean, cov, histories = dist.mean, dist.covariance, dist.histories
        log_cells = np.zeros(len(grid), dtype=bool)
    sd = np.sqrt(np.maximum(np.diag(np.asarray(cov, dtype=float)), 0.0))
    spot = {a: float(histories[a].iloc[-1]) if level else 0.0 for a in assets}
    horizon_sd = {}
    for k, (a, h) in enumerate(grid):
        value = float(sd[k])
        if log_cells[k]:
            # numeric_v1 models this cell in log space and applies text drift to the level draws' own sd;
            # approximate the level sd around the engine's centre exp(mean), not the spot
            value *= float(np.exp(np.clip(mean[k], -50, 50)))
        horizon_sd[(a, h)] = value
    if samples is not None:
        # The text overlay acts on completed draws, including the v1.1 tail engine.
        horizon_sd = dict(zip(grid, map(float, np.asarray(samples).std(axis=0, ddof=1))))
    family = str(card.get("metadata", {}).get("category") or card.get("forecast_spec", {}).get("card_family") or "")
    return NumericSummary(
        unit_id=str(card["task"]["id"]),
        asof=date.fromisoformat(str(asof)[:10]),
        family=family,
        target_type=str(targets.get("target_type", "level")),
        value_unit=str(targets.get("value_unit", "")),
        assets=assets,
        horizons=horizons,
        spot=spot,
        horizon_sd=horizon_sd,
        vol_ratio={a: _vol_ratio(histories[a], level) for a in assets},
        card_description=str(card.get("metadata", {}).get("description", "")),
        card_text_notes=str(card.get("text", {}).get("notes", "")),
    )


def numeric_summary_for_unit(unit_dir: Path | str) -> NumericSummary:
    unit_dir = Path(unit_dir)
    card = read_card(unit_dir / "card.toml")
    panels = read_panels(unit_dir / "panels")
    return numeric_summary_from(card, panels, str(card["provenance"]["data_cutoff"]))
