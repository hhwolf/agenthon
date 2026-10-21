"""Text layer tests (Phase 3): offline mode, budget counting incl. failures, JSON repair, majority vote,
neutral on errors, pre-pass, relevance, label->number table, text_v1 forecaster, mock House accounting."""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from mock_house import MockHouse, delay, error, ok
from t2agent import numeric_v1, numeric_v1_1, text_v1
from t2agent.contracts import CallBudget, NumericSummary, TextSignal
from t2agent.text_layer import constants as C
from t2agent.text_layer import read_text
from t2agent.text_layer.client import request_key_from_body
from t2agent.text_layer.corpus import card_keywords, load_corpus, plan_chunks, prioritise
from t2agent.text_layer.labels import AssetLabel, Branch, Labels, parse_labels, vote
from t2agent.text_layer.parse import ParseError, RawEvidence, extract_json
from t2agent.text_layer.prepass import find_events, horizon_window, run_prepass
from t2agent.text_layer.relevance import score_documents
from t2agent.text_overlay import apply_text_map

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
        "The Committee decided to maintain the target range for the federal funds rate at 1/4 to 1/2 percent. Voting for the FOMC monetary policy action were: Janet L. Yellen, Chair."),
    "bis_carney_2016-05-12": ("2016-05-12", "cb_speech",
        "Mark Carney: Opening remarks at the Inflation Report press conference, 12 May 2016.\n\n"
        "A vote to leave the EU could have material economic effects on the exchange rate, on demand and on supply.\n\n"
        "Sterling has depreciated by around nine percent since its November peak, reflecting referendum uncertainty."),
}
OFF_TOPIC = ("2016-04-02", "cb_speech",
             "Remarks on payment system modernisation in Brazil.\n\nThe central bank of Brazil continues to upgrade the instant payments "
             "infrastructure and the real-time gross settlement system, with no implications for monetary policy settings.")


def make_unit(tmp_path: Path, docs=DOCS, extra_index: list | None = None, name: str = "unit") -> Path:
    unit = tmp_path / name
    text = unit / "text"
    text.mkdir(parents=True)
    index = {"card_id": "t2-TEST-brexit-2016", "asof": ASOF.isoformat(), "documents": []}
    for doc_id, (ts, doc_type, body) in docs.items():
        (text / f"{doc_id}.txt").write_text(body, encoding="utf-8")
        index["documents"].append({"doc_id": doc_id, "timestamp": ts, "source": "test", "doc_type": doc_type, "file": f"{doc_id}.txt"})
    index["documents"].extend(extra_index or [])
    (text / "corpus_index.json").write_text(json.dumps(index))
    return unit


def make_summary(assets=("GBP",), family="T2-F2", notes="A scheduled binary risk event falls shortly after the as-of date."):
    return NumericSummary(
        unit_id="t2-TEST-brexit-2016", asof=ASOF, family=family, target_type="level", value_unit="usd_per_gbp",
        assets=tuple(assets), horizons=(21,), spot={a: 1.42 for a in assets},
        horizon_sd={(a, 21): 0.035 for a in assets}, vol_ratio={a: 1.3 for a in assets},
        card_description="GBP/USD into the EU referendum (21 BD).", card_text_notes=notes)


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


def numeric_neutral(sig: TextSignal, assets=("GBP",)) -> bool:
    n = TextSignal.neutral(assets)
    return sig.scenarios == n.scenarios and sig.tail_mult == 1.0


def ev(doc_id="boe_mpc_2016-06-16", established=True, direction=1):
    return RawEvidence(doc_id, "2016-06-16", "claim", "quote", ("GBP",), direction, established, "decision")


# --------------------------------------------------------------------------- #
# Happy path: labels, self-consistency, request hygiene
# --------------------------------------------------------------------------- #

def test_happy_path_labels_and_neutral_numbers(unit, server):
    sig, budget = run(unit, server)
    assert sig.fallback_reason is None
    assert sig.calls_used == budget.used == len(server.requests) == 1 + C.SYNTHESIS_RUNS
    assert numeric_neutral(sig)                       # Phase 3 leaves magnitudes to text_map
    L = sig.labels
    assert L["mode"] == "llm" and L["schema"] == C.LABELS_SCHEMA_VERSION
    assert L["regime"] == "elevated" and L["event_in_horizon"] == "scheduled_binary"
    assert L["assets"]["GBP"]["direction"] == "up" and L["assets"]["GBP"]["direction_established"]
    assert len(L["branches"]) == 2 and {b["signs"]["GBP"] for b in L["branches"]} == {1, -1}
    assert L["runs"] == 3 and L["agreement"]["regime"] == pytest.approx(2 / 3) and L["agreement"]["overall"] < 1
    assert L["votes"]["regime"].count("elevated") == 2
    assert any(e.established for e in sig.evidence) and all(e.doc_id in DOCS for e in sig.evidence)
    assert "### Labels" in sig.rationale_md and "Self-consistency: 3" in sig.rationale_md


def test_requests_are_pinned_thinking_flagged_and_seeds_vary(unit, server):
    sig, _ = run(unit, server)
    assert sig.fallback_reason is None
    bodies = server.bodies()
    for req, body in zip(server.requests, bodies):
        assert req["path"] == "/v1/chat/completions" and req["headers"]["authorization"] == f"Bearer {server.token}"
        assert body["model"] == server.model and body["temperature"] == 0.0 and body["max_tokens"] <= 4000
        assert "n" not in body and "tools" not in body and "functions" not in body
        prompt = body["messages"][1]["content"]
        assert f"AS-OF DATE: {ASOF.isoformat()}" in prompt and "Do not use any knowledge" in prompt
    extraction = [b for b in bodies if "DOCUMENTS (part" in b["messages"][1]["content"]]
    labels = [b for b in bodies if "TASK: LABELS" in b["messages"][1]["content"]]
    assert len(extraction) == 1 and len(labels) == 3
    assert all(b["chat_template_kwargs"] == {"enable_thinking": False} for b in extraction)
    assert all(b["chat_template_kwargs"] == {"enable_thinking": True} for b in labels)
    assert sorted(b["seed"] for b in labels) == [C.SEED, C.SEED + 1, C.SEED + 2]
    prompts = {b["messages"][1]["content"] for b in labels}
    assert len(prompts) == 3                       # evidence order permuted per run, numbering stable
    assert "[1] (" in next(iter(prompts))


def test_prompt_is_deterministic(unit, server):
    run(unit, server)
    run(unit, server)
    first, second = server.bodies()[:4], server.bodies()[4:]
    assert sorted(json.dumps(b, sort_keys=True) for b in first) == sorted(json.dumps(b, sort_keys=True) for b in second)


def test_neutral_and_real_signals_through_numeric_adapter(unit, server):
    sig, _ = run(unit, server)
    card = {"targets": {"asset_ids": ["GBP"], "horizons": [21]}}
    samples = np.random.default_rng(0).normal(size=(2000, 1))
    assert numeric_v1.apply_text_signal(samples, card, sig, seed=1) is samples      # Phase 3 signal is numerically neutral
    mapped = apply_text_map(sig, make_summary(), 1.0)
    adjusted = numeric_v1.apply_text_signal(samples, card, mapped, seed=1)
    assert adjusted.shape == samples.shape and np.isfinite(adjusted).all() and not np.allclose(adjusted, samples)


