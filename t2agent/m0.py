"""M0 as published in docs/M0-BASELINE.md §3; no fitting or tuning beyond that spec."""
from __future__ import annotations

import os
import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .io import sample_frame


def history(panels: dict[str, pd.DataFrame], asset: str, asof: str) -> pd.Series:
    for name in sorted(panels):
        df = panels[name]
        column = "asset" if "asset" in df else "asset_id"
        rows = df.loc[df[column].astype(str) == asset, ["date", "value"]].copy()
        if rows.empty:
            continue
        rows["date"] = pd.to_datetime(rows.date, errors="raise")
        if rows.date.isna().any():
            raise ValueError(f"Unparseable date for {asset}")
        rows = rows.loc[rows.date <= pd.Timestamp(asof)].sort_values("date").tail(300)
        if rows.empty or rows.date.duplicated().any():
            raise ValueError(f"Missing or duplicated history for {asset} in {name}")
        s = rows.set_index("date").value.astype(float)
        if not np.isfinite(s).all():
            raise ValueError(f"Nonfinite history for {asset}")
        return s
    raise ValueError(f"No panel contains {asset}")


def intervals(s: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    days = np.diff(s.index.to_numpy()).astype("timedelta64[D]").astype(float)
    good = days <= max(10 * np.median(days), 5) if len(days) else np.array([], dtype=bool)
    return days, good


def cell_metadata(card: dict, field: str, question_field: str) -> dict[tuple[str, int], str]:
    """Merge explicit grid and question metadata, refusing disagreement."""
    result = {}
    assets, horizons = card["targets"]["asset_ids"], card["targets"]["horizons"]
    grid = {(a, h) for a in assets for h in horizons}

    def add(key, value):
        value = str(value)
        if key not in grid or (key in result and result[key] != value):
            raise ValueError(f"Conflicting {field} metadata at {key}")
        result[key] = value

    for source in (card, card.get("forecast_spec", {})):
        targets = source.get("targets", {})
        if field in targets:
            hs = targets.get("horizons", horizons)
            values = targets[field]
            if len(values) != len(hs):
                raise ValueError(f"{field} must align with horizons")
            for a in targets.get("asset_ids", assets):
                for h, value in zip(hs, values, strict=True):
                    add((a, h), value)
        seen = set()
        for row in source.get("questions", []):
            if question_field in row:
                key = (row["asset"], row["horizon"])
                if key in seen:
                    raise ValueError(f"Duplicate question {key}")
                seen.add(key)
                add(key, row[question_field])
    return result


def horizon_steps(card: dict, histories: dict[str, pd.Series]) -> np.ndarray:
    periods = cell_metadata(card, "observation_periods", "observation_period")
    dates = cell_metadata(card, "target_dates", "target_date")
    result = []
    for asset in card["targets"]["asset_ids"]:
        s = histories[asset]
        gaps, valid = intervals(s)
        for h in card["targets"]["horizons"]:
            key = (asset, h)
            if key in periods:
                label = periods[key]
                if len(label) != 7 or pd.Period(label, freq="M").strftime("%Y-%m") != label:
                    raise ValueError(f"Malformed observation period: {label}")
                month = pd.Period(label, freq="M")
                if key in dates and pd.Period(dates[key], freq="M") != month:
                    raise ValueError("Observation month disagrees with target date")
                steps = month.ordinal - s.index[-1].to_period("M").ordinal
                if steps <= 0:
                    raise ValueError("Observation month must follow the anchor month")
            else:
                steps = h
                target = pd.to_datetime(dates.get(key), errors="coerce")
                if len(s) >= 3 and target is not None and not pd.isna(target) and valid.any():
                    spacing = gaps[valid].mean()
                    counted = (target.to_period("M").ordinal - s.index[-1].to_period("M").ordinal
                               if spacing > 20 else round((target - s.index[-1]).days / spacing))
                    if counted > 0 and max(counted, h) / max(min(counted, h), 1) >= 2:
                        steps = counted
            result.append(steps)
    return np.asarray(result, dtype=float)


@dataclass
class Distribution:
    mean: np.ndarray
    covariance: np.ndarray
    factor: np.ndarray
    steps: np.ndarray
    histories: dict[str, pd.Series]
    drift: np.ndarray
    step_covariance: np.ndarray
    aligned_rows: int
    diagonal_fallback: bool


def distribution(card: dict, panels: dict[str, pd.DataFrame], asof: str) -> Distribution:
    if str(card["provenance"]["data_cutoff"]) != str(asof):
        raise ValueError("asof must equal the card cutoff")
    assets = sorted(card["targets"]["asset_ids"])
    histories = {a: history(panels, a, asof) for a in assets}
    kind = card["targets"].get("target_type", "level")
    if kind not in {"level", "log_return"}:
        raise ValueError(f"Unsupported target_type {kind}")
    steps_by_asset = {}
    for asset, s in histories.items():
        _, good = intervals(s)
        if kind == "log_return" and s.abs().median() >= 0.2:
            raise ValueError("M0 tripwire: median absolute return >= 0.2")
        # Literal §3.2: returns are rows, NOT log1p(rows). See BUILD_LOG ambiguity.
        increments = s.diff() if kind == "level" else s
        steps_by_asset[asset] = increments.iloc[1:].where(good)
    aligned = pd.concat(steps_by_asset, axis=1).dropna()
    if len(aligned) < 2:
        raise ValueError("Fewer than two date-aligned steps; M0 estimate is undefined")
    mu = aligned.mean().to_numpy()
    sigma = np.atleast_2d(np.cov(aligned.to_numpy(), rowvar=False, ddof=1))
    indexes = [assets.index(a) for a in card["targets"]["asset_ids"] for _ in card["targets"]["horizons"]]
    steps = horizon_steps(card, histories)
    anchor = np.array([histories[assets[i]].iloc[-1] if kind == "level" else 0.0 for i in indexes])
    mean = anchor + steps * mu[indexes]
    cov = np.minimum.outer(steps, steps) * sigma[np.ix_(indexes, indexes)]
    cov += np.eye(len(mean)) * 1e-10
    cov += np.eye(len(mean)) * 1e-9
    fallback = False
    try:
        factor = np.linalg.cholesky(cov)
    except np.linalg.LinAlgError:
        fallback = True
        cov = np.diag(np.diag(cov))
        factor = np.linalg.cholesky(cov)
    return Distribution(mean, cov, factor, steps, histories, mu, sigma, len(aligned), fallback)


def resolve_seed(card: dict, seed: int | None) -> int:
    if seed is not None:
        return int(seed)
    if "QFBENCH_SEED" in os.environ:
        return int(os.environ["QFBENCH_SEED"])
    return zlib.crc32(card["task"]["id"].encode()) & 0x7FFFFFFF


def forecast(card: dict, panels: dict[str, pd.DataFrame], text_dir: Path | None,
             asof: str, n_draws: int = 500, seed: int | None = None) -> pd.DataFrame:
    model = distribution(card, panels, asof)
    seed = resolve_seed(card, seed)
    z = np.random.default_rng(seed).standard_normal((n_draws, len(model.mean)))
    samples = model.mean + z @ model.factor.T
    frame = sample_frame(card, samples)
    rows = []
    for i, (asset, horizon) in enumerate((a, h) for a in card["targets"]["asset_ids"]
                                      for h in card["targets"]["horizons"]):
        s = model.histories[asset]
        ai = sorted(model.histories).index(asset)
        anchor = s.iloc[-1] if card["targets"]["target_type"] == "level" else 0
        rows.append(f"| {asset} | {horizon} | {s.index[0].date()}–{s.index[-1].date()} | "
                    f"{anchor:.10g} | {model.steps[i]:g} | {model.drift[ai]:.10g} | "
                    f"{model.mean[i]:.10g} | {np.sqrt(model.covariance[i,i]):.10g} |")
    frame.attrs["rationale"] = (
        f"# M0 numeric forecast: {card['task']['id']}\n\n"
        f"1. Cutoff {asof}; use each asset's last 300 observations, with dates shown below.\n"
        "2. Level steps are differences; return steps are the published rows. Drop gaps over "
        "max(10 × median spacing, 5 days), then intersect step dates across assets.\n"
        f"3. Estimate sample covariance and mean on {model.aligned_rows} shared steps. "
        "Use joint Gaussian paths with covariance min(s, t) × step covariance and 1.1e-9 jitter. "
        f"Diagonal fallback: {model.diagonal_fallback}. Seed: {seed}; draws: {n_draws}.\n"
        "4. No text was read; no text adjustments. Centre = anchor + steps × drift.\n\n"
        "| Asset | Horizon key | History dates | Anchor | Steps | Drift per step | Centre | SD |\n"
        "|---|---|---|---|---|---|---|---|\n" + "\n".join(rows)
    )
    return frame
