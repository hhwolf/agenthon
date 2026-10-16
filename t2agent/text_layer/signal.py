"""Clamps (docs/TEXT_LAYER.md §5), evidence ranking, and the rationale text (§8)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..contracts import Evidence, NumericSummary, Scenario
from . import constants as C
from .parse import RawEvidence, RawSignal

_DRIFT_DECIMALS = 6
_ROUNDING_MARGIN = 1e-5
NUMERIC_PARAGRAPH_HEADER = "### Numeric adjustment"
NUMERIC_PARAGRAPH_UNMAPPED = ("This signal carries labels only: its own scenario is neutral (drift 0, vol_mult 1, tail_mult 1), so "
                              "applied as-is it reproduces the numeric forecast exactly. The forecast used the mapping below only "
                              "if a 'Label -> number mapping' section follows.")
NUMERIC_PARAGRAPH_MAPPED = ("The forecast used the label -> number mapping in the next section (t2agent/text_map.py); the scenarios, "
                            "vol_mult and tail_mult there are what adjusted the numeric draws.")


@dataclass
class Ledger:
    """Everything the rationale needs to show the arithmetic and the audit trail."""

    mode: str = C.MODE_LABELS
    notes: list[str] = field(default_factory=list)      # corpus / pipeline notes
    clamps: list[str] = field(default_factory=list)     # each clamp applied, before -> after
    docs_read: list[str] = field(default_factory=list)  # "doc_id (type, date)"
    docs_dropped: list[str] = field(default_factory=list)
    prepass_lines: list[str] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)
    cache_hits: int = 0
    requests: int = 0
    elapsed_s: float = 0.0
    model_summary: str = ""


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


def _evidence_table(evidence: list[RawEvidence]) -> list[str]:
    if not evidence:
        return ["No cited evidence survived validation."]
    lines = ["| # | doc_id | date | kind | assets | dir | E/I | claim |", "|---|---|---|---|---|---|---|---|"]
    for i, e in enumerate(evidence, 1):
        lines.append(f"| {i} | {e.doc_id} | {e.timestamp} | {e.kind} | {','.join(e.assets) or '-'} | "
                     f"{e.direction:+d} | {'E' if e.established else 'I'} | {e.claim.replace('|', '/')} |")
    return lines


def rationale_labels(summary: NumericSummary, labels: dict, evidence: list[RawEvidence], ledger: Ledger,
                     *, neutral_reason: str | None = None) -> str:
    """Rationale for a Phase 3 signal: documents, pre-pass facts, evidence, labels, votes."""
    assets = summary.assets
    lines = [f"## Text layer — {summary.unit_id}", ""]
    lines.append(f"As-of {summary.asof.isoformat()}; family {summary.family}; mode {labels.get('mode', ledger.mode)}; "
                 f"House requests used: {ledger.requests}"
                 + (f" ({ledger.cache_hits} served from the dev cache)" if ledger.cache_hits else "")
                 + (f"; wall time {ledger.elapsed_s:.1f} s" if ledger.elapsed_s else "") + ".")
    if neutral_reason:
        lines += ["", f"**Neutral signal** — {neutral_reason}. The forecast is numeric-only."]
    lines += ["", "### Documents", ""]
    lines.append(f"Read {len(ledger.docs_read)} document(s), highest priority first: " + "; ".join(ledger.docs_read)
                 if ledger.docs_read else "No documents were sent to the model.")
    if ledger.docs_dropped:
        lines.append(f"Not sent (budget): {'; '.join(ledger.docs_dropped)}.")
    if ledger.notes:
        lines.append("Pipeline notes: " + " ".join(ledger.notes[:12]) + (" ..." if len(ledger.notes) > 12 else ""))
    if ledger.prepass_lines:
        lines += ["", "### Deterministic pre-pass (card prose, corpus index, lexicons)", ""]
        lines += [f"- {l}" for l in ledger.prepass_lines]
    lines += ["", "### Evidence (E = established in the document, I = inferred from tone)", ""]
    lines += _evidence_table(evidence)
    n_est = sum(1 for e in evidence if e.established)
    lines += ["", f"Established items: {n_est}; inferred items: {len(evidence) - n_est}."]
    events = labels.get("events") or []
    disagreements = labels.get("disagreements") or []
    if events or disagreements:
        lines += ["", "### Reader notes (from the extraction calls)", ""]
        lines += [f"- scheduled event: {e}" for e in events[:8]]
        lines += [f"- disagreement: {d}" for d in disagreements[:6]]
    lines += ["", "### Labels (the model classifies; magnitudes come from the fixed table in text_map)", ""]
    lines.append("| field | label | agreement |")
    lines.append("|---|---|---|")
    agreement = labels.get("agreement", {}) or {}
    for key in ("regime", "event_in_horizon", "disagreement"):
        lines.append(f"| {key} | {labels.get(key)} | {agreement.get(key, '-')} |")
    for a in assets:
        al = (labels.get("assets") or {}).get(a, {})
        ev = al.get("evidence") or []
        lines.append(f"| direction {a} | {al.get('direction', 'none')}"
                     f"{' (established)' if al.get('direction_established') else ''}"
                     f"{' cites ' + ','.join(str(i) for i in ev) if ev else ''} | {agreement.get(f'direction:{a}', '-')} |")
    for b in labels.get("branches") or []:
        lines.append(f"| branch '{b.get('label')}' | prob {b.get('prob')}; signs {b.get('signs')} | - |")
    runs = labels.get("runs", 0)
    if runs:
        lines.append("")
        lines.append(f"Self-consistency: {runs} synthesis run(s); overall agreement {agreement.get('overall', '-')}; "
                     f"votes: {labels.get('votes', {})}")
    if labels.get("summary"):
        lines += ["", f"Model summary: {labels['summary']}"]
    lines += ["", NUMERIC_PARAGRAPH_HEADER, "", NUMERIC_PARAGRAPH_UNMAPPED]
    lines.append("")
    lines.append("Requests: " + (", ".join(
        f"{c.get('purpose')}={'cached' if c.get('cached') else c.get('status')}"
        + (f"x{c.get('attempts')}" if (c.get('attempts') or 0) > 1 else "") for c in ledger.calls) or "none"))
    return "\n".join(lines).rstrip() + "\n"


def mapping_rationale(summary: NumericSummary, scenarios: list[Scenario], tail_mult: float, table_lines: list[str],
                      ledger: Ledger, lam: float) -> str:
    """Appendix written by text_map: the table rows used, λ, clamps, and the adjustment ledger."""
    assets = summary.assets
    lines = ["", f"### Label -> number mapping (λ = {lam:g})", ""]
    lines += [f"- {l}" for l in table_lines] or ["- no mapping applied"]
    lines += ["", "| scenario | weight | " + " | ".join(f"drift_sd {a}" for a in assets) + " | vol_mult |",
              "|---|---|" + "---|" * len(assets) + "---|"]
    for s in scenarios:
        lines.append(f"| {s.label} | {s.weight:.3f} | " + " | ".join(f"{s.drift_sd.get(a, 0.0):+.3f}" for a in assets) + f" | {s.vol_mult:.3f} |")
    lines.append("")
    lines.append(f"tail_mult: {tail_mult:.3f} (outer 5% of draws).")
    if ledger.clamps:
        lines += ["", "Clamps applied:"] + [f"- {c}" for c in ledger.clamps]
    lines += ["", "Adjustment ledger:"]
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
                         + (f" (about {100.0 * shift / abs(spot):+.2f}% of spot {spot:.6g}; applied to the engine's own centre)" if spot else ""))
    mix_vol = sum(s.weight * s.vol_mult for s in scenarios)
    lines.append(f"- mixture vol_mult = {mix_vol:.4f}; tail_mult = {tail_mult:.3f}")
    return "\n".join(lines).rstrip() + "\n"
