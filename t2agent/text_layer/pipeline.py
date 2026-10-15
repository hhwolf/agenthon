"""``read_text`` — the text layer entry point (docs/TEXT_LAYER.md §5, §6).

Pipeline: load + prioritise corpus -> pack into <= MAX_EXTRACTION_CALLS chunks -> extraction calls
(thinking off, parallel) -> one synthesis call (thinking on) -> clamp -> TextSignal with rationale.
Every failure path returns ``TextSignal.neutral(assets, reason=...)``; nothing raises.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping

from ..contracts import CallBudget, NumericSummary, TextSignal
from . import constants as C
from .client import (BudgetExhausted, ContextOverflow, Deadline, HouseClient, OfflineError,
                     TextLayerError, cache_from_env)
from .corpus import Chunk, CorpusDoc, card_keywords, load_corpus, plan_chunks, prioritise
from .parse import ParseError, RawEvidence, RawSignal, extract_json, parse_extraction, parse_synthesis
from .prompts import extraction_messages, repair_messages, synthesis_messages
from .signal import Ledger, compose_signal, rank_evidence, rationale

__all__ = ["read_text"]


def _neutral(summary: NumericSummary, reason: str, calls_used: int, ledger: Ledger | None = None) -> TextSignal:
    signal = TextSignal.neutral(summary.assets, reason=reason)
    md = signal.rationale_md + f" Reason: {reason}."
    if ledger is not None:
        try:
            md = rationale(summary, list(signal.scenarios), signal.tail_mult, [], None, ledger, neutral_reason=reason)
        except Exception:  # noqa: BLE001 - the rationale must never break the fallback
            pass
    return replace(signal, calls_used=calls_used, rationale_md=md)


def _run_parallel(fns: list[Callable[[], Any]], max_workers: int) -> list[Any]:
    """Run callables on daemon threads, fail fast on the first exception, keep input order."""
    if len(fns) <= 1 or max_workers <= 1:
        return [fn() for fn in fns]
    results: list[Any] = [None] * len(fns)
    errors: list[BaseException | None] = [None] * len(fns)
    done: "queue.Queue[int]" = queue.Queue()
    gate = threading.Semaphore(max_workers)

    def worker(i: int, fn: Callable[[], Any]) -> None:
        with gate:
            try:
                results[i] = fn()
            except BaseException as exc:  # noqa: BLE001
                errors[i] = exc
            finally:
                done.put(i)

    for i, fn in enumerate(fns):
        threading.Thread(target=worker, args=(i, fn), name=f"text-layer-extract-{i}", daemon=True).start()
    for _ in fns:
        i = done.get()
        if errors[i] is not None:
            raise errors[i]  # type: ignore[misc]
    return results


class _Pipeline:
    def __init__(self, unit_dir: Path, summary: NumericSummary, budget: CallBudget, house: HouseClient,
                 ledger: Ledger):
        self.unit_dir = unit_dir
        self.summary = summary
        self.budget = budget
        self.house = house
        self.ledger = ledger
        self.docs: list[CorpusDoc] = []
        self.docs_by_id: dict[str, CorpusDoc] = {}
        self.norm_cache: dict[str, str] = {}
        self._lock = threading.Lock()

    # -- extraction ----------------------------------------------------------------
    def _extract_chunk(self, chunk: Chunk, part: int, total: int, depth: int = 0):
        messages = extraction_messages(self.summary, chunk, part, total)
        try:
            result = self.house.chat(messages, max_tokens=C.EXTRACTION_MAX_OUTPUT_TOKENS, thinking=False,
                                     purpose=f"extract_{part}")
        except ContextOverflow:
            if depth >= 1 or len(chunk.segments) < 2:
                raise
            with self._lock:
                self.ledger.notes.append(f"extraction part {part}: context overflow; split in two")
            half = len(chunk.segments) // 2
            left = Chunk(chunk.index, chunk.segments[:half])
            right = Chunk(chunk.index, chunk.segments[half:])
            a = self._extract_chunk(left, part, total, depth + 1)
            b = self._extract_chunk(right, part, total, depth + 1)
            return a[0] + b[0], a[1] + b[1], a[2] + b[2]
        try:
            return self._parse_extraction(result.text)
        except ParseError as exc:
            with self._lock:
                self.ledger.notes.append(f"extraction part {part}: invalid JSON ({str(exc)[:80]}); one repair requested")
            repaired = self.house.chat(repair_messages(messages, result.text, str(exc)),
                                       max_tokens=C.EXTRACTION_MAX_OUTPUT_TOKENS, thinking=False,
                                       purpose=f"extract_{part}_repair")
            return self._parse_extraction(repaired.text)

    def _parse_extraction(self, text: str):
        obj = extract_json(text, prefer_keys=("evidence",))
        with self._lock:
            evidence, events, disagreements, notes = parse_extraction(
                obj, self.docs_by_id, self.summary.assets, norm_cache=self.norm_cache)
            self.ledger.notes.extend(notes[:20])
        return evidence, events, disagreements

    # -- synthesis -----------------------------------------------------------------
    def _synthesize(self, evidence: list[RawEvidence], events: list[str], disagreements: list[str]) -> RawSignal:
        messages = synthesis_messages(self.summary, evidence, events, disagreements)
        result = self.house.chat(messages, max_tokens=C.MAX_OUTPUT_TOKENS, thinking=True, purpose="synthesize",
                                 timeout=C.SYNTHESIS_TIMEOUT_S)
        try:
            return parse_synthesis(extract_json(result.text, prefer_keys=("scenarios",)), self.summary.assets, len(evidence))
        except ParseError as exc:
            self.ledger.notes.append(f"synthesis: invalid JSON ({str(exc)[:80]}); one repair requested (thinking off)")
            repaired = self.house.chat(repair_messages(messages, result.text, str(exc)), max_tokens=C.MAX_OUTPUT_TOKENS,
                                       thinking=False, purpose="synthesize_repair", timeout=C.SYNTHESIS_TIMEOUT_S)
            return parse_synthesis(extract_json(repaired.text, prefer_keys=("scenarios",)), self.summary.assets, len(evidence))

    # -- orchestration -------------------------------------------------------------
    def run(self) -> TextSignal:
        s = self.summary
        docs = load_corpus(self.unit_dir, s.asof, self.ledger.notes)
        if not docs:
            raise TextLayerError("no readable documents in the unit's text directory")
        keywords = card_keywords(s.card_description, s.card_text_notes, assets=s.assets)
        self.docs = prioritise(docs, s.asof, keywords)
        self.docs_by_id = {d.doc_id: d for d in self.docs}
        remaining = self.budget.limit - self.budget.used
        max_chunks = min(C.MAX_EXTRACTION_CALLS, remaining - C.SYNTHESIS_RESERVE)
        if max_chunks < 1:
            raise BudgetExhausted(f"only {remaining} request(s) left; extraction + synthesis need at least "
                                  f"{1 + C.SYNTHESIS_RESERVE}")
        chunks, dropped = plan_chunks(self.docs, max_chunks=max_chunks)
        if not chunks:
            raise TextLayerError("corpus could not be packed into any request")
        sent = {d for ch in chunks for d in ch.doc_ids}
        self.ledger.docs_read = [f"{d.doc_id} ({d.doc_type}, {d.timestamp})" for d in self.docs if d.doc_id in sent]
        self.ledger.docs_dropped = sorted({f"{sg.label}" for sg in dropped})
        self.ledger.notes.append(
            f"{len(self.docs)} documents, {sum(d.tokens for d in self.docs):,} est. tokens -> "
            f"{len(chunks)} extraction request(s) of <= {C.MAX_INPUT_TOKENS_PER_CALL:,} tokens"
            + (f"; {len(dropped)} segment(s) not sent" if dropped else ""))
        total = len(chunks)
        results = _run_parallel([(lambda ch=ch, i=i: self._extract_chunk(ch, i + 1, total)) for i, ch in enumerate(chunks)],
                                C.MAX_PARALLEL_EXTRACTION)
        evidence: list[RawEvidence] = []
        events: list[str] = []
        disagreements: list[str] = []
        for ev, evs, dis in results:
            evidence.extend(ev)
            events.extend(evs)
            disagreements.extend(dis)
        doc_order = {d.doc_id: i for i, d in enumerate(self.docs)}
        evidence = rank_evidence(evidence, doc_order)
        raw = self._synthesize(evidence, events[:12], disagreements[:8])
        self._finish_ledger()
        return compose_signal(raw, evidence, s, self.ledger)

    def _finish_ledger(self) -> None:
        self.ledger.calls = list(self.house.calls)
        self.ledger.cache_hits = sum(1 for c in self.house.calls if c.get("cached"))


def read_text(unit_dir: Path | str, summary: NumericSummary, budget: CallBudget, *,
              env: Mapping[str, str] | None = None, client: Any = None,
              time_budget_s: float | None = None) -> TextSignal:
    """Read a unit's text corpus with the House model and return a clamped TextSignal.

    Never raises. Offline mode (``QFBENCH_NETWORK=none`` or no ``MODEL_ENDPOINT``) makes zero
    network attempts. ``env`` and ``client`` exist for tests; production uses ``os.environ``
    and the real OpenAI client.
    """
    import os

    environment = os.environ if env is None else env
    started = budget.used
    ledger = Ledger()
    budget_seconds = time_budget_s
    if budget_seconds is None:
        try:
            budget_seconds = float(environment.get(C.ENV_TIME_BUDGET, C.TIME_BUDGET_S))
        except (TypeError, ValueError):
            budget_seconds = C.TIME_BUDGET_S
    deadline = Deadline(budget_seconds)
    house: HouseClient | None = None
    try:
        house = HouseClient(budget, deadline, env=environment, cache=cache_from_env(environment), client=client,
                            unit_id=summary.unit_id)
        if house.offline:
            raise OfflineError(house.offline)
        pipeline = _Pipeline(Path(unit_dir), summary, budget, house, ledger)
        signal = pipeline.run()
        ledger.requests = budget.used - started
        return replace(signal, calls_used=budget.used - started,
                       rationale_md=signal.rationale_md.replace("House requests used: 0", f"House requests used: {budget.used - started}", 1))
    except OfflineError as exc:
        return _neutral(summary, f"offline ({exc}): zero network attempts", 0)
    except Exception as exc:  # noqa: BLE001 - contract: never raise
        used = budget.used - started
        ledger.requests = used
        if house is not None:
            ledger.calls = list(house.calls)
            ledger.cache_hits = sum(1 for c in house.calls if c.get("cached"))
        reason = f"{type(exc).__name__}: {str(exc)[:300]}"
        if isinstance(exc, TextLayerError) and not isinstance(exc, (BudgetExhausted,)):
            reason = f"{type(exc).__name__}: {str(exc)[:300]}"
        return _neutral(summary, reason, used, ledger)
    finally:
        _ = time.monotonic()  # keep the import honest for readers of the elapsed figures in ledger.calls
