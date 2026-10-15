"""Clamp a RawSignal into the TextSignal contract and write the rationale (docs/TEXT_LAYER.md §5, §8)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..contracts import Evidence, NumericSummary, Scenario, TextSignal
from . import constants as C
from .parse import RawEvidence, RawSignal


@dataclass
class Ledger:
    """Everything the rationale needs to show the arithmetic."""

    notes: list[str] = field(default_factory=list)      # corpus / pipeline notes
    clamps: list[str] = field(default_factory=list)     # each clamp applied, before -> after
    docs_read: list[str] = field(default_factory=list)  # "doc_id (type, date)"
    docs_dropped: list[str] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)
    cache_hits: int = 0
    requests: int = 0
    model_summary: str = ""


_DRIFT_DECIMALS = 6
_ROUNDING_MARGIN = 1e-5


def _clip(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def to_contract_evidence(items: list[RawEvidence]) -> tuple[Evidence, ...]:
    return tuple(Evidence(doc_id=e.doc_id, timestamp=e.timestamp, claim=e.claim, assets=tuple(e.assets),
                          direction=int(e.direction), established=bool(e.established)) for e in items)


def clamp_scenarios(raw: RawSignal, assets: tuple[str, ...], has_established: bool,
                    ledger: Ledger) -> tuple[list[Scenario], float]:
    """Apply the §5 clamps. Returns (scenarios, tail_mult)."""
    cands = [s for s in raw.scenarios if s.weight > 0]
    if not cands:
        ledger.clamps.append("no scenario with positive weight: using one neutral base scenario")
        return [Scenario("base", 1.0, {a: 0.0 for a in assets})], _clip(raw.tail_mult, C.TAIL_MULT_MIN, C.TAIL_MULT_MAX)
    # weights: normalise, drop tiny scenarios, renormalise (at most a few rounds)
    for _ in range(C.MAX_SCENARIOS + 1):
        total = sum(s.weight for s in cands)
        normalised = [s.weight / total for s in cands]
        small = [s for s, w in zip(cands, normalised) if w < C.SCENARIO_WEIGHT_MIN]
        if not small or len(cands) == 1:
            break
        for s in small:
            ledger.clamps.append(f"scenario '{s.label}' dropped: weight {s.weight / total:.3f} < {C.SCENARIO_WEIGHT_MIN}")
        cands = [s for s in cands if s not in small]
    if len(cands) > C.MAX_SCENARIOS:
        ledger.clamps.append(f"kept the {C.MAX_SCENARIOS} heaviest of {len(cands)} scenarios")
        cands = sorted(cands, key=lambda s: -s.weight)[: C.MAX_SCENARIOS]
    total = sum(s.weight for s in cands)
    weights = [s.weight / total for s in cands]

    drifts: list[dict[str, float]] = []
    for s in cands:
        d: dict[str, float] = {}
        for a in assets:
            v = float(s.drift_sd.get(a, 0.0))
            c = _clip(v, -C.DRIFT_SCENARIO_LIMIT, C.DRIFT_SCENARIO_LIMIT)
            if c != v:
                ledger.clamps.append(f"scenario '{s.label}' {a}: drift {v:+.3f} clamped to {c:+.3f} (|drift| <= {C.DRIFT_SCENARIO_LIMIT})")
            d[a] = c
        drifts.append(d)
    for a in assets:
        mean = sum(w * d[a] for w, d in zip(weights, drifts))
        if abs(mean) > C.DRIFT_MEAN_LIMIT:
            # Rescale slightly inside the bound so that rounding below cannot push the mean back over it.
            factor = (C.DRIFT_MEAN_LIMIT - _ROUNDING_MARGIN) / abs(mean)
            for d in drifts:
                d[a] = round(d[a] * factor, _DRIFT_DECIMALS)
            ledger.clamps.append(f"{a}: weighted mean drift {mean:+.3f} exceeds +/-{C.DRIFT_MEAN_LIMIT}; "
                                 f"all scenario drifts for {a} rescaled by {factor:.3f}")
    vols: list[float] = []
    for s in cands:
        v = _clip(s.vol_mult, C.VOL_MULT_MIN, C.VOL_MULT_MAX)
        if v != s.vol_mult:
            ledger.clamps.append(f"scenario '{s.label}': vol_mult {s.vol_mult:.3f} clamped to {v:.3f}")
        if v < C.VOL_MULT_INFERRED_FLOOR and not has_established:
            ledger.clamps.append(f"scenario '{s.label}': vol_mult {v:.3f} raised to {C.VOL_MULT_INFERRED_FLOOR:.1f}: "
                                 "no established evidence, inferred evidence cannot narrow the distribution")
            v = C.VOL_MULT_INFERRED_FLOOR
        vols.append(v)
    tail = _clip(raw.tail_mult, C.TAIL_MULT_MIN, C.TAIL_MULT_MAX)
    if tail != raw.tail_mult:
        ledger.clamps.append(f"tail_mult {raw.tail_mult:.3f} clamped to {tail:.3f}")
    scenarios = []
    labels: dict[str, int] = {}
    for s, w, d, v in zip(cands, weights, drifts, vols):
        label = s.label
        n = labels.get(label, 0)
        labels[label] = n + 1
        if n:
            label = f"{label} ({n + 1})"
        scenarios.append(Scenario(label=label, weight=round(w, 6), drift_sd={a: round(d[a], _DRIFT_DECIMALS) for a in assets},
                                  vol_mult=round(v, 4)))
    residual = 1.0 - sum(s.weight for s in scenarios)
    if abs(residual) > 1e-12:
        heaviest = max(range(len(scenarios)), key=lambda i: scenarios[i].weight)
        s = scenarios[heaviest]
        scenarios[heaviest] = Scenario(s.label, round(s.weight + residual, 6), s.drift_sd, s.vol_mult)
    for a in assets:  # defensive: the bound must hold exactly after all rounding
        mean = sum(s.weight * s.drift_sd[a] for s in scenarios)
        if abs(mean) > C.DRIFT_MEAN_LIMIT:
            factor = (C.DRIFT_MEAN_LIMIT - _ROUNDING_MARGIN) / abs(mean)
            scenarios = [Scenario(s.label, s.weight, {**s.drift_sd, a: round(s.drift_sd[a] * factor, _DRIFT_DECIMALS)}, s.vol_mult)
                         for s in scenarios]
    return scenarios, round(tail, 4)


def rank_evidence(items: list[RawEvidence], doc_order: dict[str, int], cap: int = C.MAX_EVIDENCE) -> list[RawEvidence]:
    """Established first, then by document priority; deduplicated; capped."""
    seen: set[tuple[str, str]] = set()
    unique: list[RawEvidence] = []
    for e in items:
        key = (e.doc_id, e.claim.casefold())
        if key not in seen:
            seen.add(key)
            unique.append(e)
    unique.sort(key=lambda e: (not e.established, doc_order.get(e.doc_id, 10**6)))
    return unique[:cap]


def rationale(summary: NumericSummary, scenarios: list[Scenario], tail_mult: float, evidence: list[RawEvidence],
              raw: RawSignal | None, ledger: Ledger, *, neutral_reason: str | None = None) -> str:
    assets = summary.assets
    lines = [f"## Text layer — {summary.unit_id}", ""]
    lines.append(f"As-of {summary.asof.isoformat()}; family {summary.family}; House requests used: {ledger.requests}"
                 + (f" ({ledger.cache_hits} served from the dev cache)" if ledger.cache_hits else "") + ".")
    if neutral_reason:
        lines += ["", f"**Neutral signal** — {neutral_reason}. The forecast is numeric-only."]
    lines += ["", "### Documents", ""]
    lines.append(f"Read {len(ledger.docs_read)} document(s), highest priority first: " + "; ".join(ledger.docs_read)
                 if ledger.docs_read else "No documents were read.")
    if ledger.docs_dropped:
        lines.append(f"Not sent (budget): {'; '.join(ledger.docs_dropped)}.")
    if ledger.notes:
        lines.append("Corpus notes: " + " ".join(ledger.notes[:12]) + (" ..." if len(ledger.notes) > 12 else ""))
    lines += ["", "### Evidence (E = established in the document, I = inferred from tone)", ""]
    if evidence:
        lines.append("| # | doc_id | date | kind | assets | dir | E/I | claim |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for i, e in enumerate(evidence, 1):
            lines.append(f"| {i} | {e.doc_id} | {e.timestamp} | {e.kind} | {','.join(e.assets) or '-'} | "
                         f"{e.direction:+d} | {'E' if e.established else 'I'} | {e.claim.replace('|', '/')} |")
    else:
        lines.append("No cited evidence survived validation.")
    n_est = sum(1 for e in evidence if e.established)
    lines.append("")
    lines.append(f"Established items: {n_est}; inferred items: {len(evidence) - n_est}. "
                 f"Narrowing (vol_mult < 1) {'allowed' if n_est else 'not allowed'}.")
    lines += ["", "### Scenarios", ""]
    lines.append("| scenario | weight | " + " | ".join(f"drift_sd {a}" for a in assets) + " | vol_mult | evidence |")
    lines.append("|---|---|" + "---|" * len(assets) + "---|---|")
    raw_by_label = {s.label: s for s in (raw.scenarios if raw else ())}
    for s in scenarios:
        cited = raw_by_label.get(s.label.split(" (")[0])
        ev = ",".join(str(i) for i in cited.evidence) if cited and cited.evidence else "-"
        lines.append(f"| {s.label} | {s.weight:.3f} | " + " | ".join(f"{s.drift_sd.get(a, 0.0):+.3f}" for a in assets)
                     + f" | {s.vol_mult:.3f} | {ev} |")
    lines.append("")
    lines.append(f"tail_mult: {tail_mult:.3f} (applies to the outer 5% of draws).")
    if ledger.model_summary:
        lines += ["", f"Model summary: {ledger.model_summary}"]
    lines += ["", "### Adjustments and clamps applied", ""]
    lines += [f"- {c}" for c in ledger.clamps] or ["- none; the model's values were inside every bound"]
    lines += ["", "### Adjustment ledger", ""]
    for a in assets:
        mean = sum(s.weight * s.drift_sd.get(a, 0.0) for s in scenarios)
        terms = " + ".join(f"{s.weight:.3f}x{s.drift_sd.get(a, 0.0):+.3f}" for s in scenarios)
        lines.append(f"- {a}: mean drift = {terms} = {mean:+.4f} horizon-sd")
        for h in summary.horizons:
            sd = summary.horizon_sd.get((a, h))
            if sd is None:
                continue
            spot = summary.spot.get(a, 0.0)
            shift = mean * sd
            lines.append(f"  - horizon {h}: horizon_sd {sd:.6g} -> centre shift {shift:+.6g} value units"
                         + (f" (spot {spot:.6g} -> {spot + shift:.6g})" if spot else ""))
    mix_vol = sum(s.weight * s.vol_mult for s in scenarios)
    lines.append(f"- mixture vol_mult = {' + '.join(f'{s.weight:.3f}x{s.vol_mult:.3f}' for s in scenarios)} = {mix_vol:.4f}; "
                 f"tail_mult = {tail_mult:.3f}")
    lines.append(f"- requests: {ledger.requests} admitted"
                 + (f", {ledger.cache_hits} cache hits" if ledger.cache_hits else "")
                 + f"; calls: " + ", ".join(
                     f"{c.get('purpose')}={'cached' if c.get('cached') else c.get('status')}"
                     + (f"x{c.get('attempts')}" if (c.get('attempts') or 0) > 1 else "")
                     for c in ledger.calls))
    return "\n".join(lines).rstrip() + "\n"


def compose_signal(raw: RawSignal, evidence: list[RawEvidence], summary: NumericSummary, ledger: Ledger) -> TextSignal:
    has_established = any(e.established for e in evidence)
    scenarios, tail = clamp_scenarios(raw, summary.assets, has_established, ledger)
    ledger.model_summary = raw.summary
    md = rationale(summary, scenarios, tail, evidence, raw, ledger)
    return TextSignal(scenarios=tuple(scenarios), tail_mult=tail, evidence=to_contract_evidence(evidence),
                      rationale_md=md, calls_used=ledger.requests)
