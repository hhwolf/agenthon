"""Named limits for the text layer. Values come from docs/TEXT_LAYER.md §3, §5, §6 and the Phase 3 brief.

Everything the ablation may tune lives here; nothing else in the package hardcodes a bound.
"""

from __future__ import annotations

from ..contracts import MAX_ADMITTED_REQUESTS

# --- §5 clamps (applied by signal.clamp_scenarios, used by text_map in Phase 4) -----------------
DRIFT_SCENARIO_LIMIT = 1.5     # per-scenario drift_sd, in horizon-sd units
DRIFT_MEAN_LIMIT = 0.5         # weighted mean drift per asset; scenario drifts are rescaled if exceeded
VOL_MULT_MIN = 0.8             # allowed only when backed by established evidence
VOL_MULT_MAX = 2.0
VOL_MULT_INFERRED_FLOOR = 1.0  # inferred evidence may move the centre, never narrow
TAIL_MULT_MIN = 1.0
TAIL_MULT_MAX = 2.0
SCENARIO_WEIGHT_MIN = 0.05
MAX_SCENARIOS = 4
MAX_EVIDENCE = 40              # items carried into synthesis and the signal
MAX_EVIDENCE_PER_CHUNK = 18                 # fewer, shorter items keep replies under the output cap

# --- §3 / §6 budget and runtime ------------------------------------------------------------------
HARD_REQUEST_CAP = MAX_ADMITTED_REQUESTS   # 20 admitted requests; House allows 25
MAX_EXTRACTION_CALLS = 6                    # "2–6 extraction calls with thinking off"
SYNTHESIS_RUNS = 3                          # self-consistency: majority vote over 3 label runs
SYNTHESIS_SEED_STEP = 1                     # run k uses SEED + k (pinned, reproducible, diverse)
REPAIR_ATTEMPTS = 1                         # one JSON repair per call, then that call fails
MAX_RETRIES_PER_CALL = 1                    # transient failures only; every retry spends a slot
SYNTHESIS_RESERVE = 2                       # slots kept for at least one synthesis call and its repair
TIME_BUDGET_S = 400.0                       # hard stop per unit (Final runs units sequentially)
SOFT_TARGET_S = 240.0                       # average target per unit including image pull; logged when exceeded
SAFETY_MARGIN_S = 20.0
REQUEST_TIMEOUT_S = 120.0                   # per the contract snippet
SYNTHESIS_TIMEOUT_S = 150.0                 # thinking on; bounded by the remaining time budget
SYNTHESIS_TIME_RESERVE_S = 30.0             # below SYNTHESIS_TIMEOUT_S + this, run one label call instead of three
MIN_REQUEST_TIMEOUT_S = 15.0
MAX_OUTPUT_TOKENS = 4000                    # House caps every request at 4,000 output tokens
EXTRACTION_MAX_OUTPUT_TOKENS = 4000         # 3,000 truncated replies on the dev endpoint
SYNTHESIS_MAX_OUTPUT_TOKENS = 4000
TEMPERATURE = 0.0
TOP_P = 1.0
SEED = 20261014
MAX_PARALLEL_EXTRACTION = 3
MAX_PARALLEL_SYNTHESIS = 3

# --- §2 sizing -------------------------------------------------------------------------------------
CHARS_PER_TOKEN = 2.8                       # measured on the dev endpoint (2.6–3.5 chars/token on these corpora)
MAX_INPUT_TOKENS_PER_CALL = 48_000          # "design for requests <= ~60K input tokens"
PROMPT_OVERHEAD_TOKENS = 3_000              # instructions + card + numeric block
MAX_SEGMENT_TOKENS = 20_000                 # long documents are split at paragraph boundaries
MIN_SEGMENT_TOKENS = 200
MAX_QUOTE_CHARS = 200
MIN_QUOTE_CHARS = 10
MAX_CLAIM_CHARS = 280

# --- document priority: lower sorts first. Decisions/statements > releases > minutes > speeches ---
DOC_TYPE_PRIORITY = {
    "central_bank_decision": 0,
    "fomc_statement": 0,
    "macro_release": 1,
    "fomc_minutes": 2,
    "positioning_report": 2,
    "corporate_8k": 2,
    "beige_book": 3,
    "cb_speech": 3,
    "landmark": 4,
}
DEFAULT_DOC_TYPE_PRIORITY = 3
PRIORITY_DAYS_PER_LEVEL = 60                # one priority level is worth 60 days of recency
KEYWORD_BONUS_DAYS = 30                     # each card-keyword hit (max 3) is worth 30 days
RELEVANCE_BONUS_DAYS = 90                   # a top BM25 relevance score is worth 90 days
OFF_TOPIC_PENALTY_DAYS = 240                # no asset/bank term at all: rank after everything on topic
BM25_K1 = 1.5
BM25_B = 0.75

# --- labels (Phase 3 design: the model classifies, a fixed table sets magnitudes) -----------------
REGIMES = ("calm", "elevated", "crisis")
EVENTS = ("none", "scheduled_binary", "ongoing")
DIRECTIONS = ("strong_down", "down", "none", "up", "strong_up")
LABELS_SCHEMA_VERSION = "text_labels_v1"
MAJORITY_MIN_RUNS = 2                       # a label needs at least this many agreeing runs; ties -> neutral

# --- pre-pass (deterministic, no LLM) -------------------------------------------------------------
HORIZON_CALENDAR_FACTOR = 1.45              # business days -> calendar days, with slack
HORIZON_SLACK_DAYS = 5
MIN_HORIZON_DAYS = 35                       # a 21-step card still spans the next data print
OFF_TOPIC_MIN_PRIORITY = 3                  # only speeches/beige books/landmarks can be ranked off-topic
PREPASS_CRISIS_CUES_FOR_ELEVATED = 1        # distinct crisis words in card prose + latest decisions
PREPASS_VOL_RATIO_ALREADY_WIDE = 1.5         # numeric_v1 already prices a volatile panel: no second widening
# v1 rules (crisis tier at >= 3 cues, elevated from vol_ratio >= 1.5) measured worse; see BUILD_LOG Phase 3.

# --- environment ----------------------------------------------------------------------------------
ENV_ENDPOINT = "MODEL_ENDPOINT"
ENV_TOKEN = "MODEL_TOKEN"
ENV_MODEL = "MODEL_NAME"
ENV_NETWORK = "QFBENCH_NETWORK"
ENV_CACHE_DIR = "TEXT_LAYER_CACHE_DIR"      # dev only; unset in the image
ENV_REPLAY_ONLY = "TEXT_LAYER_REPLAY_ONLY"  # 1 -> cache misses fail instead of calling the network
ENV_TIME_BUDGET = "TEXT_LAYER_TIME_BUDGET_S"
ENV_MODE = "TEXT_LAYER_MODE"                # labels (default) | notes_only
ENV_SYNTHESIS_RUNS = "TEXT_LAYER_SYNTHESIS_RUNS"
MODE_LABELS = "labels"
MODE_NOTES_ONLY = "notes_only"
MODE_NOTES_ONLY_FALLBACK = "notes_only_fallback"  # labels mode failed; pre-pass labels used instead