# --------------------------------------------------------------------------- #
# Offline, notes-only, replay
# --------------------------------------------------------------------------- #

def test_offline_network_none_makes_no_attempt(unit, server):
    sig, budget = run(unit, server, env=server.env(network="none"))
    assert numeric_neutral(sig) and sig.fallback_reason.startswith("offline")
    assert sig.calls_used == 0 and budget.used == 0 and server.requests == []
    assert sig.labels["mode"] == "neutral" and sig.labels["prepass"]["binary_event_inside"]


def test_offline_without_endpoint(unit, server):
    env = {k: v for k, v in server.env().items() if k != "MODEL_ENDPOINT"}
    sig, budget = run(unit, server, env=env)
    assert numeric_neutral(sig) and "MODEL_ENDPOINT" in sig.fallback_reason and budget.used == 0 and server.requests == []


def test_notes_only_mode_uses_no_model(unit, server):
    sig, budget = run(unit, server, mode="notes_only")
    assert sig.fallback_reason is None and budget.used == 0 and server.requests == []
    L = sig.labels
    assert L["mode"] == "notes_only" and L["event_in_horizon"] == "scheduled_binary" and L["regime"] == "calm"  # no crisis vocabulary
    assert all(v["direction"] == "none" for v in L["assets"].values()) and len(L["branches"]) == 2
    stressed = read_text(unit, make_summary(notes="Funding stress and liquidity turmoil: a scheduled binary risk event falls inside the window."),
                         CallBudget(), env=server.env(), mode="notes_only")
    assert stressed.labels["regime"] == "elevated" and stressed.labels["notes_only_inputs"]["crisis_cues"] >= 1
    wide = NumericSummary(**{**make_summary().__dict__, "vol_ratio": {"GBP": 1.8},
                             "card_text_notes": "Funding stress and liquidity turmoil ahead of the referendum."})
    assert read_text(unit, wide, CallBudget(), env=server.env(), mode="notes_only").labels["regime"] == "calm"  # panel already wide
    env_sig, _ = run(unit, server, env=dict(server.env(), TEXT_LAYER_MODE="notes_only"))
    assert env_sig.labels == L


def test_cache_then_replay_only_without_network(unit, server, tmp_path):
    env = dict(server.env(), TEXT_LAYER_CACHE_DIR=str(tmp_path / "cache"))
    sig1, b1 = run(unit, server, env=env)
    assert sig1.fallback_reason is None and b1.used == 4
    dead = dict(env, MODEL_ENDPOINT="http://127.0.0.1:9", TEXT_LAYER_REPLAY_ONLY="1")
    sig2, b2 = run(unit, server, env=dead)
    assert sig2.fallback_reason is None and b2.used == 0 and sig2.calls_used == 0
    assert sig2.labels["regime"] == sig1.labels["regime"] and sig2.labels["assets"] == sig1.labels["assets"]
    assert len(server.requests) == 4 and "served from the dev cache" in sig2.rationale_md
    miss = dict(dead, TEXT_LAYER_CACHE_DIR=str(tmp_path / "empty"))
    sig3, b3 = run(unit, server, env=miss)
    assert numeric_neutral(sig3) and "replay-only" in sig3.fallback_reason and b3.used == 0 and len(server.requests) == 4


def test_mock_house_replays_recorded_responses(unit, server, tmp_path):
    env = dict(server.env(), TEXT_LAYER_CACHE_DIR=str(tmp_path / "cache"))
    sig1, _ = run(unit, server, env=env)
    for req in server.requests:
        assert any(p.stem == request_key_from_body(req["body"]) for p in (tmp_path / "cache").glob("*.json"))
    with MockHouse(scenario="server_error", replay_dir=tmp_path / "cache") as replay:
        sig2 = read_text(unit, make_summary(), CallBudget(), env=replay.env())
        assert sig2.fallback_reason is None and sig2.labels["assets"] == sig1.labels["assets"]
        assert all(r["admitted"] for r in replay.requests) and len(replay.requests) == 4


# --------------------------------------------------------------------------- #
# Labels: validation and majority vote
# --------------------------------------------------------------------------- #

def test_parse_labels_validation():
    evidence = [ev(established=True), ev(established=False)]
    obj = {"regime": "High", "event_in_horizon": "scheduled binary", "disagreement": "yes",
           "assets": {"gbp": {"direction": "Strongly up", "direction_established": True, "evidence": [2]}},
           "branches": [{"label": "leave", "prob": 0.3, "signs": {"GBP": "-"}}, {"label": "remain", "prob": 0.6, "signs": {"GBP": 1}}]}
    L = parse_labels(obj, ("GBP",), evidence)
    assert L.regime == "elevated" and L.event_in_horizon == "scheduled_binary" and L.disagreement is True
    assert L.assets["GBP"].direction == "strong_up" and L.assets["GBP"].direction_established is False  # cites only an inferred item
    assert [round(b.prob, 3) for b in L.branches] == [0.333, 0.667] and L.branches[0].signs == {"GBP": -1}
    uncited = parse_labels({"regime": "calm", "assets": {"GBP": {"direction": "up", "evidence": []}}}, ("GBP",), evidence)
    assert uncited.assets["GBP"].direction == "none"
    three = parse_labels({"regime": "calm", "event_in_horizon": "scheduled_binary", "assets": {},
                          "branches": [{"prob": 0.4, "signs": {}}, {"prob": 0.3, "signs": {}}, {"prob": 0.3, "signs": {}}]}, ("GBP",), evidence)
    assert three.event_in_horizon == "ongoing" and three.branches == ()
    listed = parse_labels({"regime": "crisis", "assets": [{"asset": "GBP", "direction": "down", "evidence": [1]}]}, ("GBP",), evidence)
    assert listed.assets["GBP"].direction == "down"
    with pytest.raises(ParseError):
        parse_labels({"foo": 1}, ("GBP",), evidence)


def test_majority_vote_and_ties():
    a = Labels("elevated", "none", False, {"GBP": AssetLabel("up", True, (1,))})
    b = Labels("elevated", "none", False, {"GBP": AssetLabel("up", False, (2,))})
    c = Labels("crisis", "ongoing", True, {"GBP": AssetLabel("down", True, (3,))})
    L, agreement, votes = vote([a, b, c], ("GBP",))
    assert L.regime == "elevated" and L.event_in_horizon == "none" and L.disagreement is False
    assert L.assets["GBP"].direction == "up" and L.assets["GBP"].direction_established is True and L.assets["GBP"].evidence == (1, 2)
    assert agreement["regime"] == pytest.approx(2 / 3) and agreement["runs"] == 3 and votes["regime"] == ["elevated", "elevated", "crisis"]
    L2, _, _ = vote([a, c, Labels("calm", "scheduled_binary", False, {"GBP": AssetLabel("none")})], ("GBP",))
    assert L2.regime == "calm" and L2.event_in_horizon == "none" and L2.assets["GBP"].direction == "none"   # three-way ties -> neutral
    L3, _, _ = vote([a, c], ("GBP",))
    assert L3.regime == "calm" and L3.assets["GBP"].direction == "none"                                     # two-way tie -> neutral
    L4, _, _ = vote([a], ("GBP",))
    assert L4.regime == "elevated"                                                                           # a single run stands alone


