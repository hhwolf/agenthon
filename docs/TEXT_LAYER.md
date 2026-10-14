# Text layer — context and contract

## Executive summary (read this first)

The text layer reads a unit's dated document corpus with the organizer's House LLM and returns a
small, clamped `TextSignal` (scenario weights, drift and volatility multipliers, cited evidence).
The numeric engine applies that signal on top of its own distribution. The text layer never
produces draws itself, never fails the unit, and returns a neutral signal whenever anything goes
wrong. Owner: teammate. Integration point (`apply_text_signal`) is owned by the numeric engine.

Contract types live in `t2agent/contracts.py`. Do not change them without telling the other owner.
The engine side is `numeric_v1.forecast(..., text_signal=...)` → `apply_text_signal`; see `docs/NUMERIC_V1.md`.

---

## 1. Setup

```bash
PYTHON_BOOTSTRAP=python3.13 make setup   # clones vendor/track2 at the pinned revision, builds .venv
make test
```

`vendor/` and `.eval/` are gitignored, and `.dockerignore` is an allowlist, so neither reaches the
image. Add `openai` to the runtime dependencies (pinned) when the client lands. Required reading in `vendor/track2`:
`README.md` (network contract, leakage rules), `docs/SOLVER-PLAYBOOK.md` §3 (turning text into
drift / width / scenarios), `docs/CATEGORIES.md` (what text does in F1–F4), `docs/NVIDIA-STACK.md`,
`docs/RATIONALE-REVIEW.md`, and `SUBMISSION_CLI.md` → "Rules for model-API use".

## 2. What a unit gives you at runtime

The harness mounts the unit directory read-only at `/input`:

```
/input/card.toml           task card; [text].notes and [metadata].description describe the setup
/input/forecast_card.md    human-readable card
/input/forecast_spec.json  targets: asset_ids, horizons, target_type, observation_periods (monthly)
/input/panels/*.parquet    numeric history, truncated at as-of
/input/text/corpus_index.json
/input/text/*.txt
```

`corpus_index.json`:

```json
{"card_id": "...", "asof": "2016-06-17",
 "documents": [{"doc_id": "bis_draghi_2016-06-02", "timestamp": "2016-06-02",
                "source": "BIS central bankers' speeches", "doc_type": "cb_speech",
                "file": "bis_draghi_2016-06-02.txt"}]}
```

- Every timestamp is ≤ as-of. Minutes/COT timestamps are **public release dates**, not meeting dates.
- `doc_type` values seen: `fomc_statement`, `fomc_minutes`, `beige_book`, `cb_speech`,
  `central_bank_decision`, `macro_release` (CPI, employment situation), `landmark`.
- **Size (practice units):** ~11 docs, **~350K characters on average (~90K tokens), max ~550K**.
  You cannot send a whole corpus in one request safely: the House serving context window is not
  published. Design for requests ≤ ~60K input tokens (chunk, prioritise, map-reduce).
- Card prose (`[text].notes`, `description`) is a legitimate input and often states the setup
  (e.g. "a scheduled binary risk event falls shortly after the as-of date").

## 3. House model contract (official scoring)

| Item | Value |
|---|---|
| Model | `nvidia/nemotron-3-super-120b-a12b`, snapshot `rl-030326-fp8`, training cutoff unpublished |
| Call | `POST $MODEL_ENDPOINT/v1/chat/completions` (endpoint is an origin; **add `/v1`**) |
| Auth | `Authorization: Bearer $MODEL_TOKEN`; `model = $MODEL_NAME` |
| Proxy | `HTTP(S)_PROXY` injected; leave untouched, never hardcode |
| Budget | **25 admitted requests per unit**, ≤ **4,000 output tokens per request**, no token allowance |
| Charging | Charged on admission. Upstream failures and SDK retries **consume slots**. 401/403 do not. `n > 1` refused |
| Thinking | On by default. Disable per request: `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` |
| Rules | No vendor tools (search/code/retrieval). Pin temperature and seed. No other model or API is reachable |
| Local / offline | `QFBENCH_NETWORK=none` or no `MODEL_ENDPOINT` → make **zero** network attempts, return neutral |

```python
client = OpenAI(base_url=os.environ["MODEL_ENDPOINT"].rstrip("/") + "/v1",
                api_key=os.environ["MODEL_TOKEN"],
                max_retries=0,        # REQUIRED: SDK default retries silently burn budget slots
                timeout=120)
```

