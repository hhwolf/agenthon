"""Named limits for the text layer. Values come from docs/TEXT_LAYER.md §3, §5 and §6.

Everything the ablation may tune lives here; nothing else in the package hardcodes a bound.
"""

from __future__ import annotations

from ..contracts import MAX_ADMITTED_REQUESTS

# --- §5 clamps -------------------------------------------------------------
DRIFT_SCENARIO_LIMIT = 1.5     # per-scenario drift_sd, in horizon-sd units
DRIFT_MEAN_LIMIT = 0.5         # weighted mean drift per asset; scenario drifts are rescaled if exceeded
VOL_MULT_MIN = 0.8             # allowed only when backed by established evidence
VOL_MULT_MAX = 2.0
VOL_MULT_INFERRED_FLOOR = 1.0  # inferred evidence may move the centre, never narrow
TAIL_MULT_MIN = 1.0
TAIL_MULT_MAX = 2.0
SCENARIO_WEIGHT_MIN = 0.05
MAX_SCENARIOS = 4
MAX_EVIDENCE = 40              # items carried into the synthesis call and the signal
MAX_EVIDENCE_PER_CHUNK = 25

# --- §3 / §6 budget and runtime --------------------------------------------
HARD_REQUEST_CAP = MAX_ADMITTED_REQUESTS   # 20 admitted requests; House allows 25
MAX_EXTRACTION_CALLS = 6                    # "2–6 extraction calls with thinking off"
REPAIR_ATTEMPTS = 1                         # one JSON repair per call, then neutral
MAX_RETRIES_PER_CALL = 1                    # transient failures only; every retry spends a slot
SYNTHESIS_RESERVE = 2                       # keep slots for the synthesis call and its repair
TIME_BUDGET_S = 600.0
SAFETY_MARGIN_S = 30.0
REQUEST_TIMEOUT_S = 120.0                   # per the contract snippet
SYNTHESIS_TIMEOUT_S = 240.0                 # thinking on; bounded by the remaining time budget
MIN_REQUEST_TIMEOUT_S = 15.0
MAX_OUTPUT_TOKENS = 4000                    # House caps every request at 4,000 output tokens
EXTRACTION_MAX_OUTPUT_TOKENS = 3000
TEMPERATURE = 0.0
TOP_P = 1.0
SEED = 20261014
MAX_PARALLEL_EXTRACTION = 3

# --- §2 sizing ---------------------------------------------------------------
CHARS_PER_TOKEN = 4                         # conservative estimate for English prose
MAX_INPUT_TOKENS_PER_CALL = 48_000          # "design for requests <= ~60K input tokens"
PROMPT_OVERHEAD_TOKENS = 3_000              # instructions + card + numeric block
MAX_SEGMENT_TOKENS = 20_000                 # long documents are split at paragraph boundaries
MIN_SEGMENT_TOKENS = 200
MAX_QUOTE_CHARS = 300
MIN_QUOTE_CHARS = 10
MAX_CLAIM_CHARS = 280

# Document priority: lower sorts first. Decisions/statements > releases > minutes > speeches.
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

# --- environment -------------------------------------------------------------
ENV_ENDPOINT = "MODEL_ENDPOINT"
ENV_TOKEN = "MODEL_TOKEN"
ENV_MODEL = "MODEL_NAME"
ENV_NETWORK = "QFBENCH_NETWORK"
ENV_CACHE_DIR = "TEXT_LAYER_CACHE_DIR"      # dev only; unset in the image
ENV_TIME_BUDGET = "TEXT_LAYER_TIME_BUDGET_S"