def test_vote_aligns_binary_branches():
    br = lambda s0, p: (Branch("A", p, {"GBP": s0}), Branch("B", 1 - p, {"GBP": -s0}))  # noqa: E731
    r1 = Labels("elevated", "scheduled_binary", False, {"GBP": AssetLabel()}, br(1, 0.6))
    r2 = Labels("elevated", "scheduled_binary", False, {"GBP": AssetLabel()}, br(-1, 0.5))   # branches listed the other way round
    r3 = Labels("elevated", "none", False, {"GBP": AssetLabel()})
    L, _, _ = vote([r1, r2, r3], ("GBP",))
    assert L.event_in_horizon == "scheduled_binary" and len(L.branches) == 2
    assert L.branches[0].signs == {"GBP": 1} and L.branches[0].prob == pytest.approx(0.55)


def test_out_of_schema_model_output_is_contained(unit, server):
    server.scenario = "extreme"
    sig, budget = run(unit, server)
    assert sig.fallback_reason is None and budget.used == 4
    L = sig.labels
    assert L["regime"] == "calm" and L["disagreement"] is False
    assert L["assets"]["GBP"]["direction"] == "none"           # uncited strong_up dropped
    assert L["event_in_horizon"] == "ongoing" and L["branches"] == []
    assert all(not e.established for e in sig.evidence) and all(e.doc_id in DOCS for e in sig.evidence)
    mapped = apply_text_map(sig, make_summary(), 1.0)
    assert all(1.0 <= s.vol_mult <= 2.0 and abs(s.drift_sd["GBP"]) <= 1.5 for s in mapped.scenarios) and 1.0 <= mapped.tail_mult <= 2.0


# --------------------------------------------------------------------------- #
# Budget counting, failures, time
# --------------------------------------------------------------------------- #

def test_failed_calls_count_against_budget(unit, server):
    server.push(error(500), error(502))
    sig, budget = run(unit, server)
    assert numeric_neutral(sig) and "HTTP 502" in sig.fallback_reason and sig.labels["mode"] == "notes_only_fallback"
    assert budget.used == sig.calls_used == len(server.requests) == 1 + C.MAX_RETRIES_PER_CALL


def test_auth_failures_are_not_retried(unit, server):
    for status in (401, 403):
        server.requests.clear()
        server.push(error(status, "nope"))
        sig, budget = run(unit, server)
        assert numeric_neutral(sig) and str(status) in sig.fallback_reason and budget.used == 1 and len(server.requests) == 1


def test_transient_error_then_success(unit, server):
    server.push(error(503))
    sig, budget = run(unit, server)
    assert sig.fallback_reason is None and budget.used == 5 == len(server.requests)


def test_timeout_is_neutral_and_bounded(unit, server, monkeypatch):
    monkeypatch.setattr(C, "REQUEST_TIMEOUT_S", 0.5)
    monkeypatch.setattr(C, "MIN_REQUEST_TIMEOUT_S", 0.1)
    monkeypatch.setattr(C, "SAFETY_MARGIN_S", 0.0)
    monkeypatch.setattr(C, "MAX_RETRIES_PER_CALL", 0)
    server.push(delay(3.0))
    t0 = time.monotonic()
    sig, budget = run(unit, server, time_budget_s=30)
    assert numeric_neutral(sig) and time.monotonic() - t0 < 2.5 and budget.used == 1
    assert "timeout" in sig.fallback_reason.lower()


def test_time_budget_too_small_sends_nothing(unit, server, monkeypatch):
    monkeypatch.setattr(C, "SAFETY_MARGIN_S", 0.0)
    sig, budget = run(unit, server, time_budget_s=1.0)
    assert numeric_neutral(sig) and "TimeExhausted" in sig.fallback_reason and budget.used == 0 and server.requests == []


def test_budget_limits_shrink_runs_then_refuse(unit, server):
    sig3, b3 = run(unit, server, budget=CallBudget(limit=3))      # 1 extraction + 1 synthesis run
    assert sig3.fallback_reason is None and b3.used == 2 and sig3.labels["runs"] == 1
    sig2, b2 = run(unit, server, budget=CallBudget(limit=2))      # no room for extraction + reserve
    assert numeric_neutral(sig2) and "BudgetExhausted" in sig2.fallback_reason and b2.used == 0
    shared = CallBudget(limit=5, used=5)
    sig0, _ = run(unit, server, budget=shared)
    assert numeric_neutral(sig0) and shared.used == 5


def test_hard_cap_holds_for_huge_corpus(tmp_path, server):
    para = ("Paragraph about policy, inflation and sterling with a dated statement from 2016-05-05 that matters for "
            "the horizon and runs long enough to be a real paragraph. ")
    docs = {f"speech_{i:02d}_2016-0{1 + i % 5}-1{i % 9}": (f"2016-0{1 + i % 5}-1{i % 9}", "cb_speech",
                                                           "".join(f"Speech {i} section {k}. " + para * 60 + "\n\n" for k in range(15)))
            for i in range(40)}
    unit = make_unit(tmp_path, docs)
    sig, budget = run(unit, server)
    assert sig.fallback_reason is None
    assert budget.used == C.MAX_EXTRACTION_CALLS + C.SYNTHESIS_RUNS <= C.HARD_REQUEST_CAP
    for body in server.bodies():
        assert sum(len(m["content"]) for m in body["messages"]) // C.CHARS_PER_TOKEN <= 60_000
    assert "Not sent (budget)" in sig.rationale_md


def test_context_overflow_splits_the_chunk(unit, server):
    server.push(error(400, "This model's maximum context length is 8192 tokens; your request used 9000."))
    sig, budget = run(unit, server)
    assert sig.fallback_reason is None and budget.used == 1 + 2 + C.SYNTHESIS_RUNS and "split in two" in sig.rationale_md


def test_mock_house_allowance_is_enforced_and_counted(unit, server):
    server.allowance = 1                                  # extraction admitted, every label run refused with 429
    sig, budget = run(unit, server)
    assert numeric_neutral(sig) and "every synthesis run failed" in sig.fallback_reason
    assert sum(1 for r in server.requests if r["admitted"]) == 1
    assert budget.used == len(server.requests) == 1 + C.SYNTHESIS_RUNS * (1 + C.MAX_RETRIES_PER_CALL)
    assert all(r["max_tokens_effective"] <= 4000 for r in server.requests if r["admitted"])
    server.allowance = 2                                  # one label run survives: the vote proceeds on it
    server.requests.clear(); server.reset_accounting()
    sig2, _ = run(unit, server)
    assert sig2.fallback_reason is None and sig2.labels["runs"] == 1


# --------------------------------------------------------------------------- #
# JSON repair and partial synthesis failures
# --------------------------------------------------------------------------- #

