"""Prompt builders for the extraction (thinking off) and synthesis (thinking on) calls.

Every prompt states the as-of date, forbids post-as-of knowledge, and requires ``doc_id``
citations (docs/TEXT_LAYER.md §7). Outputs are strict JSON objects.
"""

from __future__ import annotations

import json

from ..contracts import NumericSummary
from . import constants as C
from .corpus import Chunk, render_chunk

SYSTEM_EXTRACT = (
    "You are the document-reading stage of a quantitative forecasting system. You read dated "
    "official documents (central-bank statements, minutes, speeches, statistical releases) and "
    "extract cited, dated evidence. You have no tools and no web access. You answer with one "
    "strict JSON object and nothing else: no markdown fences, no commentary."
)

SYSTEM_SYNTH = (
    "You are the synthesis stage of a quantitative forecasting system. You turn cited evidence "
    "into a small, conservative, well-calibrated adjustment to a numeric baseline distribution. "
    "You have no tools and no web access. Reason carefully, then answer with one strict JSON "
    "object and nothing else: no markdown fences, no commentary."
)

FAMILY_GUIDANCE = {
    "T2-F1": "F1 continuation-with-context: the numbers carry most of the signal; text adds "
             "incremental context. Keep drift modest and vol near 1 unless a document states a change.",
    "T2-F2": "F2 text-cued regime shift: a regime change may live in the text before the panel moves. "
             "A documented policy pivot or binary decision inside the horizon justifies scenarios with "
             "larger separation and a wider mixture; tone alone does not.",
    "T2-F3": "F3 cross-asset reasoning: every scenario must move all assets with sign-consistent legs "
             "(e.g. a hawkish decision moves short rates up and the currency per the quote convention).",
    "T2-F4": "F4 tail/shock-from-text: documents may foreshadow a shock. Use tail_mult and a low-weight "
             "shock scenario rather than shifting the centre far; keep the body of the distribution honest.",
}


def _as_of(summary: NumericSummary) -> str:
    return summary.asof.isoformat()


def _assets_line(summary: NumericSummary) -> str:
    units = summary.value_unit or "see card"
    return (f"assets: {', '.join(summary.assets)}; value_unit: {units}; "
            f"horizons (business days unless the card says months): {', '.join(str(h) for h in summary.horizons)}; "
            f"target_type: {summary.target_type}")


def _direction_note(summary: NumericSummary) -> str:
    return ("Direction and drift sign always refer to the QUOTED series exactly as value_unit defines it: "
            "+1 / positive = the quoted number goes up, -1 / negative = it goes down. Example: for "
            "'jpy_per_usd' a stronger yen means a LOWER number (direction -1); for 'usd_per_eur' a stronger "
            "euro means a HIGHER number (+1); for yields in percent, a hike means +1; for a cumulative "
            "log return, positive performance means +1.")


def unit_block(summary: NumericSummary) -> str:
    desc = (summary.card_description or "").strip() or "(none)"
    notes = (summary.card_text_notes or "").strip() or "(none)"
    return (f"AS-OF DATE: {_as_of(summary)}. You know nothing after this date. Do not use any knowledge "
            f"of what happened after {_as_of(summary)}; use only the documents and the card below.\n\n"
            f"FORECASTING UNIT\n- unit_id: {summary.unit_id}; family: {summary.family}\n- {_assets_line(summary)}\n"
            f"- card description: {desc}\n- card notes: {notes}\n- {_direction_note(summary)}\n")


def numeric_block(summary: NumericSummary) -> str:
    rows = []
    for a in summary.assets:
        spot = summary.spot.get(a, 0.0)
        for h in summary.horizons:
            sd = summary.horizon_sd.get((a, h))
            if sd is None:
                continue
            pct = f"{100.0 * sd / abs(spot):.2f}% of spot" if spot else "n/a"
            rows.append(f"- {a} @ horizon {h}: spot {spot:.6g}, horizon_sd {sd:.6g} ({pct})")
    vols = ", ".join(f"{a}: {summary.vol_ratio.get(a, 1.0):.2f}" for a in summary.assets)
    return ("NUMERIC BASELINE (from the numeric engine; drift_sd and vol_mult are applied on top of it):\n"
            + "\n".join(rows) + f"\n- recent/long-run volatility ratio per asset: {vols}\n"
            "- horizon_sd is one standard deviation of the baseline's horizon-end distribution in value units; "
            "a drift_sd of +0.3 moves the centre up by 0.3 horizon_sd.\n")


