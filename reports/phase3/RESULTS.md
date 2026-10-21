# Agenthon Track 2 — Phase 3/4 text layer results

Aiden Xia, 2026-10-21. Companion to BUILD_LOG "Text layer — Phase 3" and "Phase 4 — integration and ship decision".

## Summary

The text layer reads a unit's dated corpus with the House model family (Nemotron 3 Super 120B-A12B on the NVIDIA dev
endpoint) and returns categorical labels; a fixed table turns labels into scenario drifts, a volatility multiplier and a
tail multiplier, shrunk toward neutral by λ and clamped. The model never chooses numbers.

On the 88 practice proxies, paired against numeric_v1.1 (mean 2.4157, 9 capped cards):

| arm | mean | Δ | 95 % CI | caps |
|---|---:|---:|---|---:|
| card/corpus notes only (no model), λ = 0.5 | 2.3955 | −0.020 | [−0.053, +0.008] | 9 |
| LLM labels, λ = 0.5 | 2.2958 | −0.120 | [−0.205, −0.040] | 6 |
| LLM labels, λ = 1.0 | 2.2104 | −0.205 | [−0.349, −0.071] | 6 |

Under the team's balanced rule the LLM labels at λ = 0.5 pass (mean improves with the CI clear of zero, caps fall, F1/F2 move
by less than 1 %), λ ≥ 0.75 fails family consistency, and two pre-declared table variants were rejected.

## Decision context

The frozen Final image (`final-20261020-1`) ships numeric_v1.1 with card-notes labels at λ = 0.5 and House calls disabled.
Its Phase 4 report lists the LLM-label arms as *unavailable: missing validated cache*: the dev cache that holds the model
replies lived only on the author's machine and was not transferred before the release audit. The LLM arm was therefore never
weighed, not rejected. The card-notes image scores 2.378 on the same proxies (−0.038 vs numeric_v1.1, caps unchanged).
Reproducing the LLM figures needs only the replay bundle (`.eval/share/text_layer_dev_bundle_2026-10-19.tgz`, 1.3 MB) and
`scripts/compare_runs.py`; no network calls.


# Design

## Pipeline per unit (≤ 20 requests, 240 s hard stop after the post-Final hardening)

