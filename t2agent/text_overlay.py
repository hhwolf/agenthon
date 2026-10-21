"""Translate validated categorical labels using the fixed numeric-side table."""
from dataclasses import replace
import math
import os

from .contracts import NumericSummary, TextSignal
from . import text_map as T
from .text_layer import constants as C
from .text_layer.parse import RawScenario, RawSignal
from .text_layer.signal import (NUMERIC_PARAGRAPH_MAPPED, NUMERIC_PARAGRAPH_UNMAPPED,
                                Ledger, clamp_scenarios, mapping_rationale)


def lambda_from_env(env=None):
    raw = (os.environ if env is None else env).get(T.ENV_LAMBDA, T.DEFAULT_LAMBDA)
    try:
        value = float(raw)
        return min(1., max(0., value)) if math.isfinite(value) else T.DEFAULT_LAMBDA
    except (TypeError, ValueError):
        return T.DEFAULT_LAMBDA


def map_labels(labels, assets, *, lam=T.DEFAULT_LAMBDA, family=""):
    if not math.isfinite(lam) or not 0 <= lam <= 1:
        raise ValueError("lambda must be finite and in [0,1]")
    regime = labels.get("regime", "calm")
    event = labels.get("event_in_horizon", "none")
    if regime not in T.REGIME_VOL or event not in T.EVENT_VOL_FLOOR:
        raise ValueError("Unknown text regime/event")
    disagreement = bool(labels.get("disagreement", False))
    directions = {a: (labels.get("assets", {}).get(a) or {}).get("direction", "none") for a in assets}
    if any(d not in T.DIRECTION_DRIFT for d in directions.values()):
        raise ValueError("Unknown text direction")
    drift = {a: 0. if disagreement else T.DIRECTION_DRIFT[d] for a, d in directions.items()}
    vol = max(T.REGIME_VOL[regime], T.EVENT_VOL_FLOOR[event],
              T.DISAGREEMENT_VOL_FLOOR if disagreement else 1.)
    tail = max(T.REGIME_TAIL[regime], T.EVENT_TAIL[event])
    named_tail = (regime == "crisis" or family == "T2-F4") and any(drift.values())
    if named_tail:
        tail = max(tail, T.F4_TAIL_MULT)
    signs = {a: (1 if d > 0 else -1) for a, d in drift.items() if d} if named_tail else {}
    lines = [f"regime {regime}: vol {T.REGIME_VOL[regime]}, tail {T.REGIME_TAIL[regime]}; "
             f"event {event}: vol floor {T.EVENT_VOL_FLOOR[event]}, tail {T.EVENT_TAIL[event]}"]
    if disagreement:
        lines.append("disagreement: zero drift in every branch; symmetric tails; volatility floor 1.15 before lambda")
    if signs:
        lines.append(f"Named adverse tail signs {signs}; shared extreme-draw indicator, named-side expansion only")
    scenarios = []
    branches = labels.get("branches") or []
    binary = event == "scheduled_binary" and len(branches) == 2 and not disagreement
    if binary:
        probs = [float(b.get("prob", .5)) for b in branches]
        if any(not math.isfinite(p) or p < 0 for p in probs) or sum(probs) <= 0:
            raise ValueError("Invalid binary branch probabilities")
        p0 = min(T.BRANCH_PROB_CLIP[1], max(T.BRANCH_PROB_CLIP[0], probs[0]/sum(probs)))
        for branch, prob in zip(branches, (p0, 1-p0)):
            branch_signs = branch.get("signs") or {}
            if any(branch_signs.get(a, 0) not in (-1, 0, 1) for a in assets):
                raise ValueError("Branch signs must be -1, 0, or 1")
            d = {a: lam*T.BINARY_BRANCH_DRIFT*branch_signs.get(a, 0) for a in assets}
            scenarios.append(RawScenario(str(branch.get("label", "branch"))[:40], prob, d,
                                         1+lam*(vol-1), ()))
        lines.append(f"Binary branch probabilities {p0:.3f}/{1-p0:.3f}; signed +/-1 sd before lambda; one branch per draw")
    else:
        scenarios.append(RawScenario("text", 1., {a: lam*d for a, d in drift.items()}, 1+lam*(vol-1), ()))
        lines.extend(f"direction {a}={directions[a]}: {d:+.2f} sd before lambda" for a, d in drift.items())
    return RawSignal(tuple(scenarios), 1+lam*(tail-1), (), str(labels.get("summary", ""))), lines, signs, binary


def apply_text_map(signal: TextSignal, summary: NumericSummary, lam=T.DEFAULT_LAMBDA):
    if not math.isfinite(lam) or not 0 <= lam <= 1:
        raise ValueError("lambda must be finite and in [0,1]")
    labels = signal.labels or {}
    fallback_labels = labels.get("mode") == C.MODE_NOTES_ONLY_FALLBACK
    if lam == 0 or (signal.fallback_reason and not fallback_labels):
        neutral = TextSignal.neutral(summary.assets, signal.fallback_reason)
        result = replace(signal, scenarios=neutral.scenarios, tail_mult=1., tail_signs={}, branch_mixture=False)
        return signal if result == signal else result
    if labels.get("mode") in (None, "neutral"):
        return signal
    raw, lines, signs, binary = map_labels(labels, summary.assets, lam=lam, family=summary.family)
    if fallback_labels:
        lines.append("model path failed; deterministic card/corpus labels used (notes_only_fallback)")
    ledger = Ledger()
    scenarios, tail = clamp_scenarios(raw, summary.assets, any(e.established for e in signal.evidence), ledger,
                                     mean_limit=T.BINARY_MEAN_DRIFT_LIMIT if binary else .5)
    md = signal.rationale_md.replace(NUMERIC_PARAGRAPH_UNMAPPED, NUMERIC_PARAGRAPH_MAPPED, 1).rstrip()
    md += "\n" + mapping_rationale(summary, scenarios, tail, lines, ledger, lam)
    return replace(signal, scenarios=tuple(scenarios), tail_mult=tail, tail_signs=signs,
                   branch_mixture=binary, rationale_md=md)


def evidence_ledger(signal):
    """Always name established/inferred explicitly, including externally supplied signals."""
    lines = ["## Text evidence ledger", "", "| doc_id | timestamp | status | assets | claim |",
             "|---|---|---|---|---|"]
    def clean(value):
        return str(value).replace("|", "/").replace("\n", " ").replace("\r", " ")
    evidence = signal.get('evidence', ()) if isinstance(signal, dict) else signal.evidence
    for e in evidence:
        def get(name, default=''):
            return e.get(name, default) if isinstance(e, dict) else getattr(e, name, default)
        lines.append("| " + " | ".join(map(clean, (get('doc_id'), get('timestamp'),
            "established" if get('established', False) else "inferred", ", ".join(get('assets', ())), get('claim')))) + " |")
    if not evidence:
        lines.append("| — | — | no validated document evidence | — | Card cues are inferred; no document citation invented. |")
    return "\n".join(lines)
