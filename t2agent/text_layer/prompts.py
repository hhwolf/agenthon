"""Prompt builders: extraction (thinking off) and label synthesis (thinking on).

Every prompt states the as-of date, forbids post-as-of knowledge, and requires ``doc_id`` citations
(docs/TEXT_LAYER.md §7). The model classifies; it never picks numbers (Phase 3 design B2/B3).
"""

from __future__ import annotations

import json
from typing import Sequence

from ..contracts import NumericSummary
from . import constants as C
from .corpus import Chunk, render_chunk

SYSTEM_EXTRACT = (
    "You are the document-reading stage of a quantitative forecasting system. You read dated "
    "official documents (central-bank statements, minutes, speeches, statistical releases) and "
    "extract cited, dated evidence. You have no tools and no web access. You answer with one "
    "strict JSON object and nothing else: no markdown fences, no commentary."
)

SYSTEM_LABELS = (
    "You are the synthesis stage of a quantitative forecasting system. You read cited evidence and "
    "classify the situation with a small set of categorical labels; a separate numeric engine turns "
    "labels into magnitudes, so you never output numbers for drift or volatility. You have no tools "
    "and no web access. Reason carefully, then answer with one strict JSON object and nothing else."
)

FAMILY_GUIDANCE = {
    "T2-F1": "F1 continuation-with-context: the numbers carry most of the signal; text adds incremental "
             "context. Call a direction only when a document states something the panel cannot already show.",
    "T2-F2": "F2 text-cued regime shift: the shift may live in the text before the panel moves. Look for the "
             "specific policy-path phrasing that precedes moves (tone shifts, changed forward guidance, dissent), "
             "not just summaries; when the direction is clear, say so rather than staying symmetric.",
    "T2-F3": "F3 cross-asset reasoning: one story must move all assets with sign-consistent legs (a hawkish "
             "decision lifts short yields and moves the currency per its quote convention). Give every asset a label.",
    "T2-F4": "F4 tail/shock-from-text: documents may foreshadow a shock. Prefer regime=crisis/elevated and an "
             "event label over a confident direction; the numeric side fattens the tail toward the side you name.",
}


def _as_of(summary: NumericSummary) -> str:
    return summary.asof.isoformat()


def _assets_line(summary: NumericSummary) -> str:
    units = summary.value_unit or "see card"
    return (f"assets: {', '.join(summary.assets)}; value_unit: {units}; "
            f"horizons (business days unless the card says months): {', '.join(str(h) for h in summary.horizons)}; "
            f"target_type: {summary.target_type}")


def _direction_note() -> str:
    return ("Direction always refers to the QUOTED series exactly as value_unit defines it: up = the quoted number "
            "rises, down = it falls. Example: for 'jpy_per_usd' a stronger yen means a LOWER number (down); for "
            "'usd_per_eur' a stronger euro means a HIGHER number (up); for yields in percent a hike means up; for a "
            "cumulative log return, positive performance means up.")


def unit_block(summary: NumericSummary) -> str:
    desc = (summary.card_description or "").strip() or "(none)"
    notes = (summary.card_text_notes or "").strip() or "(none)"
    return (f"AS-OF DATE: {_as_of(summary)}. You know nothing after this date. Do not use any knowledge "
            f"of what happened after {_as_of(summary)}; use only the documents and the card below.\n\n"
            f"FORECASTING UNIT\n- unit_id: {summary.unit_id}; family: {summary.family}\n- {_assets_line(summary)}\n"
            f"- card description: {desc}\n- card notes: {notes}\n- {_direction_note()}\n")


def numeric_context(summary: NumericSummary) -> str:
    vols = ", ".join(f"{a}: {summary.vol_ratio.get(a, 1.0):.2f}" for a in summary.assets)
    return ("NUMERIC CONTEXT (for regime judgement only; you do not output numbers): recent/long-run realised "
            f"volatility ratio per asset: {vols}. A ratio well above 1 means the panel is already in a volatile "
            "state; a ratio near or below 1 with crisis language in the documents is the classic early-warning setup.\n")


