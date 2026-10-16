"""Label schema (Phase 3 B2/B3), validation of model output, and majority voting across runs."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Sequence

from . import constants as C
from .parse import ParseError, RawEvidence, _bool, _num


@dataclass(frozen=True)
class Branch:
    label: str
    prob: float
    signs: dict[str, int]


@dataclass(frozen=True)
class AssetLabel:
    direction: str = "none"
    direction_established: bool = False
    evidence: tuple[int, ...] = ()


@dataclass(frozen=True)
class Labels:
    regime: str = "calm"
    event_in_horizon: str = "none"
    disagreement: bool = False
    assets: dict[str, AssetLabel] = field(default_factory=dict)
    branches: tuple[Branch, ...] = ()
    summary: str = ""
    evidence_used: tuple[int, ...] = ()

    def is_neutral(self) -> bool:
        return (self.regime == "calm" and self.event_in_horizon == "none" and not self.disagreement
                and all(a.direction == "none" for a in self.assets.values()))


def neutral_labels(assets: Sequence[str]) -> Labels:
    return Labels(assets={a: AssetLabel() for a in assets})


def _enum(value, allowed: Sequence[str], default: str) -> str:
    s = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {"strong_up": "strong_up", "strongly_up": "strong_up", "strong_down": "strong_down", "strongly_down": "strong_down",
               "neutral": "none", "flat": "none", "unclear": "none", "no_event": "none", "scheduled": "scheduled_binary",
               "binary": "scheduled_binary", "scheduled_binary_event": "scheduled_binary", "normal": "calm", "high": "elevated",
               "stressed": "crisis", "stress": "crisis"}
    s = aliases.get(s, s)
    return s if s in allowed else default


def _sign(value) -> int:
    v = _num(value)
    if v is None:
        s = str(value).strip().lower()
        return 1 if s in {"+", "up", "positive", "higher"} else -1 if s in {"-", "down", "negative", "lower"} else 0
    return 1 if v > 0 else -1 if v < 0 else 0


def parse_labels(obj: dict, assets: Sequence[str], evidence: Sequence[RawEvidence]) -> Labels:
    """Coerce one synthesis reply into Labels; raise ParseError only when the shape is unusable.

    A directional call must cite at least one evidence item or it collapses to ``none`` (uncited
    claims are dropped); ``direction_established`` additionally requires a cited established item.
    """
    if not isinstance(obj, dict):
        raise ParseError("labels reply is not an object")
    if "regime" not in obj and "assets" not in obj and "event_in_horizon" not in obj:
        raise ParseError("labels reply has none of regime/event_in_horizon/assets")
    n = len(evidence)
    regime = _enum(obj.get("regime"), C.REGIMES, "calm")
    event = _enum(obj.get("event_in_horizon", obj.get("event")), C.EVENTS, "none")
    disagreement = _bool(obj.get("disagreement", False))
    lower = {a.lower(): a for a in assets}
    raw_assets = obj.get("assets") or {}
    if isinstance(raw_assets, list):  # tolerate [{"asset": "JPY", ...}, ...]
        raw_assets = {str(x.get("asset") or x.get("id") or ""): x for x in raw_assets if isinstance(x, dict)}
    per_asset: dict[str, AssetLabel] = {}
    used: set[int] = set()
    for a in assets:
        entry = None
        for k, v in (raw_assets.items() if isinstance(raw_assets, dict) else []):
            if lower.get(str(k).strip().lower()) == a and isinstance(v, dict):
                entry = v
                break
        if entry is None:
            per_asset[a] = AssetLabel()
            continue
        direction = _enum(entry.get("direction"), C.DIRECTIONS, "none")
        raw_cites = entry.get("evidence") or []
        if not isinstance(raw_cites, (list, tuple)):
            raw_cites = [raw_cites]
        cited = tuple(sorted({int(_num(e)) for e in raw_cites if _num(e) is not None and 1 <= int(_num(e)) <= n}))
        established = _bool(entry.get("direction_established", False))
        if direction != "none" and not cited:
            direction = "none"          # uncited directional claim is dropped
        if direction == "none":
            established = False
        elif established and not any(evidence[i - 1].established for i in cited):
            established = False         # established needs a cited established item
        used.update(cited)
        per_asset[a] = AssetLabel(direction, established, cited)
    branches: list[Branch] = []
    raw_branches = obj.get("branches") or []
    if isinstance(raw_branches, dict):
        raw_branches = list(raw_branches.values())
    if not isinstance(raw_branches, (list, tuple)):
        raw_branches = []
    if event == "scheduled_binary":
        for b in list(raw_branches)[:4]:
            if not isinstance(b, dict):
                continue
            prob = _num(b.get("prob", b.get("weight", b.get("probability"))))
            if prob is None or prob <= 0:
                continue
            signs_in = b.get("signs") or b.get("direction") or {}
            signs = {a: 0 for a in assets}
            if isinstance(signs_in, dict):
                for k, v in signs_in.items():
                    key = lower.get(str(k).strip().lower())
                    if key is not None:
                        signs[key] = _sign(v)
            elif len(assets) == 1:
                signs[assets[0]] = _sign(signs_in)
            branches.append(Branch(str(b.get("label") or f"branch {len(branches) + 1}")[:40], float(prob), signs))
        if len(branches) != 2:
            event = "none" if not branches else "ongoing"   # a binary event needs exactly two branches
            branches = []
        else:
            total = branches[0].prob + branches[1].prob
            branches = [Branch(b.label, b.prob / total, b.signs) for b in branches]
    summary = str(obj.get("summary") or "").strip()[:600]
    return Labels(regime, event, disagreement, per_asset, tuple(branches), summary, tuple(sorted(used)))


def _mode(values: list, default):
    """Majority value (>= MAJORITY_MIN_RUNS agreeing); ties or no majority -> default."""
    if not values:
        return default, 0.0
    counts = Counter(values)
    best, n = counts.most_common(1)[0]
    if n < min(C.MAJORITY_MIN_RUNS, len(values)) or (len(values) >= 2 and list(counts.values()).count(n) > 1):
        return default, n / len(values)
    return best, n / len(values)


def vote(runs: Sequence[Labels], assets: Sequence[str]) -> tuple[Labels, dict, dict]:
    """Majority vote across synthesis runs. Returns (labels, agreement, votes)."""
    runs = [r for r in runs if r is not None]
    if not runs:
        return neutral_labels(assets), {"overall": 0.0, "runs": 0}, {}
    agreement: dict[str, float] = {}
    votes: dict[str, list] = {}
    regime, agreement["regime"] = _mode([r.regime for r in runs], "calm")
    votes["regime"] = [r.regime for r in runs]
    event, agreement["event_in_horizon"] = _mode([r.event_in_horizon for r in runs], "none")
    votes["event_in_horizon"] = [r.event_in_horizon for r in runs]
    disagreement, agreement["disagreement"] = _mode([r.disagreement for r in runs], False)
    votes["disagreement"] = [r.disagreement for r in runs]
    per_asset: dict[str, AssetLabel] = {}
    for a in assets:
        dirs = [r.assets.get(a, AssetLabel()).direction for r in runs]
        direction, agreement[f"direction:{a}"] = _mode(dirs, "none")
        votes[f"direction:{a}"] = dirs
        established = False
        cited: tuple[int, ...] = ()
        if direction != "none":
            agreeing = [r.assets[a] for r in runs if r.assets.get(a) and r.assets[a].direction == direction]
            established = sum(1 for x in agreeing if x.direction_established) * 2 >= len(agreeing) and any(
                x.direction_established for x in agreeing)
            cited = tuple(sorted({i for x in agreeing for i in x.evidence}))
        per_asset[a] = AssetLabel(direction, established, cited)
    branches: tuple[Branch, ...] = ()
    if event == "scheduled_binary":
        binary_runs = [r for r in runs if r.event_in_horizon == "scheduled_binary" and len(r.branches) == 2]
        if binary_runs:
            ref = binary_runs[0].branches

            def agreement_score(a: Branch, b: Branch) -> int:
                return sum(a.signs.get(x, 0) * b.signs.get(x, 0) for x in assets)

            def ordered(r: Labels) -> tuple[Branch, Branch]:
                """Align this run's two branches with the reference run's by total sign agreement over all assets."""
                b0, b1 = r.branches
                straight = agreement_score(b0, ref[0]) + agreement_score(b1, ref[1])
                swapped = agreement_score(b1, ref[0]) + agreement_score(b0, ref[1])
                return (b1, b0) if swapped > straight else (b0, b1)

            pairs = [ordered(r) for r in binary_runs]
            out = []
            for idx in range(2):
                prob = sum(p[idx].prob for p in pairs) / len(pairs)
                signs = {a: _mode([p[idx].signs.get(a, 0) for p in pairs], 0)[0] for a in assets}
                out.append(Branch(pairs[0][idx].label, prob, signs))
            total = out[0].prob + out[1].prob
            branches = tuple(Branch(b.label, b.prob / total, b.signs) for b in out)
        else:
            event = "none"
    summary = max((r.summary for r in runs), key=len, default="")
    used = tuple(sorted({i for r in runs for i in r.evidence_used}))
    agreement["overall"] = round(sum(agreement.values()) / len(agreement), 4) if agreement else 0.0
    agreement["runs"] = len(runs)
    return Labels(regime, event, disagreement, per_asset, branches, summary, used), agreement, votes


def labels_to_dict(labels: Labels, *, mode: str, agreement: dict | None = None, votes: dict | None = None,
                   prepass: dict | None = None, extra: dict | None = None) -> dict:
    out = {
        "schema": C.LABELS_SCHEMA_VERSION,
        "mode": mode,
        "regime": labels.regime,
        "event_in_horizon": labels.event_in_horizon,
        "disagreement": bool(labels.disagreement),
        "assets": {a: {"direction": v.direction, "direction_established": bool(v.direction_established),
                       "evidence": list(v.evidence)} for a, v in labels.assets.items()},
        "branches": [{"label": b.label, "prob": round(b.prob, 4), "signs": dict(b.signs)} for b in labels.branches],
        "summary": labels.summary,
        "runs": (agreement or {}).get("runs", 0),
        "agreement": {k: v for k, v in (agreement or {}).items() if k != "runs"},
        "votes": votes or {},
        "prepass": prepass or {},
    }
    if extra:
        out.update(extra)
    return out