_EXTRACTION_SCHEMA = """{
  "evidence": [
    {"doc_id": "<exact id from a DOC header>", "timestamp": "<that document's timestamp>",
     "claim": "<one factual sentence>", "quote": "<verbatim excerpt, 10-300 characters, copied exactly>",
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
          "and ends with <<<END DOC>>>):\n\n" + render_chunk(chunk) + "\n\n"
        f"TASK\nExtract up to {max_items} evidence items that bear on where the assets above will be over the "
        "stated horizons: decisions taken, data released, explicit guidance or forward-looking statements, "
        "scheduled events that fall inside the horizon, and disagreements between documents. Most recent and "
        "most authoritative statements first. Return exactly this JSON shape:\n" + _EXTRACTION_SCHEMA + "\n\n"
        "RULES\n"
        "1. doc_id must be copied exactly from a DOC header. Claims you cannot tie to a document are not allowed.\n"
        "2. quote must be a verbatim excerpt from that document (10-300 characters). Do not paraphrase inside quote.\n"
        "3. established=true ONLY for things the document states as done or released: a decision taken, a print "
        "released, a level announced, a date set. Interpretations of tone, expectations, and your own inferences "
        "are established=false.\n"
        "4. direction is the sign on the quoted series per the convention above; use 0 when unclear.\n"
        "5. assets lists the asset ids affected (may be empty for general macro context).\n"
        "6. Only the as-of frame: never cite outcomes or events after the as-of date.\n"
        "7. Output ONLY the JSON object."
    )
    return [{"role": "system", "content": SYSTEM_EXTRACT}, {"role": "user", "content": user}]


_SYNTHESIS_SCHEMA = """{
  "scenarios": [
    {"label": "<short name>", "weight": <0.05-1>, "drift_sd": {"<asset id>": <number>}, "vol_mult": <0.8-2.0>,
     "evidence": [<evidence numbers that support this scenario>]}
  ],
  "tail_mult": <1.0-2.0>,
  "narrowing_support": [<numbers of ESTABLISHED evidence items that justify any vol_mult below 1.0, else []>],
  "summary": "<at most three sentences: what the text changes relative to the numeric baseline and why>"
}"""


def format_evidence(items, start: int = 1) -> str:
    lines = []
    for i, e in enumerate(items, start):
        flag = "E" if e.established else "I"
        assets = ",".join(e.assets) if e.assets else "-"
        lines.append(f"[{i}] ({flag}) {e.doc_id} {e.timestamp} | {e.kind} | assets={assets} dir={e.direction:+d} | {e.claim}")
    return "\n".join(lines) if lines else "(no evidence extracted)"


def synthesis_messages(summary: NumericSummary, evidence, events: list[str], disagreements: list[str]) -> list[dict]:
    guidance = FAMILY_GUIDANCE.get(summary.family, "")
    ev_block = format_evidence(evidence)
    events_block = "\n".join(f"- {e}" for e in events) if events else "- (none reported)"
    dis_block = "\n".join(f"- {d}" for d in disagreements) if disagreements else "- (none reported)"
    user = (
        unit_block(summary) + "\n" + numeric_block(summary) + "\n"
        f"FAMILY GUIDANCE: {guidance}\n\n"
        "EVIDENCE extracted from the unit's documents (E = established: the document states it as done/released; "
        "I = inferred: read from tone or expectation):\n" + ev_block + "\n\n"
        "SCHEDULED EVENTS mentioned in the documents:\n" + events_block + "\n\n"
        "DISAGREEMENTS between documents:\n" + dis_block + "\n\n"
        "TASK\nDecide how the text should adjust the numeric baseline and return exactly this JSON shape:\n"
        + _SYNTHESIS_SCHEMA + "\n\n"
        "RULES\n"
        f"1. 1 to {C.MAX_SCENARIOS} mutually exclusive scenarios; weights sum to 1 and each is at least "
        f"{C.SCENARIO_WEIGHT_MIN}. Give every asset a drift_sd in every scenario (0 if unaffected).\n"
        f"2. drift_sd is in units of each asset's horizon_sd. Per scenario |drift_sd| <= {C.DRIFT_SCENARIO_LIMIT}; "
        f"the weighted mean across scenarios must satisfy |mean| <= {C.DRIFT_MEAN_LIMIT} for each asset. "
        "Most good forecasts move the centre by a fraction of one sd, not multiples.\n"
        f"3. vol_mult in [{C.VOL_MULT_MIN}, {C.VOL_MULT_MAX}] scales the spread of that scenario. Use > 1 when a "
        "binary decision, crisis or shock sits inside the horizon. Use < 1 ONLY when ESTABLISHED evidence shows "
        "uncertainty has already resolved, and list those items in narrowing_support. Inferred evidence may move "
        "the centre but must never narrow the distribution.\n"
        f"4. tail_mult in [{C.TAIL_MULT_MIN}, {C.TAIL_MULT_MAX}] fattens the outer 5% of draws; raise it for "
        "discrete events (votes, decisions, pegs) inside the horizon.\n"
        "5. When documents disagree, keep the disagreement: split into scenarios or widen; do not average tone.\n"
        "6. Signs follow the quote convention stated above. For joint units every scenario moves all assets "
        "with sign-consistent legs.\n"
        "7. Cite evidence numbers for every scenario; a scenario without cited evidence is not allowed except "
        "a single neutral baseline scenario.\n"
        "8. Conservative default when evidence is thin: one scenario, drift 0, vol_mult 1, tail_mult 1.\n"
        "9. Output ONLY the JSON object."
    )
    return [{"role": "system", "content": SYSTEM_SYNTH}, {"role": "user", "content": user}]


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
