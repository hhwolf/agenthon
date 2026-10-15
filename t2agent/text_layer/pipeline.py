"""``read_text`` — the text layer entry point (docs/TEXT_LAYER.md §5, §6; Phase 3 design).

Pipeline: deterministic pre-pass -> relevance-ranked corpus packed into <= MAX_EXTRACTION_CALLS chunks ->
extraction calls (thinking off, parallel) -> SYNTHESIS_RUNS label calls (thinking on, parallel, pinned seeds
SEED+k, evidence order permuted) -> majority vote -> TextSignal whose numeric part is neutral and whose
``labels`` carry the classification. Modes: ``labels`` (default) and ``notes_only`` (no LLM, zero requests).
Every failure path returns a neutral signal with ``fallback_reason``; nothing raises.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping

from ..contracts import CallBudget, NumericSummary, TextSignal
from . import constants as C
from .client import (BudgetExhausted, ContextOverflow, Deadline, HouseClient, OfflineError, TextLayerError,
                     TimeExhausted, cache_from_env, replay_only_from_env)
from .corpus import Chunk, CorpusDoc, card_keywords, load_corpus, plan_chunks, prioritise
from .labels import Labels, labels_to_dict, neutral_labels, parse_labels, vote
from .parse import ParseError, RawEvidence, extract_json, parse_extraction
from .prepass import Prepass, labels_from_prepass, run_prepass
from .prompts import extraction_messages, labels_messages, repair_messages
from .relevance import score_documents
from .signal import Ledger, rank_evidence, rationale_labels, to_contract_evidence

__all__ = ["read_text"]

_FAIL_FAST = (BudgetExhausted, TimeExhausted, OfflineError)


def _run_parallel(fns: list[Callable[[], Any]], max_workers: int, *, fail_fast: tuple = _FAIL_FAST,
                  collect_errors: bool = False) -> list[Any]:
    """Run callables on daemon threads in input order.

    ``fail_fast`` exceptions propagate; other exceptions propagate too unless ``collect_errors`` is set,
    in which case that slot becomes ``None``. On a propagating error the queued callables are cancelled
    and the in-flight ones are awaited (each is bounded by its own request timeout) before the error is
    raised, so no request is sent after the caller has returned and the budget count is final.
    """
    if len(fns) <= 1 or max_workers <= 1:
        out = []
        for fn in fns:
            try:
                out.append(fn())
            except fail_fast:
                raise
            except Exception:
                if not collect_errors:
                    raise
                out.append(None)
        return out
    results: list[Any] = [None] * len(fns)
    errors: list[BaseException | None] = [None] * len(fns)
    done: "queue.Queue[int]" = queue.Queue()
    gate = threading.Semaphore(max_workers)
    cancel = threading.Event()

    def worker(i: int, fn: Callable[[], Any]) -> None:
        with gate:
            try:
                if not cancel.is_set():
                    results[i] = fn()
            except BaseException as exc:  # noqa: BLE001
                errors[i] = exc
            finally:
                done.put(i)

    for i, fn in enumerate(fns):
        threading.Thread(target=worker, args=(i, fn), name=f"text-layer-{i}", daemon=True).start()
    first_error: BaseException | None = None
    for _ in fns:
        i = done.get()
        err = errors[i]
        if err is not None and first_error is None and (isinstance(err, fail_fast) or not collect_errors):
            first_error = err
            cancel.set()          # queued workers return without sending; in-flight ones finish and report
    if first_error is not None:
        raise first_error
    return results


def _permutation(k: int, evidence: list[RawEvidence]) -> list[int]:
    n = len(evidence)
    if k % 3 == 1:
        return list(range(n - 1, -1, -1))
    if k % 3 == 2:
        return sorted(range(n), key=lambda i: (not evidence[i].established, evidence[i].timestamp), reverse=False)
    return list(range(n))


class _Pipeline:
    def __init__(self, unit_dir: Path, summary: NumericSummary, budget: CallBudget, house: HouseClient | None,
                 ledger: Ledger, deadline: Deadline, n_runs: int):
        self.unit_dir = unit_dir
        self.summary = summary
        self.budget = budget
        self.house = house
        self.ledger = ledger
        self.deadline = deadline
        self.n_runs = n_runs
        self.docs: list[CorpusDoc] = []
        self.docs_by_id: dict[str, CorpusDoc] = {}
        self.norm_cache: dict[str, str] = {}
        self.prepass: Prepass | None = None
        self._lock = threading.Lock()

    # -- corpus + pre-pass -----------------------------------------------------------------------
    def prepare(self) -> None:
        s = self.summary
        docs = load_corpus(self.unit_dir, s.asof, self.ledger.notes)
        keywords = card_keywords(s.card_description, s.card_text_notes, assets=s.assets)
        relevance = score_documents({d.doc_id: d.text for d in docs}, s.assets, keywords) if docs else {}
        self.prepass = run_prepass(s, docs, relevance)
        self.ledger.prepass_lines = self.prepass.summary_lines()
        self.docs = prioritise(docs, s.asof, keywords, relevance)
        self.docs_by_id = {d.doc_id: d for d in self.docs}

    # -- extraction -----------------------------------------------------------------------------
    def _extract_chunk(self, chunk: Chunk, part: int, total: int, depth: int = 0):
        assert self.house is not None
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
            a = self._extract_chunk(Chunk(chunk.index, chunk.segments[:half]), part, total, depth + 1)
            b = self._extract_chunk(Chunk(chunk.index, chunk.segments[half:]), part, total, depth + 1)
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
            try:
                evidence, events, disagreements, notes = parse_extraction(
                    obj, self.docs_by_id, self.summary.assets, norm_cache=self.norm_cache)
            except ParseError:
                raise
            except Exception as exc:  # malformed but JSON-valid shapes must reach the repair path
                raise ParseError(f"extraction reply has an unusable shape: {type(exc).__name__}: {str(exc)[:80]}") from exc
            self.ledger.notes.extend(notes[:20])
        return evidence, events, disagreements

    def _parse_labels(self, text: str, evidence: list[RawEvidence]) -> Labels:
        try:
            return parse_labels(extract_json(text, prefer_keys=("regime", "assets")), self.summary.assets, evidence)
        except ParseError:
            raise
        except Exception as exc:
            raise ParseError(f"labels reply has an unusable shape: {type(exc).__name__}: {str(exc)[:80]}") from exc

    def extract(self) -> tuple[list[RawEvidence], list[str], list[str]]:
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
        self.ledger.docs_dropped = sorted({sg.label for sg in dropped})
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
        return rank_evidence(evidence, doc_order), events[:12], disagreements[:8]

    # -- synthesis (labels, self-consistency) --------------------------------------------------------
    def _label_run(self, k: int, evidence: list[RawEvidence], events: list[str], disagreements: list[str]) -> Labels:
        assert self.house is not None and self.prepass is not None
        messages = labels_messages(self.summary, evidence, events, disagreements, self.ledger.prepass_lines,
                                   run_index=k, order=_permutation(k, evidence))
        seed = C.SEED + k * C.SYNTHESIS_SEED_STEP
        result = self.house.chat(messages, max_tokens=C.SYNTHESIS_MAX_OUTPUT_TOKENS, thinking=True,
                                 purpose=f"labels_{k + 1}", timeout=C.SYNTHESIS_TIMEOUT_S, seed=seed)
        try:
            return self._parse_labels(result.text, evidence)
        except ParseError as exc:
            with self._lock:
                self.ledger.notes.append(f"labels run {k + 1}: invalid JSON ({str(exc)[:80]}); one repair requested (thinking off)")
            repaired = self.house.chat(repair_messages(messages, result.text, str(exc)), max_tokens=C.SYNTHESIS_MAX_OUTPUT_TOKENS,
                                       thinking=False, purpose=f"labels_{k + 1}_repair", timeout=C.SYNTHESIS_TIMEOUT_S, seed=seed)
            return self._parse_labels(repaired.text, evidence)

    def synthesize(self, evidence: list[RawEvidence], events: list[str], disagreements: list[str]) -> tuple[Labels, dict, dict]:
        remaining = self.budget.limit - self.budget.used
        if remaining < 1:
            raise BudgetExhausted("no request left for synthesis")
        runs = max(1, min(self.n_runs, remaining // 2 if remaining >= 2 else 1))
        if runs < self.n_runs:
            self.ledger.notes.append(f"synthesis runs reduced to {runs} (budget remaining {remaining})")
        results = _run_parallel([(lambda k=k: self._label_run(k, evidence, events, disagreements)) for k in range(runs)],
                                C.MAX_PARALLEL_SYNTHESIS, collect_errors=True)
        good = [r for r in results if r is not None]
        failed = len(results) - len(good)
        if failed:
            self.ledger.notes.append(f"{failed} of {runs} synthesis run(s) failed and were excluded from the vote")
        if not good:
            raise TextLayerError("every synthesis run failed")
        return vote(good, self.summary.assets)


def _signal(summary: NumericSummary, labels: dict, evidence: list[RawEvidence], ledger: Ledger, calls_used: int,
            *, fallback_reason: str | None = None) -> TextSignal:
    base = TextSignal.neutral(summary.assets, reason=fallback_reason)
    md = rationale_labels(summary, labels, evidence, ledger, neutral_reason=fallback_reason)
    return replace(base, evidence=to_contract_evidence(evidence), rationale_md=md, calls_used=calls_used, labels=labels)


def _neutral(summary: NumericSummary, reason: str, calls_used: int, ledger: Ledger, prepass: Prepass | None) -> TextSignal:
    labels = {"schema": C.LABELS_SCHEMA_VERSION, "mode": "neutral", "fallback_reason": reason,
              "prepass": prepass.to_dict() if prepass is not None else {}}
    try:
        return _signal(summary, labels, [], ledger, calls_used, fallback_reason=reason)
    except Exception:  # noqa: BLE001 - the fallback must never fail
        base = TextSignal.neutral(summary.assets, reason=reason)
        return replace(base, calls_used=calls_used, labels=labels, rationale_md=base.rationale_md + f" Reason: {reason}.")


def read_text(unit_dir: Path | str, summary: NumericSummary, budget: CallBudget, *,
              env: Mapping[str, str] | None = None, client: Any = None,
              time_budget_s: float | None = None, mode: str | None = None) -> TextSignal:
    """Read a unit's text corpus and return a TextSignal with categorical labels.

    Never raises. Offline mode (``QFBENCH_NETWORK=none`` or no ``MODEL_ENDPOINT``) makes zero network
    attempts. ``TEXT_LAYER_MODE=notes_only`` (or ``mode=``) skips the model entirely and labels from the
    deterministic pre-pass. ``env`` and ``client`` exist for tests; production uses ``os.environ``.
    """
    environment = os.environ if env is None else env
    started = budget.used
    t0 = time.monotonic()
    ledger = Ledger()
    mode = (mode or str(environment.get(C.ENV_MODE, C.MODE_LABELS))).strip().lower() or C.MODE_LABELS
    ledger.mode = mode
    try:
        seconds = float(time_budget_s if time_budget_s is not None else environment.get(C.ENV_TIME_BUDGET, C.TIME_BUDGET_S))
    except (TypeError, ValueError):
        seconds = C.TIME_BUDGET_S
    try:
        n_runs = int(environment.get(C.ENV_SYNTHESIS_RUNS, C.SYNTHESIS_RUNS))
    except (TypeError, ValueError):
        n_runs = C.SYNTHESIS_RUNS
    deadline = Deadline(seconds)
    house: HouseClient | None = None
    pipeline: _Pipeline | None = None
    try:
        pipeline = _Pipeline(Path(unit_dir), summary, budget, None, ledger, deadline, max(1, n_runs))
        pipeline.prepare()
        assert pipeline.prepass is not None
        if mode == C.MODE_NOTES_ONLY:
            labels = labels_from_prepass(pipeline.prepass, summary)
            ledger.elapsed_s = time.monotonic() - t0
            return _signal(summary, labels, [], ledger, 0)
        house = HouseClient(budget, deadline, env=environment, cache=cache_from_env(environment), client=client,
                            unit_id=summary.unit_id, replay_only=replay_only_from_env(environment))
        pipeline.house = house
        if house.offline:
            raise OfflineError(house.offline)
        if not pipeline.docs:
            raise TextLayerError("no readable documents in the unit's text directory")
        evidence, events, disagreements = pipeline.extract()
        labels_obj, agreement, votes = pipeline.synthesize(evidence, events, disagreements)
        ledger.calls = list(house.calls)
        ledger.cache_hits = sum(1 for c in house.calls if c.get("cached"))
        ledger.requests = budget.used - started
        ledger.elapsed_s = time.monotonic() - t0
        if ledger.elapsed_s > C.SOFT_TARGET_S:
            ledger.notes.append(f"wall time {ledger.elapsed_s:.0f}s exceeded the {C.SOFT_TARGET_S:.0f}s soft target")
        labels = labels_to_dict(labels_obj, mode="llm", agreement=agreement, votes=votes, prepass=pipeline.prepass.to_dict(),
                                extra={"evidence_count": len(evidence), "established_count": sum(e.established for e in evidence),
                                       "events": events, "disagreements": disagreements,
                                       "requests": ledger.requests, "elapsed_s": round(ledger.elapsed_s, 2)})
        return _signal(summary, labels, evidence, ledger, ledger.requests)
    except OfflineError as exc:
        ledger.elapsed_s = time.monotonic() - t0
        return _neutral(summary, f"offline ({exc}): zero network attempts", 0, ledger, pipeline.prepass if pipeline else None)
    except Exception as exc:  # noqa: BLE001 - contract: never raise
        used = budget.used - started
        ledger.requests = used
        ledger.elapsed_s = time.monotonic() - t0
        if house is not None:
            ledger.calls = list(house.calls)
            ledger.cache_hits = sum(1 for c in house.calls if c.get("cached"))
        return _neutral(summary, f"{type(exc).__name__}: {str(exc)[:300]}", used, ledger, pipeline.prepass if pipeline else None)
