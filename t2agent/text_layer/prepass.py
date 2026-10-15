"""Deterministic pre-pass (Phase 3 B4): facts from the card and corpus index without an LLM.

* scheduled events (votes, referendums, elections, meetings, decisions, deadlines) with dates, flagged
  when they fall inside the forecast horizon
* latest central-bank decision/statement per bank, document recency
* lexicon cues (hawkish / dovish / crisis / binary) in the card prose and the latest decisions
* ``labels_from_prepass`` — the notes-only label set used as fallback and as the B4 ablation arm
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..contracts import NumericSummary
from . import constants as C
from .corpus import CorpusDoc

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"])}
_MONTHS.update({m[:3]: i for m, i in list(_MONTHS.items())})
_MONTHS["sept"] = 9
_MONTH_RE = "(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_RANGE = r"(?:\s*[-\u2013\u2014]\s*\d{1,2}(?:st|nd|rd|th)?)?"   # "18-19" / "19–20" day ranges
_DATE_PATTERNS = [
    re.compile(r"\b(?P<d>\d{1,2})(?:st|nd|rd|th)?" + _RANGE + r"\s+(?P<m>" + _MONTH_RE + r")\.?,?\s*(?P<y>\d{4})?\b", re.I),   # 23 June 2016
    re.compile(r"\b(?P<m>" + _MONTH_RE + r")\.?\s+(?P<d>\d{1,2})(?:st|nd|rd|th)?" + _RANGE + r",?\s*(?P<y>\d{4})?\b", re.I),   # June 23, 2016
    re.compile(r"\b(?P<y>\d{4})-(?P<mn>\d{2})-(?P<d>\d{2})\b"),                                                                 # 2016-06-23
]
# Event kinds are regexes over the lower-cased context window around a date. Binary kinds are the
# two-outcome political events; routine FOMC "voting for the action" language must not match.
EVENT_KINDS: dict[str, tuple[str, ...]] = {
    "referendum": (r"\breferend(?:um|a)\b", r"\bplebiscite\b"),
    "election": (r"\belections?\b", r"\bballot\b", r"\bpolls? (?:open|close)\b", r"\bpresidential (?:race|contest|election)\b"),
    "vote": (r"\bvote (?:on|to leave|to remain|to approve|to ratify|of (?:no )?confidence)\b", r"\bno-confidence\b",
             r"\bparliament(?:ary)? vote\b", r"\bcongress(?:ional)? vote\b", r"\bleave or remain\b"),
    "policy_meeting": (r"\bfomc meeting\b", r"\bpolicy meeting\b", r"\bmpc meeting\b", r"\bgoverning council meeting\b",
                       r"\bmonetary policy meeting\b", r"\brate decision\b", r"\bpolicy decision\b", r"\bnext meeting\b",
                       r"\bmeeting (?:of the committee )?would be held\b", r"\bmeets on\b", r"\bwill meet\b"),
    "deadline": (r"\bdeadline\b", r"\bexpir(?:es|y|ation)\b", r"\bfiscal cliff\b", r"\bdebt ceiling\b", r"\bshutdown\b"),
    "release": (r"\bscheduled to be released\b", r"\breleased on\b", r"\bdue (?:on|out)\b", r"\bwill be published\b",
                r"\bdata release\b", r"\brelease of the minutes\b"),
    "summit": (r"\bsummit\b", r"\bhearing\b", r"\btestimony\b", r"\bpress conference\b"),
}
_EVENT_RES = {k: [re.compile(pat) for pat in pats] for k, pats in EVENT_KINDS.items()}
BINARY_KINDS = ("referendum", "election", "vote")
HAWKISH = ("hike", "hikes", "raise rates", "raising rates", "tighten", "tightening", "restrictive", "ongoing increases",
           "further increases", "upside risks to inflation", "inflation risks", "taper", "tapering", "less accommodative")
DOVISH = ("cut", "cuts", "lower rates", "ease", "easing", "accommodative", "stimulus", "quantitative easing",
          "asset purchases", "downside risks", "patient", "negative rates", "dovish")
CRISIS = ("crisis", "turmoil", "stress", "panic", "collapse", "default", "contagion", "liquidity", "emergency",
          "pandemic", "lockdown", "unprecedented", "bailout", "bank run", "insolvency", "shock", "capitulation")
BINARY = ("referendum", "vote", "election", "ballot", "binary", "hike or hold", "leave or remain", "coin flip")
REGIME_WORDS = ("regime", "pivot", "shift", "turning point", "inflection")
_BANKS = (
    ("fomc", "Fed"), ("federal reserve", "Fed"), ("fed_", "Fed"), ("fed-", "Fed"), ("frb", "Fed"),
    ("boj", "BoJ"), ("bank of japan", "BoJ"), ("boe", "BoE"), ("bank of england", "BoE"), ("mpc", "BoE"),
    ("ecb", "ECB"), ("rba", "RBA"), ("boc", "BoC"), ("bank of canada", "BoC"), ("snb", "SNB"),
    ("riksbank", "Riksbank"), ("norges", "Norges Bank"), ("rbnz", "RBNZ"), ("pboc", "PBoC"), ("rbi", "RBI"),
    ("bcb", "BCB"), ("copom", "BCB"), ("banxico", "Banxico"), ("sarb", "SARB"), ("bok", "BoK"),
)


@dataclass(frozen=True)
class ScheduledEvent:
    kind: str
    text: str
    source: str
    event_date: date | None
    inside_horizon: bool | None

    def line(self) -> str:
        when = self.event_date.isoformat() if self.event_date else "date not stated"
        where = "inside horizon" if self.inside_horizon else ("outside horizon" if self.inside_horizon is False else "timing unknown")
        return f"{when} ({where}) {self.kind}: {self.text} [{self.source}]"


@dataclass
class Prepass:
    asof: date
    horizon_end: date
    horizon_days: int
    scheduled_events: list[ScheduledEvent] = field(default_factory=list)
    latest_decisions: dict[str, dict] = field(default_factory=dict)
    newest_doc_days: int | None = None
    docs_within_30d: int = 0
    n_docs: int = 0
    cues: dict[str, int] = field(default_factory=dict)
    card_event_flag: bool = False
    card_binary_kind: bool = False
    off_topic_docs: list[str] = field(default_factory=list)

    @property
    def events_inside(self) -> list[ScheduledEvent]:
        return [e for e in self.scheduled_events if e.inside_horizon]

    @property
    def binary_event_inside(self) -> bool:
        """A dated two-outcome event inside the horizon, or the card prose itself naming such a setup."""
        return any(e.kind in BINARY_KINDS for e in self.events_inside) or self.card_binary_kind

    def summary_lines(self) -> list[str]:
        lines = [f"horizon window: {self.asof.isoformat()} -> {self.horizon_end.isoformat()} (~{self.horizon_days} calendar days)"]
        inside = self.events_inside
        if inside:
            lines.append("scheduled events inside the horizon: " + "; ".join(e.line() for e in inside[:6]))
        other = [e for e in self.scheduled_events if not e.inside_horizon][:4]
        if other:
            lines.append("other dated events mentioned: " + "; ".join(e.line() for e in other))
        if self.latest_decisions:
            lines.append("latest decision/statement per bank: " + "; ".join(
                f"{b}: {v['doc_id']} ({v['timestamp']}, {v['days_before_asof']}d before as-of)" for b, v in self.latest_decisions.items()))
        lines.append(f"documents: {self.n_docs}; newest {self.newest_doc_days if self.newest_doc_days is not None else '?'} days before as-of; "
                     f"{self.docs_within_30d} within 30 days" + (f"; off-topic by asset terms: {', '.join(self.off_topic_docs[:6])}" if self.off_topic_docs else ""))
        cues = {k: v for k, v in self.cues.items() if v}
        if cues:
            lines.append("lexicon cues in card prose and latest decisions: " + ", ".join(f"{k}={v}" for k, v in cues.items()))
        if self.card_binary_kind:
            lines.append("card prose names a two-outcome event (referendum/election/vote) in the setup")
        elif self.card_event_flag:
            lines.append("card prose flags a scheduled risk event")
        return lines

    def to_dict(self) -> dict:
        return {
            "horizon_end": self.horizon_end.isoformat(), "horizon_days": self.horizon_days,
            "scheduled_events": [e.line() for e in self.scheduled_events[:12]],
            "events_inside_horizon": len(self.events_inside), "binary_event_inside": self.binary_event_inside,
            "latest_decisions": self.latest_decisions, "newest_doc_days": self.newest_doc_days,
            "docs_within_30d": self.docs_within_30d, "n_docs": self.n_docs, "cues": self.cues,
            "card_event_flag": self.card_event_flag, "card_binary_kind": self.card_binary_kind,
            "off_topic_docs": self.off_topic_docs,
        }


def horizon_window(summary: NumericSummary) -> tuple[date, int]:
    """Calendar window covered by the horizons (business days x 1.45 + slack, at least MIN_HORIZON_DAYS)."""
    max_h = max(summary.horizons) if summary.horizons else 21
    days = max(C.MIN_HORIZON_DAYS, int(max_h * C.HORIZON_CALENDAR_FACTOR) + C.HORIZON_SLACK_DAYS)
    return summary.asof + timedelta(days=days), days


def _parse_match(m: re.Match, asof: date) -> date | None:
    g = m.groupdict()
    try:
        day = int(g.get("d") or 0)
        if g.get("mn"):
            month = int(g["mn"])
        else:
            month = _MONTHS.get((g.get("m") or "").lower()[:3], 0) if (g.get("m") or "").lower()[:4] != "sept" else 9
        year = int(g["y"]) if g.get("y") else None
    except (TypeError, ValueError):
        return None
    if not (1 <= day <= 31) or not (1 <= month <= 12):
        return None
    if year is None:  # "23 June" -> the next occurrence on or after the as-of year
        year = asof.year
        try:
            if date(year, month, day) < asof - timedelta(days=60):
                year += 1
        except ValueError:
            return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def find_events(text: str, source: str, asof: date, horizon_end: date, *, window: int = 140,
                max_events: int = 12) -> list[ScheduledEvent]:
    """Dated events near an event keyword. Only dates after the as-of matter; past dates are context."""
    low = text.lower()
    found: list[ScheduledEvent] = []
    seen: set[tuple[str, date | None]] = set()
    for pat in _DATE_PATTERNS:
        for m in pat.finditer(text):
            d = _parse_match(m, asof)
            if d is None or d <= asof or d > asof + timedelta(days=400):
                continue
            ctx = low[max(0, m.start() - window): m.end() + window]
            kind = next((k for k, pats in _EVENT_RES.items() if any(p.search(ctx) for p in pats)), None)
            if kind is None:
                continue
            key = (kind, d)
            if key in seen:
                continue
            seen.add(key)
            snippet = re.sub(r"\s+", " ", text[max(0, m.start() - 60): m.end() + 60]).strip()
            found.append(ScheduledEvent(kind, snippet[:140], source, d, asof < d <= horizon_end))
            if len(found) >= max_events:
                return found
    if not found:
        for kind in BINARY_KINDS + ("policy_meeting",):
            for pat in _EVENT_RES[kind]:
                m = pat.search(low)
                if m and any(t in low[max(0, m.start() - window): m.end() + window]
                             for t in ("upcoming", "next", "scheduled", "ahead", "forthcoming", "later this", "has been called", "will be held")):
                    snippet = re.sub(r"\s+", " ", text[max(0, m.start() - 60): m.end() + 80]).strip()
                    found.append(ScheduledEvent(kind, snippet[:140], source, None, None))
                    break
            if found:
                break
    return found


def _bank(doc: CorpusDoc) -> str | None:
    hay = f"{doc.doc_id} {doc.source}".lower()
    for needle, bank in _BANKS:
        if needle in hay:
            return bank
    return None


def _count_cues(text: str, words: tuple[str, ...]) -> int:
    """Number of DISTINCT cue words present (occurrence counts inflate on repetitive decision texts)."""
    low = text.lower()
    return sum(1 for w in words if w in low)


def run_prepass(summary: NumericSummary, docs: list[CorpusDoc], relevance: dict | None = None) -> Prepass:
    asof = summary.asof
    horizon_end, days = horizon_window(summary)
    pre = Prepass(asof=asof, horizon_end=horizon_end, horizon_days=days, n_docs=len(docs))
    card_text = f"{summary.card_text_notes}\n{summary.card_description}"
    pre.scheduled_events.extend(find_events(card_text, "card", asof, horizon_end))
    ages: list[int] = []
    decision_text = ""
    for d in docs:
        try:
            ts = date.fromisoformat(d.timestamp[:10]) if d.timestamp else None
        except ValueError:
            ts = None
        age = (asof - ts).days if ts else None
        if age is not None:
            ages.append(age)
        if d.doc_type in ("central_bank_decision", "fomc_statement"):
            bank = _bank(d) or d.doc_type
            cur = pre.latest_decisions.get(bank)
            if cur is None or (age is not None and age < cur["days_before_asof"]):
                pre.latest_decisions[bank] = {"doc_id": d.doc_id, "timestamp": d.timestamp, "days_before_asof": age if age is not None else 9999}
        if len(pre.scheduled_events) < 24:
            pre.scheduled_events.extend(find_events(d.text, d.doc_id, asof, horizon_end, max_events=4))
    for bank, info in pre.latest_decisions.items():
        doc = next((d for d in docs if d.doc_id == info["doc_id"]), None)
        if doc is not None:
            decision_text += "\n" + doc.text[:4000]
    if ages:
        pre.newest_doc_days = min(ages)
        pre.docs_within_30d = sum(1 for a in ages if a <= 30)
    cue_text = card_text + decision_text
    pre.cues = {
        "hawkish": _count_cues(cue_text, HAWKISH), "dovish": _count_cues(cue_text, DOVISH),
        "crisis": _count_cues(cue_text, CRISIS), "binary": _count_cues(card_text, BINARY),
        "regime": _count_cues(card_text, REGIME_WORDS),
    }
    low = card_text.lower()
    pre.card_binary_kind = any(p.search(low) for k in BINARY_KINDS for p in _EVENT_RES[k]) or "binary" in low
    pre.card_event_flag = pre.card_binary_kind or "scheduled" in low or "risk event" in low
    pre.scheduled_events.sort(key=lambda e: (not bool(e.inside_horizon), e.event_date or date.max))
    pre.scheduled_events = pre.scheduled_events[:24]
    if relevance:  # list only documents that the ranking actually penalises (speeches, beige books, landmarks)
        low_priority = {d.doc_id for d in docs
                        if C.DOC_TYPE_PRIORITY.get(d.doc_type, C.DEFAULT_DOC_TYPE_PRIORITY) >= C.OFF_TOPIC_MIN_PRIORITY}
        pre.off_topic_docs = [d for d, r in relevance.items() if r.off_topic and d in low_priority]
    return pre


def labels_from_prepass(pre: Prepass, summary: NumericSummary) -> dict:
    """Notes-only labels (B4 v2): conservative, deterministic, no direction calls.

    * elevated when the card prose / latest decisions carry crisis vocabulary AND the panel is not already
      volatile (numeric_v1 already widens on a high recent/long-run vol ratio; widening twice hurt);
    * never ``crisis`` from a lexicon alone (the v1 tier measured worse on the practice proxies);
    * scheduled_binary when a two-outcome event sits inside the horizon (dated in a document or named
      by the card prose); branches carry no signs, so the table adds width and tail, not drift.
    """
    crisis = pre.cues.get("crisis", 0)
    max_vol_ratio = max((summary.vol_ratio.get(a, 1.0) for a in summary.assets), default=1.0)
    already_wide = max_vol_ratio >= C.PREPASS_VOL_RATIO_ALREADY_WIDE
    regime = "elevated" if (crisis >= C.PREPASS_CRISIS_CUES_FOR_ELEVATED and not already_wide) else "calm"
    event = "scheduled_binary" if pre.binary_event_inside else "none"
    branches = []
    if event == "scheduled_binary":
        branches = [{"label": "event outcome A", "prob": 0.5, "signs": {a: 0 for a in summary.assets}},
                    {"label": "event outcome B", "prob": 0.5, "signs": {a: 0 for a in summary.assets}}]
    return {
        "schema": C.LABELS_SCHEMA_VERSION, "mode": C.MODE_NOTES_ONLY,
        "regime": regime, "event_in_horizon": event, "disagreement": False,
        "assets": {a: {"direction": "none", "direction_established": False} for a in summary.assets},
        "branches": branches, "summary": "Deterministic pre-pass labels from card prose, event regex and lexicon cues; no direction call.",
        "runs": 0, "agreement": {}, "prepass": pre.to_dict(),
        "notes_only_inputs": {"crisis_cues": crisis, "max_vol_ratio": round(max_vol_ratio, 3), "already_wide": already_wide,
                              "binary_event_inside": pre.binary_event_inside},
    }