_EXTRACTION_SCHEMA = """{
  "evidence": [
    {"doc_id": "<exact id from a DOC header>", "timestamp": "<that document's timestamp>",
     "claim": "<one factual sentence>", "quote": "<verbatim excerpt, 10-200 characters, copied exactly>",
     "assets": ["<asset id>"], "direction": -1 | 0 | 1, "established": true | false,
     "kind": "decision" | "data" | "guidance" | "tone" | "event" | "other"}
  ],
  "scheduled_events": [{"date": "YYYY-MM-DD or null", "event": "<what>", "doc_id": "<id>"}],
  "disagreements": ["<one sentence naming the documents on each side>"]
}"""


def extraction_messages(summary: NumericSummary, chunk: Chunk, part: int, total: int,
                        max_items: int = C.MAX_EVIDENCE_PER_CHUNK) -> list[dict]:
    user = (
        unit_block(summary)
        + f"\nDOCUMENTS (part {part} of {total}; each begins with <<<DOC id=... timestamp=... type=...>>> "
          "and ends with <<<END DOC>>>). Some documents may be off-topic for these assets; extract nothing from "
          "those rather than forcing relevance.\n\n" + render_chunk(chunk) + "\n\n"
        f"TASK\nExtract up to {max_items} evidence items that bear on where the assets above will be over the "
        "stated horizons: decisions taken, data released, explicit guidance or forward-looking statements, changes "
        "in tone or wording versus earlier communication, scheduled events that fall inside the horizon, and "
        "disagreements between documents. Most recent and most authoritative statements first. Return exactly "
        "this JSON shape:\n" + _EXTRACTION_SCHEMA + "\n\n"
        "RULES\n"
        "1. doc_id must be copied exactly from a DOC header. Claims you cannot tie to a document are not allowed.\n"
        "2. quote must be a verbatim excerpt from that document (10-200 characters). Do not paraphrase inside quote.\n"
        "3. established=true ONLY for things the document states as done or released: a decision taken, a print "
        "released, a level announced, a date set. Interpretations of tone, expectations, and your own inferences "
        "are established=false.\n"
        "4. direction is the sign on the quoted series per the convention above; use 0 when unclear.\n"
        "5. assets lists the asset ids affected (may be empty for general macro context).\n"
        "6. Only the as-of frame: never cite outcomes or events after the as-of date.\n"
        "7. Output ONLY the JSON object."
    )
    return [{"role": "system", "content": SYSTEM_EXTRACT}, {"role": "user", "content": user}]


def _labels_schema(assets: Sequence[str]) -> str:
    asset_obj = ", ".join(f'"{a}": {{"direction": "strong_down" | "down" | "none" | "up" | "strong_up", '
                          f'"direction_established": true | false, "evidence": [<evidence numbers>]}}' for a in assets)
    return ("{\n"
            '  "regime": "calm" | "elevated" | "crisis",\n'
            '  "event_in_horizon": "none" | "scheduled_binary" | "ongoing",\n'
            f'  "assets": {{{asset_obj}}},\n'
            '  "disagreement": true | false,\n'
            '  "branches": [\n'
            '    {"label": "<outcome>", "prob": <0-1>, "signs": {' + ", ".join(f'"{a}": -1 | 0 | 1' for a in assets) + "}}\n"
            "  ],\n"
            '  "summary": "<at most three sentences>"\n'
            "}\n"
            "(branches: exactly two objects when event_in_horizon is scheduled_binary, otherwise an empty list)")


def format_evidence(items: Sequence, order: Sequence[int] | None = None) -> str:
    idx = list(order) if order is not None else list(range(len(items)))
    lines = []
    for i in idx:
        e = items[i]
        flag = "E" if e.established else "I"
        assets = ",".join(e.assets) if e.assets else "-"
        lines.append(f"[{i + 1}] ({flag}) {e.doc_id} {e.timestamp} | {e.kind} | assets={assets} dir={e.direction:+d} | {e.claim}")
    return "\n".join(lines) if lines else "(no evidence extracted)"


