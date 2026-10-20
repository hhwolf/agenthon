"""Label -> number table (Phase 4 item 1). Constants only; starting values from SOLVER-PLAYBOOK §3.

``apply_text_map(signal, summary, lam)`` turns the categorical labels a Phase 3 ``TextSignal`` carries
into scenarios, vol and tail multipliers, shrunk toward neutral by ``lam`` (0 = numeric only, 1 = full
table) and passed through the §5 clamps. A neutral or label-free signal is returned unchanged, so
``apply_text_signal`` reproduces the numeric forecast exactly in that case.
"""

from __future__ import annotations

from dataclasses import replace

from .contracts import NumericSummary, TextSignal
from .text_layer import constants as C
from .text_layer.parse import RawScenario, RawSignal
from .text_layer.signal import (NUMERIC_PARAGRAPH_MAPPED, NUMERIC_PARAGRAPH_UNMAPPED, Ledger, clamp_scenarios,
                                mapping_rationale)

DEFAULT_LAMBDA = 0.5                      # balanced-risk hedge (C2); 1.0 only if the ablation is consistent
ENV_LAMBDA = "TEXT_LAYER_LAMBDA"

REGIME_VOL = {"calm": 1.0, "elevated": 1.25, "crisis": 1.6}
REGIME_TAIL = {"calm": 1.0, "elevated": 1.0, "crisis": 1.5}
EVENT_VOL_FLOOR = {"none": 1.0, "scheduled_binary": 1.15, "ongoing": 1.15}
EVENT_TAIL = {"none": 1.0, "scheduled_binary": 1.25, "ongoing": 1.0}
DIRECTION_DRIFT = {"strong_down": -0.5, "down": -0.25, "none": 0.0, "up": 0.25, "strong_up": 0.5}
BINARY_BRANCH_DRIFT = 1.0                 # per-asset drift of each branch, times the branch sign
BRANCH_PROB_CLIP = (0.2, 0.8)
DISAGREEMENT_VOL_FLOOR = 1.15             # disagreement -> vol_mult >= 1.15 ...
DISAGREEMENT_DRIFT_FACTOR = 0.0           # ... and drift scaled by this (0 = no drift; the playbook's "do not average tone")
CRISIS_SHOCK_WEIGHT = 0.2                 # F4/crisis with a named side: low-weight shock scenario on that side
CRISIS_SHOCK_DRIFT_MULT = 2.0
CRISIS_SHOCK_VOL = 1.8
TUNABLE = ("REGIME_VOL", "REGIME_TAIL", "EVENT_VOL_FLOOR", "EVENT_TAIL", "DIRECTION_DRIFT", "BINARY_BRANCH_DRIFT",
           "BRANCH_PROB_CLIP", "DISAGREEMENT_VOL_FLOOR", "DISAGREEMENT_DRIFT_FACTOR", "CRISIS_SHOCK_WEIGHT",
           "CRISIS_SHOCK_DRIFT_MULT", "CRISIS_SHOCK_VOL")


def table_constants(overrides: dict | None = None) -> dict:
    """The label->number table as a dict, with optional pre-declared overrides for ablation variants."""
    cfg = {name: globals()[name] for name in TUNABLE}
    for key, value in (overrides or {}).items():
        if key not in cfg:
            raise KeyError(f"unknown table constant {key!r}")
        cfg[key] = value
    return cfg


def lambda_from_env(env=None) -> float:
    import os

    raw = (os.environ if env is None else env).get(ENV_LAMBDA, DEFAULT_LAMBDA)
    try:
        return min(1.0, max(0.0, float(raw)))
    except (TypeError, ValueError):
        return DEFAULT_LAMBDA


def _shrink(value: float, lam: float, neutral: float = 0.0) -> float:
    return neutral + (value - neutral) * lam