def test_extraction_json_repaired_once(unit, server):
    server.push(ok("Sure! Here is what I found, in prose rather than JSON."))
    sig, budget = run(unit, server)
    assert sig.fallback_reason is None and budget.used == 2 + C.SYNTHESIS_RUNS
    repair = server.bodies()[1]["messages"]
    assert [m["role"] for m in repair] == ["system", "user", "assistant", "user"] and "not a valid JSON" in repair[-1]["content"]


def test_extraction_repair_failure_is_neutral(unit, server):
    server.push(ok("still prose"), ok("and again prose"))
    sig, budget = run(unit, server)
    assert numeric_neutral(sig) and "ParseError" in sig.fallback_reason and budget.used == 2


EXTRACTION = {"evidence": [{"doc_id": "boe_mpc_2016-06-16", "timestamp": "2016-06-16", "claim": "Rate held.",
                            "quote": "maintain Bank Rate at 0.5%", "assets": ["GBP"], "direction": 0, "established": True, "kind": "decision"}],
              "scheduled_events": [], "disagreements": []}


def test_labels_repair_runs_with_thinking_off(unit, server, monkeypatch):
    monkeypatch.setattr(C, "MAX_PARALLEL_SYNTHESIS", 1)
    server.push(ok(json.dumps(EXTRACTION)), ok("", finish_reason="length"))
    sig, budget = run(unit, server)
    assert sig.fallback_reason is None and budget.used == 1 + 1 + C.SYNTHESIS_RUNS and sig.labels["runs"] == 3
    flags = [b["chat_template_kwargs"]["enable_thinking"] for b in server.bodies()]
    assert flags[:3] == [False, True, False]


def test_one_failed_synthesis_run_is_excluded_from_the_vote(unit, server, monkeypatch):
    monkeypatch.setattr(C, "MAX_PARALLEL_SYNTHESIS", 1)
    server.push(ok(json.dumps(EXTRACTION)), error(500), error(502))
    sig, budget = run(unit, server)
    assert sig.fallback_reason is None and sig.labels["runs"] == 2 and budget.used == 1 + 2 + 2
    assert "1 of 3 synthesis run(s) failed" in sig.rationale_md


def test_all_synthesis_runs_failing_is_neutral(unit, server):
    server.scenario = "invalid_json"
    server.push(ok(json.dumps(EXTRACTION)))
    sig, budget = run(unit, server)
    assert numeric_neutral(sig) and "every synthesis run failed" in sig.fallback_reason
    assert budget.used == 1 + 3 * C.SYNTHESIS_RUNS      # call + repair + compact retry per run, still <= the 20 cap
    assert budget.used <= C.HARD_REQUEST_CAP and sig.labels["mode"] == "notes_only_fallback"


def test_truncated_and_fenced_outputs_are_tolerated(unit, server):
    for scenario in ("truncated", "think"):
        server.scenario = scenario
        server.requests.clear()
        sig, budget = run(unit, server)
        assert sig.fallback_reason is None, scenario
        assert budget.used == 4, scenario


def test_extract_json_cases():
    assert extract_json('```json\n{"regime": "calm"}\n```', prefer_keys=("regime",))["regime"] == "calm"
    assert extract_json('<think>{"not": 1}</think>\n{"evidence": []}') == {"evidence": []}
    obj = extract_json('{"evidence": [{"doc_id": "a", "claim": "b", "established": true}, {"doc_id": "c", "cla')
    assert obj["evidence"][0]["doc_id"] == "a"
    with pytest.raises(ParseError):
        extract_json("no json here")


# --------------------------------------------------------------------------- #
# Pre-pass, relevance, corpus handling
# --------------------------------------------------------------------------- #

def test_prepass_dates_kinds_and_card_flags():
    s = make_summary()
    end, days = horizon_window(s)
    assert days >= C.MIN_HORIZON_DAYS and end > ASOF
    boe = find_events(DOCS["boe_mpc_2016-06-16"][2], "boe", ASOF, end)
    assert any(e.kind == "referendum" and e.event_date == date(2016, 6, 23) and e.inside_horizon for e in boe)
    fomc = find_events(DOCS["fomc_statement_2016-06-15"][2] + " The next meeting of the Committee would be held on July 26-27, 2016.", "fomc", ASOF, end)
    assert all(e.kind != "vote" for e in fomc) and any(e.kind == "policy_meeting" and e.event_date == date(2016, 7, 26) for e in fomc)
    ranged = find_events("The Committee met on March 19-20, 2013. By unanimous vote, the Committee ratified.", "x", date(2013, 5, 24), date(2013, 11, 27))
    assert ranged == []                                   # past date with explicit year is not a future event
    unit_docs = [type("D", (), {"doc_id": k, "timestamp": v[0], "doc_type": v[1], "source": "", "text": v[2]})() for k, v in DOCS.items()]
    pre = run_prepass(s, unit_docs)
    assert pre.card_binary_kind and pre.binary_event_inside and "BoE" in pre.latest_decisions and "Fed" in pre.latest_decisions
    plain = NumericSummary(**{**s.__dict__, "card_description": "GBP/USD continuation (21 BD).", "card_text_notes": "Routine continuation card."})
    calm = run_prepass(plain, unit_docs)
    assert not calm.card_binary_kind and calm.binary_event_inside   # the BoE decision names the referendum date inside the horizon
    assert not run_prepass(plain, unit_docs[1:2]).binary_event_inside  # the FOMC statement alone: "Voting for" is not a vote event


def test_relevance_ranks_off_topic_speech_last(tmp_path, server):
    docs = dict(DOCS, bis_brazil_2016_04_02=OFF_TOPIC)
    unit = make_unit(tmp_path, docs)
    s = make_summary()
    loaded = load_corpus(unit, ASOF, [])
    kw = card_keywords(s.card_description, s.card_text_notes, assets=s.assets)
    rel = score_documents({d.doc_id: d.text for d in loaded}, s.assets, kw)
    assert rel["bis_brazil_2016_04_02"].off_topic and not rel["bis_carney_2016-05-12"].off_topic
    ranked = prioritise(loaded, ASOF, kw, rel)
    assert ranked[0].doc_type == "central_bank_decision" and ranked[-1].doc_id == "bis_brazil_2016_04_02"
    assert not rel["fomc_statement_2016-06-15"].off_topic or ranked.index(next(d for d in ranked if d.doc_id == "fomc_statement_2016-06-15")) < 3
    sig, _ = run(unit, server)
    assert "off-topic by asset terms: bis_brazil_2016_04_02" in sig.rationale_md
    chunks, dropped = plan_chunks(ranked, max_chunks=6)
    assert len(chunks) == 1 and not dropped


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


def test_missing_unit_dir_and_empty_corpus_are_neutral(tmp_path, server):
    sig, budget = run(tmp_path / "nope", server)
    assert numeric_neutral(sig) and budget.used == 0 and server.requests == []
    empty = tmp_path / "empty"
    (empty / "text").mkdir(parents=True)
    sig2, budget2 = run(empty, server)
    assert numeric_neutral(sig2) and budget2.used == 0 and "no readable documents" in sig2.fallback_reason


