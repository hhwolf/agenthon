"""Build a ``NumericSummary`` for a practice unit from the numeric engine (dev / evaluation helper).

The numeric owner builds the summary in production; this mirrors that construction so the text
layer can be exercised and swept on the practice units without touching the forecaster.
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
    increments = (series.diff() if level else series).dropna()
    if len(increments) < RECENT_WINDOW + 5:
        return 1.0
    long_run = float(increments.std(ddof=1))
    recent = float(increments.tail(RECENT_WINDOW).std(ddof=1))
    if not np.isfinite(long_run) or long_run <= 0 or not np.isfinite(recent):
        return 1.0
    return float(np.clip(recent / long_run, 0.2, 5.0))


def numeric_summary_for_unit(unit_dir: Path | str) -> NumericSummary:
    unit_dir = Path(unit_dir)
    card = read_card(unit_dir / "card.toml")
    panels = read_panels(unit_dir / "panels")
    asof = str(card["provenance"]["data_cutoff"])
    targets = card["targets"]
    assets = tuple(targets["asset_ids"])
    horizons = tuple(int(h) for h in targets["horizons"])
    level = targets.get("target_type", "level") == "level"
    grid = [(a, h) for a in assets for h in horizons]
    try:
        prepared = numeric_v1.prepare(card, panels, asof)
        _, cov, log_cells, _ = numeric_v1.moments(prepared, numeric_v1.selected_config())
        histories = prepared.histories
    except Exception:
        dist = m0.distribution(card, panels, asof)
        cov, histories = dist.covariance, dist.histories
        log_cells = np.zeros(len(grid), dtype=bool)
    sd = np.sqrt(np.maximum(np.diag(np.asarray(cov, dtype=float)), 0.0))
    spot = {a: float(histories[a].iloc[-1]) if level else 0.0 for a in assets}
    horizon_sd = {}
    for k, (a, h) in enumerate(grid):
        value = float(sd[k])
        if log_cells[k] and spot[a]:
            value *= abs(spot[a])  # log-space cell -> approximate level units
        horizon_sd[(a, h)] = value
    family = str(card.get("metadata", {}).get("category") or card.get("forecast_spec", {}).get("card_family") or "")
    return NumericSummary(
        unit_id=str(card["task"]["id"]),
        asof=date.fromisoformat(asof[:10]),
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
