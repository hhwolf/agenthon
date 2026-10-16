"""Shared contract between the numeric engine and the text layer. See docs/TEXT_LAYER.md."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

MAX_ADMITTED_REQUESTS = 20  # House allows 25 per unit; keep 5 spare


@dataclass(frozen=True)
class NumericSummary:
    unit_id: str
    asof: date
    family: str  # "T2-F1" .. "T2-F4"
    target_type: str  # "level" | "log_return"
    value_unit: str
    assets: tuple[str, ...]
    horizons: tuple[int, ...]
    spot: dict[str, float]  # last observed level; 0.0 for log_return targets
    horizon_sd: dict[tuple[str, int], float]  # numeric engine's sd per (asset, horizon)
    vol_ratio: dict[str, float]  # recent vol / long-run vol, per asset
    card_description: str
    card_text_notes: str


@dataclass(frozen=True)
class Evidence:
    doc_id: str
    timestamp: str
    claim: str
    assets: tuple[str, ...]
    direction: int  # -1, 0, +1 on the quoted series
    established: bool


@dataclass(frozen=True)
class Scenario:
    label: str
    weight: float
    drift_sd: dict[str, float]  # per asset, in horizon-sd units
    vol_mult: float = 1.0


@dataclass(frozen=True)
class TextSignal:
    scenarios: tuple[Scenario, ...]
    tail_mult: float = 1.0
    evidence: tuple[Evidence, ...] = ()
    rationale_md: str = ""
    calls_used: int = 0
    fallback_reason: str | None = None  # set whenever the signal is neutral because of a failure
    labels: dict = field(default_factory=dict)  # Phase 3 categorical labels; text_map turns them into numbers

    @staticmethod
    def neutral(assets: tuple[str, ...], reason: str | None = None) -> TextSignal:
        return TextSignal(
            scenarios=(Scenario("base", 1.0, {a: 0.0 for a in assets}),),
            rationale_md="Text layer neutral: forecast is numeric-only.",
            fallback_reason=reason,
        )


@dataclass
class CallBudget:
    limit: int = MAX_ADMITTED_REQUESTS
    used: int = field(default=0)

    def spend(self) -> bool:
        """Call immediately before sending a request; False means do not send."""
        if self.used >= self.limit:
            return False
        self.used += 1
        return True
