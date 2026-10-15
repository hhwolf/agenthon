# Phase 4 text integration

The default candidate is numeric_v1.1 plus **card-notes-only, lambda 0.5**.
This is provisional: the 88-card dev-label cache is absent, so neither LLM-label
arm has been scored. See [results](../reports/phase4/RESULTS.md) and the
[precommitted protocol](../reports/phase4/VALIDATION.md). No new image is published
by this integration experiment.

On the 88 development proxies, card notes lower the mean from 2.415744 to
2.378141; caps remain 9, with no new or removed capped cards. The paired as-of-year
block bootstrap 95% interval for the mean delta is [-0.068127, -0.013183]. F1
worsens slightly (0.841566 to 0.842977); F2, F3 and F4 improve. These are practice
proxies, and the inherited B4 v2 rules already saw practice results in Phase 3.
This does not establish sealed-Final performance.

## Runtime and overrides

Both numeric engines keep the six positional forecast arguments. They sample
first, call `read_text` if enabled, map categorical labels, then apply the text
signal to completed draws. `numeric_v1_1` remains the default engine. The numeric
configuration files and Phase 2 selection are unchanged; `text_config.json`
contains the separate provisional text choice.

```sh
# Default candidate: card prose only, zero model calls, including restricted mode.
forecast --panels /input/panels --text /input/text --asof YYYY-MM-DD --out /output/forecast.parquet

# Reproduce a numeric baseline explicitly.
forecast --panels /input/panels --asof YYYY-MM-DD --out /output/forecast.parquet --text-mode numeric_only

# Explicit House-label experiment; the normal House/proxy environment is required.
forecast --panels /input/panels --text /input/text --asof YYYY-MM-DD --out /output/forecast.parquet --text-mode labels --text-lambda 0.5
```

`text_mode` and `text_lambda` are optional forecast keywords. CLI flags override
`TEXT_LAYER_MODE` / `TEXT_LAYER_LAMBDA`, which override the committed selection.
`text_dir=None`, `numeric_only`, and lambda zero make no model calls. Zero lambda
and neutral signals preserve numeric sample bytes. Text errors preserve completed
numeric draws; numeric errors still fall back to M0 and a wide random walk.
Rationales may differ to explain neutrality or failure.

`card_notes_only` reads only `[metadata].description` and `[text].notes`, retaining
the inherited numeric volatility-ratio guard. It neither loads corpus documents
nor calls House. Legacy `notes_only` also reads corpus pre-pass features; it is
available explicitly but was not the Phase 4 B4 comparison. `text_v1` is an
explicit labels wrapper over numeric_v1.1, with env-free ablation variants.
The existing runtime dependency is pinned at `openai==3.31.0`.

## Fixed mapping and joint behavior

`t2agent/text_map.py` contains constants only; `text_overlay.py` implements the
mapping. The playbook motivates these rules; the user's specification supplies
the numerical coefficients. No coefficient was fitted in Phase 4.

| label | full-strength adjustment before lambda |
|---|---|
| elevated | volatility 1.25 |
| crisis | volatility 1.6, outer-tail scale 1.5 |
| up / down | drift +0.25 / -0.25 horizon SD |
| strong up / down | drift +0.5 / -0.5 horizon SD |
| scheduled binary | two branches, signed +/-1 SD; normalized probabilities clipped to [0.2,0.8] |
| disagreement | zero drift in every branch, no directional tail, volatility at least 1.15 |

The inherited event width floor 1.15 and binary tail scale 1.25 are retained.
Lambda scales drift and excess volatility/tail scale above one. Generic mean
drift is capped at 0.5 SD; fixed binary shifts keep their specified magnitudes,
with an implied mean bound of 1 SD. Opposite +/-1 branches imply a 0.6-SD maximum
mean; rise-versus-hold (+1/0) can imply 0.8 SD at 80/20. One branch is sampled for the entire draw,
including every asset and horizon. Asset signs come from the validated text;
the card-only pre-pass cannot invent them, so its event branches have zero drift.

For crisis or F4 with a named adverse direction, a single joint extreme-draw
indicator identifies the outer 5%. Named asset residuals expand only on that
side. Other assets use symmetric expansion. Disagreement removes named sides.
The ordinary scenario shift is not added again to binary branch shifts.

`TextSignal` adds optional `tail_signs` and `branch_mixture` fields with neutral
defaults. Existing supplied `text_signal` hooks remain already-mapped numerical
signals. Every parsed signal appends a text evidence ledger to
`forecast_rationale.md`, with document IDs, timestamps and the full words
`established` / `inferred`. Card cues carry no invented document citations.
Volatility below one remains forbidden without established evidence.

## Reproduce the comparison

Restore `.eval` using [EVALUATION_DATA.md](../reports/EVALUATION_DATA.md), then:

```sh
.venv/bin/python -m t2eval.phase4
# Once teammate sweep artifacts are available:
.venv/bin/python -m t2eval.phase4 --labels-dir /path/to/text_signals
```

The label directory must contain the Phase 3 sweep's per-unit JSON artifacts,
including `mode=dev|replay`, model, unit ID, as-of, assets and a successful `llm`
signal. Canned/mock records, failed labels, mismatched cards and future evidence
are rejected. Both lambda arms consume the same frozen labels and the same
numeric samples. Missing labels remain unavailable; they are never replaced by
neutral signals and reported as measured text performance. No live requests
are sent by this comparison script. Raw dev-response caches can first be replayed
with `scripts/run_text_layer_practice.py --mode replay --cache-dir PATH` using
the original dev model name. Do not change prompt inputs to force cache matches.

The script writes means, caps, family breakdowns, per-card deltas, cap changes,
input/source hashes, label-artifact hashes and the balanced decision under
`reports/phase4/`. It does not automatically publish or change the runtime choice.
The current cached label format is flat; the mock Final replay server supports
both it and the previous per-unit cache format.

The remaining step is to supply all 88 validated cached labels, rerun the fixed
comparison, and record the final decision in BUILD_LOG and text_config.json.