def map_labels(labels: dict, assets: tuple[str, ...], *, lam: float = DEFAULT_LAMBDA,
               table: dict | None = None) -> tuple[RawSignal, list[str]]:
    """Table lookup -> RawSignal (before clamps) plus the table rows used, for the rationale."""
    T = table_constants(table)
    REGIME_VOL, REGIME_TAIL, EVENT_VOL_FLOOR, EVENT_TAIL = T["REGIME_VOL"], T["REGIME_TAIL"], T["EVENT_VOL_FLOOR"], T["EVENT_TAIL"]
    DIRECTION_DRIFT, BINARY_BRANCH_DRIFT, BRANCH_PROB_CLIP = T["DIRECTION_DRIFT"], T["BINARY_BRANCH_DRIFT"], T["BRANCH_PROB_CLIP"]
    DISAGREEMENT_VOL_FLOOR, DISAGREEMENT_DRIFT_FACTOR = T["DISAGREEMENT_VOL_FLOOR"], T["DISAGREEMENT_DRIFT_FACTOR"]
    CRISIS_SHOCK_WEIGHT, CRISIS_SHOCK_DRIFT_MULT, CRISIS_SHOCK_VOL = T["CRISIS_SHOCK_WEIGHT"], T["CRISIS_SHOCK_DRIFT_MULT"], T["CRISIS_SHOCK_VOL"]
    lines: list[str] = []
    if table:
        lines.append(f"table overrides: {table}")
    regime = str(labels.get("regime") or "calm")
    event = str(labels.get("event_in_horizon") or "none")
    disagreement = bool(labels.get("disagreement", False))
    per_asset = labels.get("assets") or {}
    drift = {a: DIRECTION_DRIFT.get(str((per_asset.get(a) or {}).get("direction", "none")), 0.0) for a in assets}
    for a in assets:
        d = (per_asset.get(a) or {}).get("direction", "none")
        if d != "none":
            lines.append(f"direction {a} = {d} -> drift {DIRECTION_DRIFT.get(d, 0.0):+.2f} sd")
    if disagreement:
        drift = {a: d * DISAGREEMENT_DRIFT_FACTOR for a, d in drift.items()}
        lines.append(f"disagreement -> drift x{DISAGREEMENT_DRIFT_FACTOR:g}, vol_mult >= {DISAGREEMENT_VOL_FLOOR}")
    vol = max(REGIME_VOL.get(regime, 1.0), EVENT_VOL_FLOOR.get(event, 1.0), DISAGREEMENT_VOL_FLOOR if disagreement else 1.0)
    tail = max(REGIME_TAIL.get(regime, 1.0), EVENT_TAIL.get(event, 1.0))
    lines.append(f"regime {regime} -> vol_mult {REGIME_VOL.get(regime, 1.0)}, tail {REGIME_TAIL.get(regime, 1.0)}; "
                 f"event {event} -> vol floor {EVENT_VOL_FLOOR.get(event, 1.0)}, tail {EVENT_TAIL.get(event, 1.0)}")
    scenarios: list[RawScenario] = []
    branches = labels.get("branches") or []
    if event == "scheduled_binary" and len(branches) == 2:
        p0 = float(branches[0].get("prob", 0.5))
        p0 = min(BRANCH_PROB_CLIP[1], max(BRANCH_PROB_CLIP[0], p0))
        probs = (p0, 1.0 - p0)
        lines.append(f"scheduled_binary -> two branches, probs clipped to {BRANCH_PROB_CLIP}: {probs[0]:.2f}/{probs[1]:.2f}, "
                     f"branch drift +/-{BINARY_BRANCH_DRIFT} sd by sign")
        for b, p in zip(branches, probs):
            signs = b.get("signs") or {}
            d = {a: _shrink(drift[a] + BINARY_BRANCH_DRIFT * float(signs.get(a, 0) or 0), lam) for a in assets}
            scenarios.append(RawScenario(str(b.get("label") or "branch")[:40], p, d, _shrink(vol, lam, 1.0), ()))
    elif regime == "crisis" and any(drift[a] != 0.0 for a in assets):
        lines.append(f"crisis with a named side -> shock scenario weight {CRISIS_SHOCK_WEIGHT}, drift x{CRISIS_SHOCK_DRIFT_MULT}, "
                     f"vol {CRISIS_SHOCK_VOL}")
        scenarios.append(RawScenario("crisis base", 1.0 - CRISIS_SHOCK_WEIGHT, {a: _shrink(drift[a], lam) for a in assets},
                                     _shrink(vol, lam, 1.0), ()))
        scenarios.append(RawScenario("crisis shock", CRISIS_SHOCK_WEIGHT,
                                     {a: _shrink(drift[a] * CRISIS_SHOCK_DRIFT_MULT, lam) for a in assets},
                                     _shrink(CRISIS_SHOCK_VOL, lam, 1.0), ()))
    else:
        scenarios.append(RawScenario("text", 1.0, {a: _shrink(drift[a], lam) for a in assets}, _shrink(vol, lam, 1.0), ()))
    return RawSignal(tuple(scenarios), _shrink(tail, lam, 1.0), (), str(labels.get("summary") or "")), lines


def apply_text_map(signal: TextSignal, summary: NumericSummary, lam: float = DEFAULT_LAMBDA,
                   table: dict | None = None) -> TextSignal:
    """Return ``signal`` with scenarios/tail set from its labels (or unchanged when there is nothing to map).

    Neutral signals (offline, no documents, hard failures without a pre-pass) are returned untouched; notes-only
    labels produced as a fallback after a model failure are mapped like any other labels.
    """
    labels = signal.labels or {}
    if labels.get("mode") in (None, "neutral") or lam <= 0.0:
        return signal
    raw, lines = map_labels(labels, summary.assets, lam=lam, table=table)
    ledger = Ledger()
    has_established = any(e.established for e in signal.evidence)
    scenarios, tail = clamp_scenarios(raw, summary.assets, has_established, ledger)
    md = signal.rationale_md.replace(NUMERIC_PARAGRAPH_UNMAPPED, NUMERIC_PARAGRAPH_MAPPED, 1).rstrip() + "\n" \
        + mapping_rationale(summary, scenarios, tail, lines, ledger, lam)
    return replace(signal, scenarios=tuple(scenarios), tail_mult=tail, rationale_md=md)