def labels_messages(summary: NumericSummary, evidence: Sequence, events: Sequence[str], disagreements: Sequence[str],
                    prepass_lines: Sequence[str], run_index: int = 0, order: Sequence[int] | None = None) -> list[dict]:
    guidance = FAMILY_GUIDANCE.get(summary.family, "")
    events_block = "\n".join(f"- {e}" for e in events) if events else "- (none reported by the reader)"
    dis_block = "\n".join(f"- {d}" for d in disagreements) if disagreements else "- (none reported by the reader)"
    pre_block = "\n".join(f"- {l}" for l in prepass_lines) if prepass_lines else "- (none)"
    user = (
        f"TASK: LABELS (run {run_index + 1})\n\n" + unit_block(summary) + "\n" + numeric_context(summary) + "\n"
        f"FAMILY GUIDANCE: {guidance}\n\n"
        "FACTS FROM THE CARD AND CORPUS INDEX (deterministic pre-pass; dates are as stated in the sources):\n" + pre_block + "\n\n"
        "EVIDENCE extracted from the unit's documents (E = established: the document states it as done/released; "
        "I = inferred: read from tone or expectation). Numbers are stable identifiers; the order is arbitrary:\n"
        + format_evidence(evidence, order) + "\n\n"
        "SCHEDULED EVENTS reported by the reader:\n" + events_block + "\n\n"
        "DISAGREEMENTS reported by the reader:\n" + dis_block + "\n\n"
        "TASK\nClassify the situation for the forecast horizon. Return exactly this JSON shape:\n" + _labels_schema(summary.assets) + "\n\n"
        "DEFINITIONS\n"
        "- regime: calm = nothing in the documents argues for unusual uncertainty; elevated = a binary decision, policy "
        "transition, or visible stress inside the horizon; crisis = documents describe acute market/financial stress, "
        "emergency measures or a shock in progress.\n"
        "- event_in_horizon: scheduled_binary = a dated two-outcome event (referendum, election, vote, a decision the "
        "documents frame as hike-or-hold) falls inside the horizon; ongoing = an unfolding regime shift or crisis without "
        "a single date; none otherwise.\n"
        "- direction per asset: the sign of the move the documents argue for over the horizon on the quoted series; "
        "strong_* only when several authoritative, recent documents agree. none when the documents are silent or balanced.\n"
        "- direction_established: true only when the directional call rests on ESTABLISHED items (a decision taken, a "
        "print released), not on tone.\n"
        "- disagreement: true when authoritative documents point in opposite directions for an asset, or the card prose "
        "and the latest decision conflict. Do not average them away.\n"
        "- branches: for scheduled_binary give exactly two outcomes with probabilities summing to 1 and the sign of each "
        "asset's move under each outcome (signs consistent across assets within a branch).\n"
        "RULES\n"
        "1. Every non-none direction must cite evidence numbers; a direction without citations is dropped.\n"
        "2. Use only the evidence and facts above; no outside knowledge of what happened after the as-of date.\n"
        "3. When documents disagree, set disagreement=true (and widen via regime) rather than picking a side.\n"
        "4. Default when evidence is thin: regime calm, event none, every direction none, disagreement false.\n"
        "5. Output ONLY the JSON object."
    )
    return [{"role": "system", "content": SYSTEM_LABELS}, {"role": "user", "content": user}]


def repair_messages(messages: list[dict], bad_output: str, error: str) -> list[dict]:
    return list(messages) + [
        {"role": "assistant", "content": (bad_output or "(empty)")[:3000]},
        {"role": "user", "content": (
            f"Your previous reply was not a valid JSON object of the required shape ({error[:160]}). "
            "Reply again with ONLY the JSON object described above: same keys, no markdown fences, "
            "no commentary, no text before or after it. Keep it compact.")},
    ]


def messages_tokens(messages: list[dict]) -> int:
    return sum(len(m.get("content") or "") for m in messages) // C.CHARS_PER_TOKEN


def canonical(messages: list[dict]) -> str:
    return json.dumps(messages, sort_keys=True, ensure_ascii=False)
