# F4 tail experiment — pre-registration (committed before any candidate is scored)

Date: 2026-10-21. Time box: go/no-go by **2026-10-23 12:00 EDT**. If a GO cannot be fully released and verified by
then, it is abandoned. Default outcome: **NO-GO, keep the current final**
`ghcr.io/hhwolf/agenthon-numeric-v1@sha256:400fe71078d8f9e3e7859da3402ec7866a531760c14b1c0bc795e8e71db0d674`.

## Corrections to the brief (facts checked before writing this plan)

1. **numeric_v1.1 does not use Gaussian tails.** `t2agent/numeric_v1_1_config.json` has `"tails": "fhs5"`:
   filtered historical simulation. Lagged-EWMA-standardized residuals are resampled in 5-step blocks, and their
   covariance is normalized to the model covariance. The shocks therefore carry the empirical tail shape of each
   card's history. (Only if fewer than 20 residual rows exist does it fall back to a unit-variance t5.) Each
   candidate below therefore *replaces* FHS with a parametric variance-normalized scale mixture on F4 cards.
   It does not replace a Gaussian.
2. **There are 28 F4 practice proxies, not 31.** Of the 31 `t2-F4-*` units, three have no resolvable sibling
   outcome: `aud-gfc-2008`, `chf-defended-floor-2015` and `funding-stress-10y-2008`. They are excluded from
   every practice score, as in all earlier phases.
3. **Prior evidence, disclosed.** Phase 2.5 evaluated a *global* unit-variance t5 (`student_unit`) and a global
   5%×3 mixture; FHS beat both on the CV rule. Phase 2 found a global (non-normalized) t5 worse. This plan was
   written **without looking at the F4-specific rows of those earlier runs**. The hypothesis itself is motivated
   by the 9 practice caps, all F4 and already seen in the audit. Practice is therefore an in-sample proxy, and any
   practice gain is optimistic for the sealed set.

## A-priori expectation (falsifiable)

Unit-variance quantiles (computed before scoring):

| law | q95 | q99 | q99.9 |
|---|---:|---:|---:|
| Gaussian | 1.645 | 2.326 | 3.090 |
| (a) t5 × √(3/5) | 1.561 | 2.606 | 4.565 |
| (b) t4 × √(1/2) | 1.507 | 2.649 | 5.072 |
| (c) 10% × 2.5 mixture / √1.525 | 1.519 | 2.651 | 4.710 |

Holding variance fixed, these laws widen the 1%/99% quantiles by about 0.3 SD but *narrow* 5%/95% and sharpen
the centre. The capped F4 cards miss by many SD (unclipped scores 8.3–248), so tail-pinball gains are small
relative to their error, and CRPS can worsen slightly. **Prediction: no candidate improves the practice mean by
≥ 0.02; NO-GO is the most likely outcome.**

## Candidates (applied only when `card.toml [metadata].category == "T2-F4"`)

Every other card calls the unchanged `numeric_v1_1.forecast`. Same engine, drift, covariance, monthly
handling, card-notes text at λ = 0.5, seeds (per-card CRC32) and 2,000 draws as the current final. Only the
shock law changes: a Gaussian factor draw multiplied by a per-draw scale common to all assets in the draw
(the existing `tail_scale` mechanism, per covariance segment).

| id | scale per draw | variance |
|---|---|---|
| a `t5` | √(3 / χ²₅) (= t5 × √(3/5)) | 1 |
| b `t4` | √(2 / χ²₄) (= t4 × √(1/2)) | 1 |
| c `mix10` | 2.5 with probability 0.10, else 1; divided by √1.525 | 1 |

The experiment runs through an evaluation-only wrapper (`t2eval/f4_tails.py`). No runtime file changes unless
the result is GO.

## Data and baselines (fixed)

- Historical: the same 2,060 synthetic cards (dataset seed 20261014, union `eaa07cbd…`). **Primary: T2-F4
  template cards with as-of 2009–2018 (328 cards).** Report-only: T2-F4 2019–2024 (167 cards); it never ranks,
  gates or vetoes. Historical cards carry no text, so the baseline is numeric_v1.1 (CV F4 mean 0.961435, 1 cap).
- Practice: the 88 resolvable proxies with card-notes text. Baseline is the current final: mean **2.378141**,
  **9** caps; F4 (28 cards) 4.459123, 9 caps.
- Official scorer, existing M0 normalization; failures count as 8.

## Acceptance (all must hold for a candidate; otherwise it fails)

1. Practice overall mean ≤ 2.378141 − 0.02 = **2.358141**.
2. Practice caps (score ≥ 8) ≤ **9**.
3. CV F4 mean ≤ 1.01 × 0.961435 = **0.971049**.
4. No family or panel group is more than 10% worse than the current final, checked in CV (groups with
   ≥ 40 cards; macro_monthly ≥ 20, as in Phase 2.5) and in practice (family/panel groups with ≥ 10 cards).
5. Non-F4 byte-identical: every non-F4 practice output triplet (parquet, meta, rationale) equals the current
   final's, and every non-F4 historical card score equals numeric_v1.1's exactly.

**Selection:** among candidates passing 1–5, choose the lowest practice overall mean. Within 0.0005, prefer
the lower CV F4 mean, then the order a, b, c. If none passes: **NO-GO**. No candidate, parameter or rule is
added or changed after scores are seen. Paired year-block bootstrap CIs (10,000, seed 20261015) are
descriptive only.

## If GO (all by 2026-10-23 12:00 EDT, else abandon)

Implement behind config (F4-only tail setting) with tests: unit variance of each scale law, non-F4
byte-identical, determinism. Then PR to main, Greptile 5/5, a `final-YYYYMMDD-N` CI tag and the full release
check: 104/104, cold anonymous pull, eight mock-Final sweeps, 0 House requests, fresh seed, digest equality,
and `submission.final.json` updated and validated without packing. The current final becomes fallback #1.
Nothing is packed or uploaded; House stays disabled; PR #8 is untouched.