def test_joint_card_labels_every_asset(unit, server):
    sig = read_text(unit, make_summary(assets=("GBP", "EUR"), family="T2-F3"), CallBudget(), env=server.env())
    assert sig.fallback_reason is None and set(sig.labels["assets"]) == {"GBP", "EUR"}
    assert all(set(b["signs"]) == {"GBP", "EUR"} for b in sig.labels["branches"])
    mapped = apply_text_map(sig, make_summary(assets=("GBP", "EUR"), family="T2-F3"), 1.0)
    assert all(set(s.drift_sd) == {"GBP", "EUR"} for s in mapped.scenarios)


# --------------------------------------------------------------------------- #
# Label -> number table and the text_v1 forecaster
# --------------------------------------------------------------------------- #

def _labelled(**over):
    base = {"schema": C.LABELS_SCHEMA_VERSION, "mode": "llm", "regime": "calm", "event_in_horizon": "none", "disagreement": False,
            "assets": {"GBP": {"direction": "none", "direction_established": False, "evidence": []}}, "branches": [], "summary": ""}
    base.update(over)
    sig = TextSignal.neutral(("GBP",))
    from dataclasses import replace
    return replace(sig, labels=base)


def test_text_map_table_values_and_lambda():
    s = make_summary()
    calm = apply_text_map(_labelled(), s, 1.0)
    assert calm.scenarios[0].drift_sd["GBP"] == 0.0 and calm.scenarios[0].vol_mult == 1.0 and calm.tail_mult == 1.0
    elevated = apply_text_map(_labelled(regime="elevated"), s, 1.0)
    assert elevated.scenarios[0].vol_mult == 1.25
    assert apply_text_map(_labelled(regime="elevated"), s, 0.5).scenarios[0].vol_mult == 1.125
    crisis = apply_text_map(_labelled(regime="crisis"), s, 1.0)
    assert crisis.scenarios[0].vol_mult == 1.6 and crisis.tail_mult == 1.5
    up = apply_text_map(_labelled(assets={"GBP": {"direction": "strong_up", "direction_established": True, "evidence": [1]}}), s, 1.0)
    assert up.scenarios[0].drift_sd["GBP"] == 0.5
    dis = apply_text_map(_labelled(disagreement=True, assets={"GBP": {"direction": "up"}}), s, 1.0)
    assert dis.scenarios[0].drift_sd["GBP"] == 0.0 and dis.scenarios[0].vol_mult == 1.15
    binary = apply_text_map(_labelled(event_in_horizon="scheduled_binary", regime="elevated",
                                      branches=[{"label": "leave", "prob": 0.9, "signs": {"GBP": -1}}, {"label": "remain", "prob": 0.1, "signs": {"GBP": 1}}]), s, 1.0)
    assert [round(x.weight, 2) for x in binary.scenarios] == [0.8, 0.2]
    # Explicit Phase 4 branches retain +/-1 sd at the clipped 80/20 weights.
    assert [x.drift_sd["GBP"] for x in binary.scenarios] == [-1., 1.]
    assert abs(sum(x.weight * x.drift_sd["GBP"] for x in binary.scenarios)) <= 0.6 + 1e-9 and binary.tail_mult == 1.25
    even = apply_text_map(_labelled(event_in_horizon="scheduled_binary", regime="elevated",
                                    branches=[{"label": "a", "prob": 0.5, "signs": {"GBP": -1}}, {"label": "b", "prob": 0.5, "signs": {"GBP": 1}}]), s, 1.0)
    assert [x.drift_sd["GBP"] for x in even.scenarios] == [-1.0, 1.0] and [x.vol_mult for x in even.scenarios] == [1.25, 1.25]
    shock = apply_text_map(_labelled(regime="crisis", assets={"GBP": {"direction": "down", "evidence": [1]}}), s, 1.0)
    assert len(shock.scenarios) == 1 and shock.tail_signs == {"GBP": -1} and shock.tail_mult == 1.5
    assert apply_text_map(_labelled(regime="crisis"), s, 0.0).scenarios[0].vol_mult == 1.0            # λ = 0 -> numeric only
    neutral = TextSignal.neutral(("GBP",), reason="offline")
    assert apply_text_map(neutral, s, 1.0) is neutral
    assert "Label -> number mapping" in crisis.rationale_md and "Adjustment ledger" in crisis.rationale_md


def test_text_v1_forecaster_modes(unit, server, monkeypatch):
    card = {"task": {"id": "t2-TEST-brexit-2016"}, "provenance": {"data_cutoff": ASOF.isoformat()},
            "targets": {"asset_ids": ["GBP"], "horizons": [21], "target_type": "level", "value_unit": "usd_per_gbp"},
            "metadata": {"category": "T2-F2", "description": "GBP/USD into the EU referendum (21 BD)."},
            "text": {"notes": "A scheduled binary risk event falls shortly after the as-of date."}}
    import pandas as pd
    dates = pd.bdate_range(end=ASOF, periods=400)
    rng = np.random.default_rng(3)
    panels = {"g10_fx_daily.parquet": pd.DataFrame({"asset_id": "GBP", "date": dates, "value": 1.45 + np.cumsum(rng.normal(0, 0.005, len(dates)))})}
    for k, v in server.env().items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("TEXT_LAYER_LAMBDA", "0.5")
    # The release config disables House; this explicit labels experiment re-enables it.
    monkeypatch.setattr(numeric_v1, "text_settings", lambda: {"mode": "labels", "lambda": .5, "house_calls": True})
    text = text_v1.forecast(card, panels, unit / "text", ASOF.isoformat(), 500, 11)
    numeric = numeric_v1_1.forecast(card, panels, None, ASOF.isoformat(), 500, 11)
    assert not np.allclose(text.value.to_numpy(), numeric.value.to_numpy()) and len(server.requests) == 4
    assert "Label -> number mapping" in text.attrs["rationale"] and "### Labels" in text.attrs["rationale"]
    monkeypatch.setenv("QFBENCH_NETWORK", "none")
    offline = text_v1.forecast(card, panels, unit / "text", ASOF.isoformat(), 500, 11)
    assert np.array_equal(offline.value.to_numpy(), numeric.value.to_numpy()) and "offline" in offline.attrs["rationale"]
    notes = text_v1.forecast_notes_only_l10(card, panels, unit / "text", ASOF.isoformat(), 500, 11)
    assert notes.attrs["text_signal"].labels["mode"] == "notes_only" and not np.allclose(notes.value.to_numpy(), numeric.value.to_numpy())
    assert len(server.requests) == 4                       # neither offline nor notes-only touched the network
    no_text = text_v1.forecast(card, panels, None, ASOF.isoformat(), 500, 11)
    assert np.array_equal(no_text.value.to_numpy(), numeric.value.to_numpy())