1. **Deterministic pre-pass** (no model): calendar window of the horizons; dated events from card prose and documents with
   regex kinds (referendum / election / vote-on / policy meeting / deadline / release / summit; day ranges; year-less dates
   resolved against the document's own date); latest decision or statement per bank; document recency; whole-word hawkish /
   dovish / crisis / binary cue counts; `card_binary_kind` when the card names a two-outcome event.
2. **Relevance**: BM25 over asset/bank terms plus card keywords; speeches, beige books and landmarks that mention neither are
   ranked last. Decisions, statements, releases and minutes are never penalised.
3. **Extraction** (thinking off, ≤ 6 parallel requests of ≤ 48K estimated tokens at 2.8 characters per token): cited
   evidence items {doc_id, claim, quote, assets, direction, established}. Uncited claims are dropped; `established` survives
   only with a verbatim quote found in the document.
4. **Labels** (thinking on, 3 runs with seeds SEED+k and the evidence order permuted): regime, event in horizon, per-asset
   direction with `direction_established`, disagreement, two branches for a scheduled binary event. Majority vote per field
   (≥ 2 of 3; ties → neutral value); branches aligned across runs by total sign agreement.
5. **Table** (`t2agent/text_map.py`, applied by `t2agent/text_overlay.py`): elevated → vol 1.25; crisis → vol 1.6, tail
   1.5; scheduled binary → two branches with ±1.0 sd drift by sign and probabilities clipped to [0.2, 0.8], tail 1.25;
   direction ±0.25 sd (strong ±0.5); disagreement → no drift and vol ≥ 1.15; λ shrinks drift, vol−1 and tail−1; then the
   §5 clamps (per-scenario |drift| ≤ 1.5, weighted mean |drift| ≤ 0.5, vol in [0.8, 2.0] with narrowing only on established
   evidence, tail in [1, 2], weights ≥ 0.05).

## Guarantees

`budget.spend()` precedes every request including retries and repairs; offline (`QFBENCH_NETWORK=none` or no
`MODEL_ENDPOINT`) makes zero network attempts; any failure yields a signal that leaves the numeric draws unchanged (neutral,
or, after the hardening, the deterministic card/corpus labels); applying a neutral signal reproduces numeric_v1.1 bit for bit.
The adversarial review of the Phase 3 code (five lenses, two to three refuters per finding) raised 40 findings, 29 upheld,
all fixed with regression tests.


# Development sweep with the real model

`scripts/run_text_layer_practice.py --mode dev` over the 104 practice units, `nvidia/nemotron-3-super-120b-a12b` on
integrate.api.nvidia.com, two passes (a network outage turned 63 units neutral in the first pass; the gap-fill pass re-ran
only those).

| quantity | value |
|---|---:|
| units labelled | 100 / 104 (4 neutral: no JSON after the single repair) |
| requests per unit | mean 4.4, max 11 of the 20 cap |
| wall time per live unit | mean ≈ 125 s, max 293 s (4 units over the 240 s target) |
| self-consistency agreement (3 runs) | mean 0.85; 29 units below 0.8 |
| replies cached for replay | 449 |

Label mix on the 100 labelled units: regime elevated 83, crisis 8, calm 9; event scheduled_binary 44, ongoing 13, none 43;
disagreement flagged on 63; per-asset directions none 105, up 25, strong_up 8, down 20, strong_down 7, of which 48
established. The model is conservative on direction and liberal on disagreement, so most of the measured gain comes from
width and tails rather than from moving the centre.

`chat_template_kwargs.enable_thinking=false` is honoured: extraction replies carry no reasoning and their completion tokens
match the visible text; label calls think server-side (1,000–2,700 completion tokens for about 700 characters of JSON).
The tokenizer counts 2.6–3.5 characters per token on these corpora; sizing constants were corrected before the sweep.


# Ablations

All arms are paired on the same 88-card roster with 2,000 draws and the pinned official scorer; the LLM arms replay the
cached replies with zero network calls. Bootstrap CIs are over cards.

## Against numeric_v1 (2.4356, 9 caps), 2026-10-15

| arm | mean | Δ | 95 % CI | caps | F1 Δ | F2 Δ | F3 Δ | F4 Δ |
|---|---:|---:|---|---:|---:|---:|---:|---:|
| notes-only v2, λ = 0.5 | 2.4122 | −0.023 | [−0.051, +0.001] | 9 | +0.013 | −0.058 | +0.007 | −0.039 |
| notes-only v2, λ = 1.0 | 2.3768 | −0.059 | [−0.108, −0.015] | 8 | +0.022 | −0.105 | +0.009 | −0.120 |
| LLM labels, λ = 0.5 | 2.2905 | −0.145 | [−0.238, −0.060] | 7 | +0.008 | −0.025 | −0.023 | −0.426 |
| LLM labels, λ = 1.0 | 2.2067 | −0.229 | [−0.378, −0.090] | 6 | +0.038 | −0.023 | −0.022 | −0.712 |

## Against numeric_v1.1 (2.4157, 9 caps), 2026-10-19

| arm | mean | Δ | 95 % CI | caps | F1 Δ | F2 Δ | F3 Δ | F4 Δ |
|---|---:|---:|---|---:|---:|---:|---:|---:|
| notes-only, λ = 0.5 | 2.3955 | −0.020 | [−0.053, +0.008] | 9 | | | | |
| LLM labels, λ = 0.5 | 2.2958 | −0.120 | [−0.205, −0.040] | 6 | +0.008 | +0.008 | −0.025 | −0.373 |
| LLM labels, λ = 0.75 | 2.2403 | −0.176 | [−0.294, −0.064] | 6 | +0.014 | +0.011 | −0.028 | −0.552 |
| LLM labels, λ = 1.0 | 2.2104 | −0.205 | [−0.349, −0.071] | 6 | +0.028 | +0.016 | −0.020 | −0.665 |
| variant: disagreement keeps half the drift, λ = 0.5 | 2.2925 | −0.123 | [−0.209, −0.042] | 6 | +0.008 | −0.004 | −0.022 | −0.376 |
| variant: binary branch drift 0.75, λ = 0.5 | 2.3067 | −0.109 | [−0.187, −0.037] | 6 | +0.005 | +0.004 | −0.024 | −0.334 |

The notes-only rules were revised once after seeing the practice breakdown (v1 → v2: no lexicon crisis tier, no vol-ratio
trigger, no second widening when the panel is already volatile), so the notes-only figures are optimistic; the LLM arms were
not tuned on the practice set. The table variants were declared before scoring with the rule "keep the table unless a
variant improves the mean, caps do not rise and no family is more than 10 % worse"; neither qualified.


# Hardening, risks and reproduction

## Post-Final hardening (branch `aiden/post-final-hardening`, not in the frozen image)

- Model-path failures on a unit with a loaded corpus now return the deterministic card/corpus labels
  (`labels.mode = notes_only_fallback`), which the overlay maps; offline, missing or empty corpora stay neutral.
- Unit clock bounded at 240 s (request timeout 90 s, label calls 120 s, one label call instead of three when fewer than
  140 s remain): 104 stalled units would take 6.9 h of the 12 h platform clock, 150 would take 10 h.
- A second, compact (20-item, thinking-off) repair recovers label calls whose first repair still returns no JSON, within the
  20-request cap (worst case 10 requests for the label stage).

## Risks that keep the LLM arm from being a free win

- The House route's availability and latency at evaluation time were never observed; the frozen card-notes image carries
  none of that risk.
- Practice episodes are historical and may be remembered by the model; the sealed window is 2025–26.
- 29 % of units have vote agreement below 0.8, so individual cards can move on a rerun; the LLM seed is a constant independent
  of `QFBENCH_SEED`, so the organisers' fresh-seed rerun changes the numeric draws, not the labels.
- The dev endpoint may serve a different snapshot than the House route.

## Reproduction

Replay bundle `.eval/share/text_layer_dev_bundle_2026-10-19.tgz` (llm_cache, text_signals, ablations). With it unpacked under
`.eval/`: `TEXT_LAYER_CACHE_DIR=.eval/llm_cache TEXT_LAYER_REPLAY_ONLY=1 make eval-practice
FORECASTER=t2agent.text_v1:forecast_labels_l05`, likewise `_l10`, then `scripts/compare_runs.py numeric_v1_1 ...`. The mock
House (`tests/mock_house.py --replay-dir .eval/llm_cache`) serves the same replies to an image under `make mock-final`.
Labels and rationales per unit are in `text_signals/<unit>.json|.md`.