## 4. Development model access (Development phase is closed — no House token)

Use NVIDIA's hosted API for the same model family, through the **same env vars**, so the code path
is identical:

```bash
# .env  (gitignored; never commit, never copy into the image)
MODEL_ENDPOINT=https://integrate.api.nvidia.com
MODEL_NAME=nvidia/nemotron-3-super-120b-a12b
MODEL_TOKEN=nvapi-...        # free key from build.nvidia.com
QFBENCH_NETWORK=restricted
```

OpenRouter (`nvidia/nemotron-3-super-120b-a12b`) is a fallback. Either may serve a different
snapshot than House, so treat dev results as approximate. Verify that `enable_thinking=False`
works on the dev endpoint before relying on it.

Cache every dev response on disk keyed by (unit_id, prompt hash, model, params) under
`.eval/llm_cache/` so ablations are cheap and repeatable. The cache must never enter the Docker
build context.

## 5. The contract (see `t2agent/contracts.py`)

```python
read_text(unit_dir: Path, summary: NumericSummary, budget: CallBudget) -> TextSignal
```

- `NumericSummary` is built by the numeric engine: spot, per-cell horizon sd, recent/long vol ratio,
  family, target_type, card prose.
- `TextSignal.scenarios`: 1–4 scenarios, weights sum to 1. Per-scenario `drift_sd[asset]` is in units
  of that asset's horizon sd (sign = direction of the *quoted series*; check `value_unit`, e.g. JPY
  and CHF are quoted per USD). Joint cards: each scenario moves every asset (sign-consistent legs).
- `TextSignal.neutral(assets)` is the fallback, and applying it must reproduce the numeric forecast exactly.

### Clamps (initial values — will be tuned by ablation, keep them as named constants)

| Quantity | Range |
|---|---|
| per-scenario `drift_sd` | [-1.5, 1.5] |
| weighted mean drift per asset | [-0.5, 0.5] (rescale scenario drifts if exceeded) |
| `vol_mult` | [0.8, 2.0]; **< 1.0 only if backed by `established=True` evidence** |
| `tail_mult` | [1.0, 2.0] |
| scenario weight | each ≥ 0.05 |

"Established" = the corpus states it (decision taken, print released, level announced).
"Inferred" = read from tone. Inferred evidence may move the centre, never narrow the distribution.
When documents disagree, keep the disagreement: widen or split into scenarios. Do not average tone.

## 6. Budget and runtime plan

- Unit wall clock is 1,800 s **including image pull and the numeric engine**. Text layer: ≤ 600 s total.
- Typical: prioritise docs (decisions/statements > minutes > speeches; recent first), 2–6 extraction
  calls with thinking off, 1 synthesis call with thinking on. **Hard cap 20 admitted requests**, leaving 5 spare.
- Count a request as spent when it is sent, not when it succeeds.
- Strict JSON output; validate; one repair attempt max (counts against budget); then neutral.

## 7. Leakage and memorization

- Use only documents in `/input/text` and the card. Never fetch anything.
- The model knows history. Prompts must state the as-of date, forbid post-as-of knowledge, and require
  `doc_id` citations for every claim. Claims without a citation are dropped.
- Practice cards (2007–2024) are events the model may remember, so text gains measured on them are
  optimistic. The sealed set is H2 2025 – Q2 2026.

## 8. Rationale

`TextSignal.rationale_md` is appended to `forecast_rationale.md`: each adjustment, its size, the
`doc_id`s behind it, and established vs inferred, ending with an adjustment ledger. It is never
scored, but it is screened by humans at the top of the board.

## 9. Evaluation

- Unit tests: clamping, neutral fallback, budget counting (including failures), offline mode, JSON repair.
- Mock server (`tests/mock_house.py`): OpenAI-compatible, canned responses, can simulate 401/403/5xx/timeout.
- Offline full sweep: `make admissibility FORECASTER=<text-aware forecaster>` with `QFBENCH_NETWORK=none` → 104/104 pass.
- Ablation (with the dev model): `make eval-practice` numeric-only vs numeric+text on the 88 practice
  proxies, reported by family. Text ships only if it helps there and does not increase capped cards.
  The historical backtest (`make backtest`) has no text, so it cannot measure this.
