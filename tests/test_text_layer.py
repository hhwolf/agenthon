"""Text layer tests: clamping, neutral fallback, budget counting (incl. failures), offline mode, JSON repair."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from mock_house import MockHouse, canned_extraction, delay, error, ok
from t2agent import numeric_v1
from t2agent.contracts import CallBudget, TextSignal
from t2agent.text_layer import constants as C
from t2agent.text_layer import read_text
from t2agent.text_layer.corpus import load_corpus, plan_chunks, prioritise
from t2agent.text_layer.parse import RawScenario, RawSignal, extract_json
from t2agent.text_layer.signal import Ledger, clamp_scenarios

ROOT = Path(__file__).resolve().parents[1]
ASOF = date(2016, 6, 17)
DOCS = {
    "boe_mpc_2016-06-16": ("2016-06-16", "central_bank_decision",
        "Bank of England Monetary Policy Committee decision, 16 June 2016.\n\n"
        "The Committee voted unanimously to maintain Bank Rate at 0.5% and the stock of purchased assets at 375 billion pounds.\n\n"
        "The outcome of the referendum on 23 June is the largest immediate risk facing UK financial markets, and possibly also global financial markets."),
    "fomc_statement_2016-06-15": ("2016-06-15", "fomc_statement",
        "Federal Open Market Committee statement, 15 June 2016.\n\n"
        "Information received since the Committee met in April indicates that the pace of improvement in the labor market has slowed while growth in economic activity appears to have picked up.\n\n"
        "The Committee decided to maintain the target range for the federal funds rate at 1/4 to 1/2 percent."),
    "bis_carney_2016-05-12": ("2016-05-12", "cb_speech",
        "Mark Carney: Opening remarks at the Inflation Report press conference, 12 May 2016.\n\n"
        "A vote to leave the EU could have material economic effects on the exchange rate, on demand and on supply.\n\n"
        "Sterling has depreciated by around nine percent since its November peak, reflecting referendum uncertainty."),
}


def make_unit(tmp_path: Path, docs=DOCS, extra_index: list | None = None) -> Path:
    unit = tmp_path / "unit"
    text = unit / "text"
    text.mkdir(parents=True)
    index = {"card_id": "t2-TEST-brexit-2016", "asof": ASOF.isoformat(), "documents": []}
    for doc_id, (ts, doc_type, body) in docs.items():
        (text / f"{doc_id}.txt").write_text(body, encoding="utf-8")
        index["documents"].append({"doc_id": doc_id, "timestamp": ts, "source": "test", "doc_type": doc_type, "file": f"{doc_id}.txt"})
    index["documents"].extend(extra_index or [])
    (text / "corpus_index.json").write_text(json.dumps(index))
    return unit


def make_summary(assets=("GBP",), family="T2-F2"):
    from t2agent.contracts import NumericSummary
    return NumericSummary(
        unit_id="t2-TEST-brexit-2016", asof=ASOF, family=family, target_type="level", value_unit="usd_per_gbp",
        assets=tuple(assets), horizons=(21,), spot={a: 1.42 for a in assets},
        horizon_sd={(a, 21): 0.035 for a in assets}, vol_ratio={a: 1.3 for a in assets},
        card_description="GBP/USD into the EU referendum (21 BD).",
        card_text_notes="A scheduled binary risk event falls shortly after the as-of date.")


@pytest.fixture
def server():
    s = MockHouse().start()
    yield s
    s.stop()


@pytest.fixture
def unit(tmp_path):
    return make_unit(tmp_path)


def run(unit, server, budget=None, env=None, **kw):
    budget = budget if budget is not None else CallBudget()
    sig = read_text(unit, make_summary(), budget, env=env if env is not None else server.env(), **kw)
    return sig, budget


def is_neutral(sig: TextSignal) -> bool:
    n = TextSignal.neutral(("GBP",))
    return sig.scenarios == n.scenarios and sig.tail_mult == 1.0 and sig.evidence == ()


# --------------------------------------------------------------------------- #
# Happy path and request hygiene
# --------------------------------------------------------------------------- #

def test_happy_path_small_corpus(unit, server):
    sig, budget = run(unit, server)
    assert sig.fallback_reason is None
    assert sig.calls_used == budget.used == len(server.requests) == 2  # one extraction + one synthesis
    assert len(sig.scenarios) == 3 and abs(sum(s.weight for s in sig.scenarios) - 1) < 1e-9
    assert all(set(s.drift_sd) == {"GBP"} for s in sig.scenarios)
    assert any(e.established for e in sig.evidence) and all(e.doc_id in DOCS for e in sig.evidence)
    assert sig.tail_mult == 1.2
    assert "### Adjustment ledger" in sig.rationale_md and "mean drift" in sig.rationale_md


def test_requests_are_pinned_tool_free_and_thinking_flagged(unit, server):
    sig, _ = run(unit, server)
    assert sig.fallback_reason is None
    extraction, synthesis = server.requests
    for req in (extraction, synthesis):
        body = req["body"]
        assert req["path"] == "/v1/chat/completions"
        assert req["headers"]["authorization"] == f"Bearer {server.token}"
        assert body["model"] == server.model and body["temperature"] == 0.0 and body["seed"] == C.SEED
        assert body["max_tokens"] <= 4000 and "n" not in body
        for forbidden in ("tools", "functions", "tool_choice", "web_search_options"):
            assert forbidden not in body
        prompt = body["messages"][1]["content"]
        assert f"AS-OF DATE: {ASOF.isoformat()}" in prompt and "Do not use any knowledge" in prompt
    assert extraction["body"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert synthesis["body"]["chat_template_kwargs"] == {"enable_thinking": True}
    assert "doc_id must be copied exactly" in extraction["body"]["messages"][1]["content"]


def test_prompt_is_deterministic(unit, server):
    run(unit, server)
    run(unit, server)
    assert server.bodies()[0] == server.bodies()[2] and server.bodies()[1] == server.bodies()[3]


# --------------------------------------------------------------------------- #
# Offline mode
# --------------------------------------------------------------------------- #

def test_offline_network_none_makes_no_attempt(unit, server):
    sig, budget = run(unit, server, env=server.env(network="none"))
    assert is_neutral(sig) and sig.fallback_reason.startswith("offline")
    assert sig.calls_used == 0 and budget.used == 0 and server.requests == []


def test_offline_without_endpoint(unit, server):
    env = {k: v for k, v in server.env().items() if k != "MODEL_ENDPOINT"}
    sig, budget = run(unit, server, env=env)
    assert is_neutral(sig) and "MODEL_ENDPOINT" in sig.fallback_reason
    assert budget.used == 0 and server.requests == []


def test_neutral_reproduces_numeric_draws(unit, server):
    sig, _ = run(unit, server, env=server.env(network="none"))
    card = {"targets": {"asset_ids": ["GBP"], "horizons": [21]}}
    samples = np.random.default_rng(0).normal(size=(200, 1))
    assert numeric_v1.apply_text_signal(samples, card, sig, seed=1) is samples


def test_real_signal_is_accepted_by_numeric_adapter(unit, server):
    sig, _ = run(unit, server)
    card = {"targets": {"asset_ids": ["GBP"], "horizons": [21]}}
    samples = np.random.default_rng(0).normal(size=(2000, 1))
    adjusted = numeric_v1.apply_text_signal(samples, card, sig, seed=1)
    assert adjusted.shape == samples.shape and np.isfinite(adjusted).all() and not np.allclose(adjusted, samples)


# --------------------------------------------------------------------------- #
# Clamps
# --------------------------------------------------------------------------- #

def test_extreme_values_are_clamped_end_to_end(unit, server):
    server.scenario = "extreme"
    sig, _ = run(unit, server)
    assert sig.fallback_reason is None
    assert all(not e.established for e in sig.evidence) and all(e.doc_id in DOCS for e in sig.evidence)
    assert len(sig.scenarios) == 2  # the two tiny scenarios were dropped
    mean = sum(s.weight * s.drift_sd["GBP"] for s in sig.scenarios)
    assert abs(mean) <= C.DRIFT_MEAN_LIMIT + 1e-9 and all(abs(s.drift_sd["GBP"]) <= C.DRIFT_SCENARIO_LIMIT for s in sig.scenarios)
    assert [s.vol_mult for s in sig.scenarios] == [1.0, 2.0]  # 0.5 -> 0.8 -> floored at 1 (no established); 5 -> 2
    assert sig.tail_mult == C.TAIL_MULT_MAX
    assert "rescaled" in sig.rationale_md and "cannot narrow" in sig.rationale_md


def test_vol_below_one_needs_established_evidence(unit, server):
    quote = "The Committee voted unanimously to maintain Bank Rate at 0.5%"
    established = {"evidence": [{"doc_id": "boe_mpc_2016-06-16", "timestamp": "2016-06-16", "claim": "Bank Rate held at 0.5%.",
                                 "quote": quote, "assets": ["GBP"], "direction": 0, "established": True, "kind": "decision"}],
                   "scheduled_events": [], "disagreements": []}
    narrow = {"scenarios": [{"label": "calm", "weight": 1.0, "drift_sd": {"GBP": 0.0}, "vol_mult": 0.85, "evidence": [1]}],
              "tail_mult": 1.0, "narrowing_support": [1], "summary": "Decision already taken."}
    server.push(ok(json.dumps(established)), ok(json.dumps(narrow)))
    sig, _ = run(unit, server)
    assert sig.fallback_reason is None and sig.scenarios[0].vol_mult == 0.85 and sig.evidence[0].established

    inferred = json.loads(json.dumps(established))
    inferred["evidence"][0].update(established=False, quote="")
    server.push(ok(json.dumps(inferred)), ok(json.dumps(narrow)))
    sig2, _ = run(unit, server)
    assert sig2.fallback_reason is None and sig2.scenarios[0].vol_mult == 1.0
    assert "cannot narrow" in sig2.rationale_md


def test_established_requires_verbatim_quote_and_citations(unit, server):
    reply = {"evidence": [
        {"doc_id": "boe_mpc_2016-06-16", "claim": "Fake quote.", "quote": "rates were cut to zero", "assets": ["GBP"], "direction": -1, "established": True},
        {"doc_id": "ghost_2016-06-01", "claim": "Uncited.", "quote": "", "assets": ["GBP"], "direction": 1, "established": True},
        {"doc_id": "bis_carney_2016-05-12", "claim": "Sterling fell about nine percent.", "quote": "Sterling has depreciated by around nine percent", "assets": ["GBP"], "direction": -1, "established": True},
    ], "scheduled_events": [], "disagreements": []}
    server.push(ok(json.dumps(reply)))
    sig, _ = run(unit, server)
    assert sig.fallback_reason is None
    ids = {e.doc_id for e in sig.evidence}
    assert "ghost_2016-06-01" not in ids
    by_claim = {e.claim: e for e in sig.evidence}
    assert by_claim["Fake quote."].established is False and by_claim["Sterling fell about nine percent."].established is True


def test_clamp_scenarios_unit():
    ledger = Ledger()
    raw = RawSignal((RawScenario("a", 0.7, {"X": 2.0}, 0.5, (1,)), RawScenario("b", 0.3, {"X": -0.2}, 3.0, ()),
                     RawScenario("c", 0.01, {"X": 0.0}, 1.0, ())), 9.0, (), "")
    scenarios, tail = clamp_scenarios(raw, ("X",), has_established=False, ledger=ledger)
    assert [s.label for s in scenarios] == ["a", "b"] and abs(sum(s.weight for s in scenarios) - 1) < 1e-9
    mean = sum(s.weight * s.drift_sd["X"] for s in scenarios)
    assert abs(mean) <= C.DRIFT_MEAN_LIMIT + 1e-9 and scenarios[0].drift_sd["X"] > 0 > scenarios[1].drift_sd["X"]
    assert [s.vol_mult for s in scenarios] == [1.0, 2.0] and tail == 2.0
    scenarios_e, _ = clamp_scenarios(raw, ("X",), has_established=True, ledger=Ledger())
    assert scenarios_e[0].vol_mult == C.VOL_MULT_MIN
    assert any("dropped" in c for c in ledger.clamps) and any("rescaled" in c for c in ledger.clamps)


# --------------------------------------------------------------------------- #
# Budget counting, failures, time
# --------------------------------------------------------------------------- #

def test_failed_calls_count_against_budget(unit, server):
    server.push(error(500), error(502))
    sig, budget = run(unit, server)
    assert is_neutral(sig) and "HTTP 502" in sig.fallback_reason
    assert budget.used == sig.calls_used == len(server.requests) == 1 + C.MAX_RETRIES_PER_CALL


def test_auth_failures_are_not_retried(unit, server):
    for status in (401, 403):
        server.requests.clear()
        server.push(error(status, "nope"))
        sig, budget = run(unit, server)
        assert is_neutral(sig) and str(status) in sig.fallback_reason
        assert budget.used == 1 and len(server.requests) == 1


def test_transient_error_then_success(unit, server):
    server.push(error(503))
    sig, budget = run(unit, server)
    assert sig.fallback_reason is None and budget.used == 3 == len(server.requests)


def test_timeout_is_neutral_and_bounded(unit, server, monkeypatch):
    monkeypatch.setattr(C, "REQUEST_TIMEOUT_S", 0.5)
    monkeypatch.setattr(C, "MIN_REQUEST_TIMEOUT_S", 0.1)
    monkeypatch.setattr(C, "SAFETY_MARGIN_S", 0.0)
    monkeypatch.setattr(C, "MAX_RETRIES_PER_CALL", 0)
    server.push(delay(3.0))
    t0 = time.monotonic()
    sig, budget = run(unit, server, time_budget_s=30)
    assert is_neutral(sig) and time.monotonic() - t0 < 2.5
    assert budget.used == 1 and "Timeout" in sig.fallback_reason or "timeout" in sig.fallback_reason.lower()


def test_time_budget_too_small_sends_nothing(unit, server, monkeypatch):
    monkeypatch.setattr(C, "SAFETY_MARGIN_S", 0.0)
    sig, budget = run(unit, server, time_budget_s=1.0)
    assert is_neutral(sig) and "TimeExhausted" in sig.fallback_reason and budget.used == 0 and server.requests == []


def test_budget_limit_respected(unit, server):
    sig, budget = run(unit, server, budget=CallBudget(limit=2))  # no room for extraction + synthesis reserve
    assert is_neutral(sig) and "BudgetExhausted" in sig.fallback_reason and budget.used == 0 and server.requests == []
    sig3, budget3 = run(unit, server, budget=CallBudget(limit=3))
    assert sig3.fallback_reason is None and budget3.used == 2


def test_exhausted_shared_budget(unit, server):
    budget = CallBudget(limit=5, used=5)
    sig, _ = run(unit, server, budget=budget)
    assert is_neutral(sig) and server.requests == [] and budget.used == 5


def test_hard_cap_holds_for_huge_corpus(tmp_path, server):
    para = ("Paragraph about policy, inflation and the exchange rate with a dated statement from 2016-05-05 "
            "that matters for the horizon and runs long enough to be a real paragraph. ")
    docs = {f"speech_{i:02d}_2016-0{1 + i % 5}-1{i % 9}": (f"2016-0{1 + i % 5}-1{i % 9}", "cb_speech",
                                                           "".join(f"Speech {i} section {k}. " + para * 60 + "\n\n" for k in range(15)))
            for i in range(40)}
    unit = make_unit(tmp_path, docs)
    sig, budget = run(unit, server)
    assert sig.fallback_reason is None
    assert budget.used == C.MAX_EXTRACTION_CALLS + 1 <= C.HARD_REQUEST_CAP
    for body in server.bodies():
        assert sum(len(m["content"]) for m in body["messages"]) // C.CHARS_PER_TOKEN <= 60_000
    assert "Not sent (budget)" in sig.rationale_md


def test_context_overflow_splits_the_chunk(unit, server):
    server.push(error(400, "This model's maximum context length is 8192 tokens; your request used 9000."))
    sig, budget = run(unit, server)
    assert sig.fallback_reason is None
    assert budget.used == 4  # overflow + two halves + synthesis
    assert "split in two" in sig.rationale_md


# --------------------------------------------------------------------------- #
# JSON repair
# --------------------------------------------------------------------------- #

def test_extraction_json_repaired_once(unit, server):
    server.push(ok("Sure! Here is what I found, in prose rather than JSON."))
    sig, budget = run(unit, server)
    assert sig.fallback_reason is None and budget.used == 3
    repair = server.bodies()[1]["messages"]
    assert [m["role"] for m in repair] == ["system", "user", "assistant", "user"] and "not a valid JSON" in repair[-1]["content"]
    assert "one repair requested" in sig.rationale_md


def test_extraction_repair_failure_is_neutral(unit, server):
    server.push(ok("still prose"), ok("and again prose"))
    sig, budget = run(unit, server)
    assert is_neutral(sig) and "ParseError" in sig.fallback_reason and budget.used == 2


def test_synthesis_repair_runs_with_thinking_off(unit, server):
    extraction = canned_extraction(json.dumps({"x": 0}))  # no docs in this fake prompt -> empty evidence is fine
    extraction = {"evidence": [{"doc_id": "boe_mpc_2016-06-16", "timestamp": "2016-06-16", "claim": "Rate held.",
                                "quote": "maintain Bank Rate at 0.5%", "assets": ["GBP"], "direction": 0, "established": True, "kind": "decision"}],
                  "scheduled_events": [], "disagreements": []}
    server.push(ok(json.dumps(extraction)), ok("", finish_reason="length"))
    sig, budget = run(unit, server)
    assert sig.fallback_reason is None and budget.used == 3
    flags = [b["chat_template_kwargs"]["enable_thinking"] for b in server.bodies()]
    assert flags == [False, True, False]


def test_truncated_and_fenced_outputs_are_tolerated(unit, server):
    for scenario in ("truncated", "think"):
        server.scenario = scenario
        server.requests.clear()
        sig, budget = run(unit, server)
        assert sig.fallback_reason is None, scenario
        assert budget.used == 2, scenario


def test_extract_json_cases():
    assert extract_json('```json\n{"scenarios": [1]}\n```')["scenarios"] == [1]
    assert extract_json('<think>{"not": 1}</think>\n{"evidence": []}') == {"evidence": []}
    obj = extract_json('{"evidence": [{"doc_id": "a", "claim": "b", "established": true}, {"doc_id": "c", "cla')
    assert obj["evidence"][0]["doc_id"] == "a"
    with pytest.raises(Exception):
        extract_json("no json here")


# --------------------------------------------------------------------------- #
# Corpus handling, cache, robustness
# --------------------------------------------------------------------------- #

def test_post_asof_and_missing_documents_are_dropped(tmp_path, server):
    extra = [{"doc_id": "future_2016-07-01", "timestamp": "2016-07-01", "source": "x", "doc_type": "cb_speech", "file": "future.txt"},
             {"doc_id": "missing_doc", "timestamp": "2016-06-01", "source": "x", "doc_type": "cb_speech", "file": "nope.txt"}]
    unit = make_unit(tmp_path, extra_index=extra)
    (unit / "text" / "future.txt").write_text("Leave won the referendum and sterling fell sharply.")
    sig, _ = run(unit, server)
    assert sig.fallback_reason is None
    prompt = server.bodies()[0]["messages"][1]["content"]
    assert "future_2016-07-01" not in prompt and "Leave won" not in prompt
    assert "after as-of" in sig.rationale_md and "missing" in sig.rationale_md


def test_prioritisation_and_chunk_plan(unit):
    notes = []
    docs = load_corpus(unit, ASOF, notes)
    ordered = prioritise(docs, ASOF, {"referendum", "sterling"})
    assert ordered[0].doc_type == "central_bank_decision" and ordered[-1].doc_type == "cb_speech"
    chunks, dropped = plan_chunks(ordered, max_chunks=6)
    assert len(chunks) == 1 and not dropped and chunks[0].doc_ids == [d.doc_id for d in ordered]


def test_cache_serves_second_run_without_requests(unit, server, tmp_path):
    env = dict(server.env(), TEXT_LAYER_CACHE_DIR=str(tmp_path / "cache"))
    sig1, b1 = run(unit, server, env=env)
    n = len(server.requests)
    sig2, b2 = run(unit, server, env=env)
    assert sig1.fallback_reason is None and n == b1.used == 2
    assert len(server.requests) == n and b2.used == 0 and sig2.calls_used == 0
    assert sig1.scenarios == sig2.scenarios and "served from the dev cache" in sig2.rationale_md
    assert any(p.suffix == ".json" for p in (tmp_path / "cache").rglob("*"))


def test_missing_unit_dir_and_empty_corpus_are_neutral(tmp_path, server):
    sig, budget = run(tmp_path / "nope", server)
    assert is_neutral(sig) and budget.used == 0 and server.requests == []
    empty = tmp_path / "empty"
    (empty / "text").mkdir(parents=True)
    sig2, budget2 = run(empty, server)
    assert is_neutral(sig2) and budget2.used == 0 and "no readable documents" in sig2.fallback_reason


def test_joint_card_gets_every_asset_in_every_scenario(unit, server):
    sig = read_text(unit, make_summary(assets=("GBP", "EUR"), family="T2-F3"), CallBudget(), env=server.env())
    assert sig.fallback_reason is None
    assert all(set(s.drift_sd) == {"GBP", "EUR"} for s in sig.scenarios)


@pytest.mark.skipif(not (ROOT / "vendor" / "track2" / "units" / "t2-F2-abenomics-2012").exists(), reason="vendor units not checked out")
def test_numeric_summary_and_pipeline_on_a_real_unit(server):
    from t2agent.text_layer.summary import numeric_summary_for_unit
    unit = ROOT / "vendor" / "track2" / "units" / "t2-F2-abenomics-2012"
    summary = numeric_summary_for_unit(unit)
    assert summary.assets == ("JPY",) and summary.horizon_sd[("JPY", 63)] > 0 and summary.spot["JPY"] > 0
    budget = CallBudget()
    sig = read_text(unit, summary, budget, env=server.env())
    assert sig.fallback_reason is None and 2 <= budget.used <= C.HARD_REQUEST_CAP
    assert any(e.established for e in sig.evidence)