def test_candidate_config_uses_house_when_present_and_degrades_to_card_labels(unit, server, monkeypatch):
    """LLM-label candidate: labels mode with House calls enabled; offline is numeric-only; a failed House route
    degrades to the frozen release's card-only labels."""
    settings = numeric_v1.text_settings()
    assert settings["mode"] == "labels" and settings["lambda"] == 0.5 and settings["house_calls"] is True
    card = {"task": {"id": "t2-TEST-brexit-2016"}, "provenance": {"data_cutoff": ASOF.isoformat()},
            "targets": {"asset_ids": ["GBP"], "horizons": [21], "target_type": "level", "value_unit": "usd_per_gbp"},
            "metadata": {"category": "T2-F2", "description": "GBP/USD into the EU referendum (21 BD)."},
            "text": {"notes": "A scheduled binary risk event falls shortly after the as-of date."}}
    import pandas as pd
    dates = pd.bdate_range(end=ASOF, periods=400)
    rng = np.random.default_rng(3)
    panels = {"g10_fx_daily.parquet": pd.DataFrame({"asset_id": "GBP", "date": dates, "value": 1.45 + np.cumsum(rng.normal(0, 0.005, len(dates)))})}
    for k, v in server.env().items():
        monkeypatch.setenv(k, v)
    for k in ("QFBENCH_NETWORK", "TEXT_LAYER_MODE", "TEXT_LAYER_LAMBDA"):
        monkeypatch.delenv(k, raising=False)
    numeric = numeric_v1_1.forecast(card, panels, None, ASOF.isoformat(), 500, 11)
    with_house = numeric_v1_1.forecast(card, panels, unit / "text", ASOF.isoformat(), 500, 11)
    assert 4 <= len(server.requests) <= 6 and all(r["admitted"] for r in server.requests)
    assert not np.allclose(with_house.value.to_numpy(), numeric.value.to_numpy())
    assert "mode llm" in with_house.attrs["rationale"] and "Label -> number mapping" in with_house.attrs["rationale"]
    server.requests.clear()
    monkeypatch.setenv("QFBENCH_NETWORK", "none")
    offline = numeric_v1_1.forecast(card, panels, unit / "text", ASOF.isoformat(), 500, 11)
    assert server.requests == [] and np.array_equal(offline.value.to_numpy(), numeric.value.to_numpy())
    monkeypatch.delenv("QFBENCH_NETWORK")
    server.scenario = "server_error"
    server.reset_accounting()
    degraded = numeric_v1_1.forecast(card, panels, unit / "text", ASOF.isoformat(), 500, 11)
    card_only = numeric_v1_1.forecast(card, panels, unit / "text", ASOF.isoformat(), 500, 11, text_mode="card_notes_only")
    assert np.array_equal(degraded.value.to_numpy(), card_only.value.to_numpy())      # worst case == frozen release
    assert "notes_only_fallback" in degraded.attrs["rationale"]


@pytest.mark.skipif(not (ROOT / "vendor" / "track2" / "units" / "t2-F2-abenomics-2012").exists(), reason="vendor units not checked out")
def test_numeric_summary_and_pipeline_on_a_real_unit(server):
    from t2agent.text_layer.summary import numeric_summary_for_unit
    unit = ROOT / "vendor" / "track2" / "units" / "t2-F2-abenomics-2012"
    summary = numeric_summary_for_unit(unit)
    assert summary.assets == ("JPY",) and summary.horizon_sd[("JPY", 63)] > 0 and summary.spot["JPY"] > 0
    budget = CallBudget()
    sig = read_text(unit, summary, budget, env=server.env())
    assert sig.fallback_reason is None and 2 <= budget.used <= C.HARD_REQUEST_CAP
    assert sig.labels["event_in_horizon"] == "scheduled_binary" and sig.labels["prepass"]["card_binary_kind"]
    assert any(e.established for e in sig.evidence)


# --------------------------------------------------------------------------- #
# Regression tests from the adversarial review (2026-10-15)
# --------------------------------------------------------------------------- #

def test_malformed_corpus_index_falls_back_to_txt(tmp_path):
    for bad in ("[]", '{"documents": null}', '{"documents": "x"}', "not json"):
        unit = tmp_path / f"u{abs(hash(bad))}"
        (unit / "text").mkdir(parents=True)
        (unit / "text" / "boe_2016-06-16.txt").write_text("Bank Rate held at 0.5% ahead of the referendum on 23 June.")
        (unit / "text" / "corpus_index.json").write_text(bad)
        notes: list[str] = []
        docs = load_corpus(unit, ASOF, notes)
        assert [d.doc_id for d in docs] == ["boe_2016-06-16"] and docs[0].timestamp == "2016-06-16", bad
        assert any("falling back" in n for n in notes), bad
    undated = tmp_path / "undated"
    (undated / "text").mkdir(parents=True)
    (undated / "text" / "speech.txt").write_text("No date in this file name, so its timestamp must stay unknown.")
    docs = load_corpus(undated, ASOF, [])
    assert docs[0].timestamp == ""


def test_duplicate_detection_uses_full_text_and_first_doc_id_wins(tmp_path):
    head = "Shared opening paragraph. " * 300          # ~7,800 chars identical
    docs = {"a_2016-06-01": ("2016-06-01", "cb_speech", head + "Tail A differs."),
            "b_2016-06-02": ("2016-06-02", "cb_speech", head + "Tail B differs."),
            "c_2016-06-03": ("2016-06-03", "cb_speech", head + "Tail A differs.")}
    unit = make_unit(tmp_path, docs, extra_index=[{"doc_id": "a_2016-06-01", "timestamp": "2016-06-09", "source": "x",
                                                   "doc_type": "cb_speech", "file": "b_2016-06-02.txt"}])
    notes: list[str] = []
    loaded = load_corpus(unit, ASOF, notes)
    assert [d.doc_id for d in loaded] == ["a_2016-06-01", "b_2016-06-02"]       # c is a true duplicate of a
    assert any("duplicate doc_id" in n for n in notes) and any("duplicate of a_2016-06-01" in n for n in notes)


def test_vote_aligns_branches_by_all_assets():
    A = ("GBP", "EUR")
    r1 = Labels("elevated", "scheduled_binary", False, {a: AssetLabel() for a in A},
                (Branch("leave", 0.6, {"GBP": -1, "EUR": -1}), Branch("remain", 0.4, {"GBP": 1, "EUR": 1})))
    r2 = Labels("elevated", "scheduled_binary", False, {a: AssetLabel() for a in A},
                (Branch("remain", 0.5, {"GBP": 0, "EUR": 1}), Branch("leave", 0.5, {"GBP": 0, "EUR": -1})))   # reversed, first asset 0
    r3 = Labels("elevated", "scheduled_binary", False, {a: AssetLabel() for a in A},
                (Branch("remain", 0.3, {"GBP": 1, "EUR": 1}), Branch("leave", 0.7, {"GBP": -1, "EUR": -1})))  # reversed
    L, _, _ = vote([r1, r2, r3], A)
    assert len(L.branches) == 2
    leave, remain = L.branches
    assert leave.signs == {"GBP": -1, "EUR": -1} and remain.signs == {"GBP": 1, "EUR": 1}
    assert leave.prob == pytest.approx((0.6 + 0.5 + 0.7) / 3) and leave.label == "leave"


