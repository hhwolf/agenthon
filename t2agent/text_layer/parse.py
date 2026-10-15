"""Strict JSON extraction and validation of model outputs."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from . import constants as C
from .corpus import CorpusDoc


class ParseError(ValueError):
    """The model output is not a usable JSON object of the required shape."""


@dataclass(frozen=True)
class RawEvidence:
    doc_id: str
    timestamp: str
    claim: str
    quote: str
    assets: tuple[str, ...]
    direction: int
    established: bool
    kind: str


@dataclass(frozen=True)
class RawScenario:
    label: str
    weight: float
    drift_sd: dict[str, float]
    vol_mult: float
    evidence: tuple[int, ...]


@dataclass(frozen=True)
class RawSignal:
    scenarios: tuple[RawScenario, ...]
    tail_mult: float
    narrowing_support: tuple[int, ...]
    summary: str


# --------------------------------------------------------------------------- #
# JSON extraction
# --------------------------------------------------------------------------- #

_THINK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)
_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*|```", re.S)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _lenient_loads(s: str):
    try:
        return json.loads(s)
    except ValueError:
        return json.loads(_TRAILING_COMMA_RE.sub(r"\1", s))


def _balanced_end(s: str, start: int) -> int:
    depth = 0
    in_str = esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return i + 1
    return -1


def _close_truncated(s: str) -> list[str]:
    out = []
    for cut in (len(s), s.rfind(","), max(s.rfind("}"), s.rfind("]")) + 1):
        if cut <= 0:
            continue
        frag = s[:cut]
        stack: list[str] = []
        in_str = esc = False
        for ch in frag:
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch in "{[":
                stack.append("}" if ch == "{" else "]")
            elif ch in "}]" and stack:
                stack.pop()
        out.append(frag + ('"' if in_str else "") + "".join(reversed(stack)))
    return out


def extract_json(text: str, prefer_keys: tuple[str, ...] = ("evidence", "scenarios")) -> dict:
    """Return the answer object from model output, tolerating fences, <think> blocks, prose and truncation."""
    if not text or not text.strip():
        raise ParseError("empty model output")
    s = _THINK_RE.sub("", text)
    low = s.lower()
    if "</think>" in low and "<think>" not in low:
        s = s[low.rfind("</think>") + len("</think>"):]
    s = _FENCE_RE.sub("", s).strip()
    candidates: list[dict] = []
    try:
        obj = _lenient_loads(s)
        if isinstance(obj, dict):
            candidates.append(obj)
    except ValueError:
        pass
    if not candidates:
        repairs = 5
        for start in [m.start() for m in re.finditer(r"\{", s)][:200]:
            end = _balanced_end(s, start)
            if end >= 0:
                try:
                    obj = _lenient_loads(s[start:end])
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    candidates.append(obj)
                continue
            if repairs <= 0:
                continue
            repairs -= 1
            for cand in _close_truncated(s[start:]):
                try:
                    obj = _lenient_loads(cand)
                except ValueError:
                    continue
                if isinstance(obj, dict) and obj:
                    candidates.append(obj)
                    break
    if not candidates:
        raise ParseError("no JSON object found in model output")
    for obj in candidates:
        if any(k in obj for k in prefer_keys):
            return obj
    return candidates[0]


# --------------------------------------------------------------------------- #
# Coercion helpers
# --------------------------------------------------------------------------- #

def _num(x) -> float | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x) if math.isfinite(float(x)) else None
    if isinstance(x, str):
        try:
            v = float(x.strip().rstrip("%"))
        except ValueError:
            return None
        return v if math.isfinite(v) else None
    return None


def _bool(x) -> bool:
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return bool(x)
    return str(x).strip().lower() in {"true", "yes", "1", "established", "y"}


def _direction(x) -> int:
    v = _num(x)
    if v is None:
        s = str(x).strip().lower()
        return 1 if s in {"up", "+", "positive", "higher"} else -1 if s in {"down", "-", "negative", "lower"} else 0
    return 1 if v > 0 else -1 if v < 0 else 0


_QUOTE_TRANSLATE = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "−": "-", "…": "...", " ": " ",
})


def _norm(s: str) -> str:
    s = s.translate(_QUOTE_TRANSLATE)
    s = re.sub(r"\s+", " ", s).strip().casefold()
    return s.strip(" \"'`.,;:-")


def quote_found(quote: str, text: str, norm_text: str | None = None) -> bool:
    if not isinstance(quote, str):
        return False
    q = _norm(quote)
    if len(q) < C.MIN_QUOTE_CHARS or len(q) > C.MAX_QUOTE_CHARS * 2:
        return False
    return q in (norm_text if norm_text is not None else _norm(text))


def resolve_doc_id(doc_id: str, docs_by_id: dict[str, CorpusDoc]) -> str | None:
    if doc_id in docs_by_id:
        return doc_id
    cand = doc_id.strip().strip("[]'\"")
    if cand in docs_by_id:
        return cand
    lower = {k.lower(): k for k in docs_by_id}
    if cand.lower() in lower:
        return lower[cand.lower()]
    stem = Path(cand).stem.lower()
    hits = [k for k, d in docs_by_id.items() if Path(d.file).stem.lower() == stem or k.lower() == stem]
    return hits[0] if len(hits) == 1 else None


def _match_assets(values, assets: tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(values, str):
        values = [v.strip() for v in re.split(r"[,/;]", values)]
    if not isinstance(values, (list, tuple)):
        return ()
    lower = {a.lower(): a for a in assets}
    out: list[str] = []
    for v in values:
        key = str(v).strip().lower()
        if key in lower and lower[key] not in out:
            out.append(lower[key])
    return tuple(out)


# --------------------------------------------------------------------------- #
# Extraction output
# --------------------------------------------------------------------------- #

def parse_extraction(obj: dict, docs_by_id: dict[str, CorpusDoc], assets: tuple[str, ...],
                     *, norm_cache: dict[str, str] | None = None,
                     max_items: int = C.MAX_EVIDENCE_PER_CHUNK) -> tuple[list[RawEvidence], list[str], list[str], list[str]]:
    """Validate one extraction reply.

    Returns (evidence, scheduled_events, disagreements, notes). Uncited claims (no resolvable
    doc_id) are dropped; ``established`` survives only with a verbatim quote found in the document.
    """
    if not isinstance(obj, dict) or not isinstance(obj.get("evidence"), list):
        raise ParseError("extraction reply lacks an 'evidence' list")
    norm_cache = norm_cache if norm_cache is not None else {}
    notes: list[str] = []
    out: list[RawEvidence] = []
    seen: set[tuple[str, str]] = set()
    for item in obj["evidence"][: max_items * 3]:
        if not isinstance(item, dict):
            continue
        claim = re.sub(r"\s+", " ", str(item.get("claim") or "")).strip()
        if not claim:
            continue
        doc_id = resolve_doc_id(str(item.get("doc_id") or ""), docs_by_id)
        if doc_id is None:
            notes.append(f"uncited claim dropped (doc_id {str(item.get('doc_id'))[:60]!r}): {claim[:80]}")
            continue
        doc = docs_by_id[doc_id]
        quote = str(item.get("quote") or "").strip()
        established = _bool(item.get("established"))
        if established:
            if doc_id not in norm_cache:
                norm_cache[doc_id] = _norm(doc.text)
            if not quote_found(quote, doc.text, norm_cache[doc_id]):
                notes.append(f"{doc_id}: quote not found verbatim; demoted to inferred: {claim[:80]}")
                established = False
        key = (doc_id, claim.casefold())
        if key in seen:
            continue
        seen.add(key)
        out.append(RawEvidence(
            doc_id=doc_id, timestamp=str(item.get("timestamp") or doc.timestamp), claim=claim[:C.MAX_CLAIM_CHARS],
            quote=quote[:C.MAX_QUOTE_CHARS], assets=_match_assets(item.get("assets"), assets),
            direction=_direction(item.get("direction")), established=established,
            kind=str(item.get("kind") or "other").strip().lower()[:16] or "other"))
        if len(out) >= max_items:
            break
    events: list[str] = []
    for ev in obj.get("scheduled_events") or []:
        if isinstance(ev, dict) and ev.get("event"):
            doc_id = resolve_doc_id(str(ev.get("doc_id") or ""), docs_by_id)
            if doc_id is None:
                continue
            events.append(f"{ev.get('date') or 'date not stated'}: {str(ev['event'])[:160]} [{doc_id}]")
        elif isinstance(ev, str) and ev.strip():
            events.append(ev.strip()[:200])
    disagreements = [str(d).strip()[:240] for d in (obj.get("disagreements") or []) if str(d).strip()]
    return out, events[:12], disagreements[:8], notes


# --------------------------------------------------------------------------- #
# Synthesis output
# --------------------------------------------------------------------------- #

def parse_synthesis(obj: dict, assets: tuple[str, ...], n_evidence: int) -> RawSignal:
    """Validate the synthesis reply into a RawSignal. Clamping happens later in signal.py."""
    if not isinstance(obj, dict):
        raise ParseError("synthesis reply is not an object")
    scenarios_in = obj.get("scenarios")
    if not isinstance(scenarios_in, list) or not scenarios_in:
        raise ParseError("synthesis reply lacks a non-empty 'scenarios' list")
    lower = {a.lower(): a for a in assets}
    scenarios: list[RawScenario] = []
    for i, sc in enumerate(scenarios_in[: C.MAX_SCENARIOS * 3]):
        if not isinstance(sc, dict):
            continue
        w = _num(sc.get("weight", sc.get("probability", sc.get("prob"))))
        if w is None:
            raise ParseError(f"scenario {i + 1} has a non-numeric weight")
        drift_in = sc.get("drift_sd", sc.get("drift", {}))
        drift: dict[str, float] = {}
        if isinstance(drift_in, dict):
            for k, v in drift_in.items():
                key = lower.get(str(k).strip().lower())
                val = _num(v)
                if key is not None and val is not None:
                    drift[key] = val
        else:
            val = _num(drift_in)
            if val is not None and len(assets) == 1:
                drift[assets[0]] = val
        vol = _num(sc.get("vol_mult", sc.get("vol_multiplier", 1.0)))
        if vol is None:
            raise ParseError(f"scenario {i + 1} has a non-numeric vol_mult")
        ev = tuple(int(e) for e in (sc.get("evidence") or []) if _num(e) is not None and 1 <= int(_num(e)) <= n_evidence)
        label = re.sub(r"\s+", " ", str(sc.get("label") or sc.get("name") or f"scenario_{i + 1}")).strip()[:48]
        scenarios.append(RawScenario(label=label or f"scenario_{i + 1}", weight=w, drift_sd=drift,
                                     vol_mult=vol, evidence=ev))
    if not scenarios:
        raise ParseError("no usable scenario objects")
    tail = _num(obj.get("tail_mult", 1.0))
    if tail is None:
        raise ParseError("tail_mult is not numeric")
    support = tuple(int(e) for e in (obj.get("narrowing_support") or [])
                    if _num(e) is not None and 1 <= int(_num(e)) <= n_evidence)
    summary = re.sub(r"\s+", " ", str(obj.get("summary") or "")).strip()[:600]
    return RawSignal(tuple(scenarios), tail, support, summary)