def test_malformed_label_shapes_reach_the_repair_path(unit, server, monkeypatch):
    # Shapes that parse_labels now coerces (dict instead of list, scalar evidence) must not raise ...
    odd = {"regime": "calm", "event_in_horizon": "scheduled_binary", "assets": {"GBP": {"direction": "up", "evidence": 1}},
           "branches": {"a": {"label": "a", "prob": 0.5, "signs": {"GBP": 1}}, "b": {"label": "b", "prob": 0.5, "signs": {"GBP": -1}}}}
    L = parse_labels(odd, ("GBP",), [ev()])
    assert L.assets["GBP"].direction == "up" and len(L.branches) == 2
    # ... and any other non-ParseError exception inside the parse stage is converted so the single repair still happens.
    import t2agent.text_layer.pipeline as pl
    calls = {"n": 0}
    real = pl.parse_labels

    def flaky(obj, assets, evidence):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TypeError("unhashable type: 'slice'")
        return real(obj, assets, evidence)

    monkeypatch.setattr(pl, "parse_labels", flaky)
    monkeypatch.setattr(C, "MAX_PARALLEL_SYNTHESIS", 1)
    server.push(ok(json.dumps(EXTRACTION)))
    sig, budget = run(unit, server)
    assert sig.fallback_reason is None and budget.used == 1 + 1 + C.SYNTHESIS_RUNS
    assert "unusable shape" in sig.rationale_md


def test_failed_extraction_stops_siblings_and_budget_is_final(tmp_path, server):
    body = ("Paragraph about sterling, the referendum and policy with a dated statement from 2016-05-05 that runs "
            "long enough to be real. ") * 900                            # ~100K chars = ~25K tokens each
    docs = {f"speech_{i}_2016-05-1{i}": (f"2016-05-1{i}", "cb_speech", body + f" Section marker {i}.") for i in range(3)}
    unit = make_unit(tmp_path, docs)
    server.push(error(401, "bad token"))                                 # the first extraction request fails hard
    sig, budget = run(unit, server)
    assert numeric_neutral(sig) and "401" in sig.fallback_reason
    seen_at_return = len(server.requests)
    time.sleep(0.5)
    assert len(server.requests) == seen_at_return == budget.used == sig.calls_used   # nothing sent after return
    assert budget.used <= 3


def test_year_less_dates_resolve_against_the_document_date():
    end = ASOF.replace(year=ASOF.year) ; end = date(2016, 7, 22)
    text = "The Governor said the referendum on 23 June would be the main risk."
    old_doc = find_events(text, "old", ASOF, end, reference=date(2014, 6, 1))
    assert old_doc == []                                                 # 23 June 2014 is in the past
    fresh = find_events(text, "new", ASOF, end, reference=date(2016, 6, 10))
    assert fresh and fresh[0].event_date == date(2016, 6, 23) and "[year inferred]" in fresh[0].text
    past_dated = find_events("The general election on 7 May 2015 returned a majority; another upcoming election is unlikely.",
                             "x", ASOF, end, reference=date(2016, 6, 1))
    assert past_dated == []                                              # dated past event: no undated fallback


def test_cue_words_match_whole_words_and_bank_needles_are_bounded():
    from t2agent.text_layer.prepass import CRISIS, DOVISH, _bank, _count_cues
    assert _count_cues("increase release decrease executive stressed", CRISIS + DOVISH) == 0
    assert _count_cues("the bank will ease policy; funding stress is acute", CRISIS + DOVISH) == 2
    doc = lambda doc_id: type("D", (), {"doc_id": doc_id, "source": ""})()  # noqa: E731
    assert _bank(doc("pboc_mp_decision_2015-08-11")) == "PBoC" and _bank(doc("boc_rate_decision_2017-07-12")) == "BoC"
    assert _bank(doc("fomc-statement-2016-06-15")) == "Fed" and _bank(doc("bis_shirakawa_2012-11-26")) is None


def test_off_topic_needs_no_asset_term_and_no_card_keyword():
    texts = {"brazil": OFF_TOPIC[2], "referendum_only": "A note on how a referendum changes public finances in general terms.",
             "sterling": DOCS["bis_carney_2016-05-12"][2]}
    rel = score_documents(texts, ("GBP",), {"referendum", "scheduled", "binary"})
    assert rel["brazil"].off_topic and rel["brazil"].specific_hits == 0 and rel["brazil"].card_hits == 0
    assert not rel["referendum_only"].off_topic and rel["referendum_only"].specific_hits == 0 and rel["referendum_only"].card_hits == 1
    assert not rel["sterling"].off_topic and rel["sterling"].specific_hits >= 1


def test_evidence_numbering_is_stable_across_permuted_runs(unit, server):
    import re
    sig, _ = run(unit, server)
    assert sig.fallback_reason is None
    runs = [b["messages"][1]["content"] for b in server.bodies() if "TASK: LABELS" in b["messages"][1]["content"]]
    numbered = [re.findall(r"^\[(\d+)\] \(([EI])\) (.+)$", p, re.M) for p in runs]
    assert len(numbered) == 3 and all(len(n) == len(numbered[0]) >= 3 for n in numbered)
    assert all(set(n) == set(numbered[0]) for n in numbered)            # same (number, flag, line) triples
    assert any(n != numbered[0] for n in numbered[1:])                   # but presented in a different order


def test_clamp_scenarios_unit():
    from t2agent.text_layer.parse import RawScenario, RawSignal
    from t2agent.text_layer.signal import Ledger, clamp_scenarios
    raw = RawSignal((RawScenario("a", 0.7, {"X": 2.0}, 0.5, ()), RawScenario("b", 0.29, {"X": -0.2}, 3.0, ()),
                     RawScenario("c", 0.01, {"X": 0.0}, 1.0, ())), 9.0, (), "")
    ledger = Ledger()
    scenarios, tail = clamp_scenarios(raw, ("X",), has_established=False, ledger=ledger)
    assert [s.label for s in scenarios] == ["a", "b"] and abs(sum(s.weight for s in scenarios) - 1) < 1e-9
    assert all(abs(s.drift_sd["X"]) <= 1.5 for s in scenarios) and abs(sum(s.weight * s.drift_sd["X"] for s in scenarios)) <= 0.5 + 1e-9
    assert [s.vol_mult for s in scenarios] == [1.0, 2.0] and tail == 2.0
    assert any("dropped" in c for c in ledger.clamps) and any("rescaled" in c for c in ledger.clamps) and any("cannot narrow" in c for c in ledger.clamps)
    established, _ = clamp_scenarios(raw, ("X",), has_established=True, ledger=Ledger())
    assert established[0].vol_mult == C.VOL_MULT_MIN
    many = RawSignal(tuple(RawScenario(f"s{i}", 1.0, {"X": 0.0}, 1.0, ()) for i in range(6)), 1.0, (), "")
    assert len(clamp_scenarios(many, ("X",), True, Ledger())[0]) == C.MAX_SCENARIOS


def test_rationale_numeric_paragraph_matches_what_was_applied(unit, server):
    from t2agent.text_layer.signal import NUMERIC_PARAGRAPH_MAPPED, NUMERIC_PARAGRAPH_UNMAPPED
    sig, _ = run(unit, server)
    assert NUMERIC_PARAGRAPH_UNMAPPED in sig.rationale_md and NUMERIC_PARAGRAPH_MAPPED not in sig.rationale_md
    assert "### Reader notes" in sig.rationale_md and "disagreement:" in sig.rationale_md
    mapped = apply_text_map(sig, make_summary(), 0.5)
    assert NUMERIC_PARAGRAPH_MAPPED in mapped.rationale_md and NUMERIC_PARAGRAPH_UNMAPPED not in mapped.rationale_md


def test_model_timestamps_are_not_trusted_and_retries_are_logged(unit, server):
    reply = json.loads(json.dumps(EXTRACTION))
    reply["evidence"][0]["timestamp"] = "2099-01-01"
    server.push(error(503), ok(json.dumps(reply)))
    sig, budget = run(unit, server)
    assert sig.fallback_reason is None and sig.evidence[0].timestamp == "2016-06-16"
    assert "extract_1=200x2" in sig.rationale_md and budget.used == 2 + C.SYNTHESIS_RUNS


def test_established_requires_a_verbatim_quote(tmp_path):
    from t2agent.text_layer.parse import parse_extraction, quote_found
    docs = {d.doc_id: d for d in load_corpus(make_unit(tmp_path), ASOF, [])}
    base = {"doc_id": "boe_mpc_2016-06-16", "claim": "Rate held.", "assets": ["GBP"], "direction": 0, "established": True}
    cases = {"maintain Bank Rate at 0.5%": True, "MAINTAIN   bank rate at 0.5%": True, "“maintain Bank Rate at 0.5%”": True,
             "maintain Bank Rate at 0.75%": False, "": False, "Rate": False}
    for quote, expected in cases.items():
        out, _, _, notes = parse_extraction({"evidence": [dict(base, quote=quote)]}, docs, ("GBP",))
        assert out[0].established is expected, quote
    assert quote_found("the referendum on 23 June", docs["boe_mpc_2016-06-16"].text)


def test_parallel_failure_accounting_is_exact(tmp_path, server):
    body = ("Sterling, the referendum and policy, with a dated statement from 2016-05-05 that runs long enough. ") * 900
    docs = {f"speech_{i}_2016-05-1{i}": (f"2016-05-1{i}", "cb_speech", body + f" Marker {i}.") for i in range(3)}
    unit = make_unit(tmp_path, docs)
    server.scenario = "invalid_json"                      # every extraction reply unparsable: each chunk gets one repair
    sig, budget = run(unit, server)
    assert numeric_neutral(sig) and "ParseError" in sig.fallback_reason
    at_return = len(server.requests)
    time.sleep(0.5)
    assert len(server.requests) == at_return == budget.used == sig.calls_used
    assert budget.used <= 2 * 3                           # at most one call + one repair per chunk, never a label call


def test_deadline_stops_the_pipeline_mid_way(unit, server, monkeypatch):
    monkeypatch.setattr(C, "SAFETY_MARGIN_S", 0.0)
    monkeypatch.setattr(C, "MIN_REQUEST_TIMEOUT_S", 0.1)
    server.push(delay(1.2))                               # the extraction reply arrives, but eats the budget
    sig, budget = run(unit, server, time_budget_s=1.3)
    assert numeric_neutral(sig) and "TimeExhausted" in sig.fallback_reason
    assert budget.used == 1 and len(server.requests) == 1   # no label call was started after the deadline
    time.sleep(0.3)
    assert len(server.requests) == 1



# --------------------------------------------------------------------------- #
# Post-Final hardening (2026-10-21)
# --------------------------------------------------------------------------- #

def test_model_failure_falls_back_to_card_labels_and_overlay_maps_them(unit, server):
    from t2agent.text_overlay import apply_text_map as overlay
    server.push(error(500), error(502))
    sig, budget = run(unit, server)
    assert numeric_neutral(sig) and "HTTP 502" in sig.fallback_reason and budget.used == 2
    L = sig.labels
    assert L["mode"] == "notes_only_fallback" and L["event_in_horizon"] == "scheduled_binary" and L["fallback_reason"] == sig.fallback_reason
    assert L["fallback_source"] == "card_notes_only" and L["prepass"]["n_docs"] == 0     # card prose only, like the frozen release
    card_only = read_text(unit, make_summary(), CallBudget(), env=server.env(network="none"), mode="card_notes_only")
    assert {k: L[k] for k in ("regime", "event_in_horizon", "disagreement", "assets", "branches")} == \
           {k: card_only.labels[k] for k in ("regime", "event_in_horizon", "disagreement", "assets", "branches")}
    mapped = overlay(sig, make_summary(), 0.5)
    assert len(mapped.scenarios) == 2 and all(s.vol_mult > 1.0 for s in mapped.scenarios) and mapped.tail_mult > 1.0
    assert "notes_only_fallback" in mapped.rationale_md
    offline, _ = run(unit, server, env=server.env(network="none"))
    assert offline.labels["mode"] == "neutral" and overlay(offline, make_summary(), 1.0) is offline
    nowhere = read_text(unit.parent / "missing", make_summary(), CallBudget(), env=server.env())
    assert nowhere.labels["mode"] == "neutral"
    empty = unit.parent / "empty"
    (empty / "text").mkdir(parents=True, exist_ok=True)
    assert read_text(empty, make_summary(), CallBudget(), env=server.env()).labels["mode"] == "neutral"


def test_short_unit_clock_runs_one_label_call(unit, server, monkeypatch):
    monkeypatch.setattr(C, "SAFETY_MARGIN_S", 0.0)
    monkeypatch.setattr(C, "MIN_REQUEST_TIMEOUT_S", 0.1)
    sig, budget = run(unit, server, time_budget_s=C.SYNTHESIS_TIMEOUT_S + C.SYNTHESIS_TIME_RESERVE_S - 5)
    assert sig.fallback_reason is None and sig.labels["runs"] == 1 and budget.used == 2
    assert "left on the unit clock" in sig.rationale_md


def test_second_compact_repair_recovers_a_label_run(unit, server, monkeypatch):
    monkeypatch.setattr(C, "MAX_PARALLEL_SYNTHESIS", 1)
    server.push(ok(json.dumps(EXTRACTION)), ok("prose, not JSON"), ok("still prose after the repair"))
    sig, budget = run(unit, server)
    assert sig.fallback_reason is None and sig.labels["runs"] == 3
    assert budget.used == 1 + 3 + 2                       # extraction, run 1 (call + repair + compact), runs 2 and 3
    flags = [b["chat_template_kwargs"]["enable_thinking"] for b in server.bodies()]
    assert flags[1:4] == [True, False, False] and "compact retry" in sig.rationale_md
    compact_prompt = server.bodies()[3]["messages"][1]["content"]
    assert compact_prompt.count("\n[") <= C.COMPACT_EVIDENCE_ITEMS
    server.push(ok(json.dumps(EXTRACTION)), ok("prose"), ok("prose"), ok("prose"))
    monkeypatch.setattr(C, "SYNTHESIS_RUNS", 1)
    sig2, budget2 = run(unit, server)
    assert numeric_neutral(sig2) and sig2.labels["mode"] == "notes_only_fallback" and budget2.used == 4


def test_unit_clock_is_bounded_for_the_platform_clock():
    assert C.TIME_BUDGET_S <= 240 and 104 * C.TIME_BUDGET_S <= 0.6 * 43_200
    assert C.REQUEST_TIMEOUT_S + C.SAFETY_MARGIN_S < C.TIME_BUDGET_S and C.SYNTHESIS_TIMEOUT_S < C.TIME_BUDGET_S
