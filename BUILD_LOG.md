# Phase 0–1 measurement loop

The complete generated evaluation snapshot is published with release v0.1.0.0.
See [evaluation data](reports/EVALUATION_DATA.md) for download and restoration
instructions. All 55,005 archived files were verified against a per-file SHA-256
manifest; preliminary runs remain distinguishable from the final run IDs below.

## Scope and reference

2026-10-14. Implement measurement and literal M0 only; no forecaster optimization.
Read README, M0-BASELINE, CONCEPTS, SOLVER-PLAYBOOK, CATEGORIES,
MONTHLY-HORIZONS, and SUBMISSION_CLI before implementation.

- Read-only upstream checkout: `vendor/track2`, commit
  `b9c663d239a0e6b86ebd3f3f2d5aead88516067d` (track package 3.1.0).
- Toolkit: requested **v2.6.0**, peeled commit `bd01548e34d21fd660d88fd06157078fb25ece4e`
  (annotated tag object `683e70c9c44eca947699a72bea79147a5d4d8c7a`).
  Upstream now recommends v2.6.1 and its Dockerfile installs it. Local evaluation
  stays at 2.6.0; the exact reference image and a staged 2.6.0 variant are checked separately.
- Python 3.13.7 venv created with `/opt/miniconda3/bin/python -m venv .venv`.
  Installed toolkit via its tagged Git URL and `pip install ./vendor/track2`.
  Numeric packages match the reference Dockerfile: NumPy 2.1.3, pandas 2.2.3,
  PyArrow 18.1.0, jsonschema 4.23.0.
- Docker was absent. Installed Homebrew docker, docker-buildx, colima, ripgrep.
  Started profile `agenthon`: VZ/Rosetta, 4 CPUs, 8 GiB RAM, 30 GiB disk.
  Docker client plugin configuration stays under `.context/docker-config`.

## Decisions and ambiguities

1. **M0 near 1 is a model check, not a historical identity.** §5 normalizes by
   model-expected error, not observed error. Historical pseudo-cards must retain
   their actual score even if it differs from 1. An independent Gaussian-outcome
   calibration mode checks the normalization with the official scorer.
2. **M0 returns vs reference CLI:** §3.2 explicitly uses panel rows as M0 return
   steps. Current vendor `targets.log_return_steps` instead converts simple
   returns with `log1p`. Implement literal M0 documentation; local realized
   cumulative log returns use `sum(log1p(r))`. Do not silently change M0 to match
   the reference CLI; these are distinct forecasters.
3. **Monthly metadata drift:** §3.7 says Sahm lacks named months and lists steps
   8,9. The current spec *does* name January/February 2025. Use current explicit
   periods and actual last observation; report the discrepancy rather than
   hardcode per-unit overrides in inference.
4. **Practice dates:** most target dates are sealed. When absent, the local
   practice proxy uses `asof + pandas.offsets.BDay(horizon)` and labels it inferred.
   Exact sibling row lookup never rolls or interpolates a missing target date.
   Explicit observation months use an exact unique row in that month. The
   README's 75 exact recoveries were measured with sealed dates/values; public
   proxies cannot certify the same count or equality to sealed outcomes.
5. **Union conflicts:** an initial scan found 1,045 conflicting macro monthly
   keys (revisions) and 496 rates keys (the illustrative exemplar). Exclude the
   exemplar from the 103-practice-unit union. Retain vintage/source provenance;
   choose the most recent source cutoff for the historical union. This is a
   revised-data historical benchmark, not a certified point-in-time vintage test.
6. **Undefined M0 cases:** reject missing/nonfinite/duplicate dates, fewer than
   two aligned steps, inconsistent monthly mappings, or return tripwire >=0.2.
   No invented variance floor beyond §3.8's two diagonal additions. Date parsing
   and steps follow the specified fallback for absent/malformed target dates.
7. **Seed:** default M0 is CRC32(unit_id), 500 draws; explicit `seed`, then
   `QFBENCH_SEED`, overrides it. Reference defaults to 0 and the wrapper passes
   QFBENCH_SEED explicitly (upstream itself ignores that environment variable).
8. **Weights:** use exact 5/7 and 2/7 for one cell, as the official scorer does;
   0.714/0.286 in prose are rounded. Failed cards remain in means at 8.0.
9. **Expected-error numerics:** Kummer's exact moment formula is used for the
   joint divisor. At |delta|/s >100, integrate a centred, rationalized square
   root to avoid catastrophic subtraction. Integrating over ±12 normal SDs
   omits <4e-33 probability mass. Tests independently integrate four cases.

## Initial checks

- Reference CLI exemplar: **g0–g3 all pass**, toolkit 2.6.0.
- M0 exemplar: seed **795546941**, 128 aligned steps, steps **21,21,21,21**;
  SDs **0.08722815, 0.09236816, 0.09053985, 0.10281506**, matching §4.
- macOS Accelerate/NumPy emitted spurious matmul FP warnings in the vendor CLI;
  the resulting samples are finite and the official gates pass. No warnings
  are interpreted as evidence of valid output; gates inspect the actual arrays.
  A final independent comparison on all 104 M0 matrices against non-BLAS
  `einsum(..., optimize=False)` also passes: maximum absolute difference
  **3.55e-15**, with every product finite.

## Results

All runs below use 500 forecast draws and unset QFBENCH_SEED: M0 defaults to
CRC32(unit_id), reference defaults to 0. Dataset seed is 20261014. Source hash for
the final scored runs is
`fd14e2b62f53ae6c56dd168b522f4294820e53ac46b0a99b8f775f18e82fb13e`.

| Evaluation | Forecaster | Cards | Mean normalized score | Failures | Clipped |
|---|---|---:|---:|---:|---:|
| Historical synthetic cards | M0 | 2,060 | **1.214629** | 0 | 24 |
| Historical synthetic cards | Reference CLI | 2,060 | **1.394364** | 0 | 22 |
| Sibling-panel practice proxies | M0 | 88 | **2.551735** | 0 | 11 |
| Sibling-panel practice proxies | Reference CLI | 88 | **2.557722** | 0 | 10 |
| Independent M0-distributed outcomes, one per card | M0 | 2,060 | **0.951098** | 0 | 0 |
| Independent outcomes, 20 additional replicas per card | Fixed M0 forecasts | 41,200 | **1.002631** | — | — |

Lower is better. Practice comparisons use the identical roster. These are local
measurements and are not organizer leaderboard scores. The 20-replica diagnostic
uses the official `_composite` function directly after the full CLI evaluation;
it does not repeat filesystem gates 41,200 times. Standard error across its 20
replicate means is **0.003014**. The single-outcome run has SE **0.012463** and is
retained as measured, not replaced by the repeated-outcome aggregate.

Final local report directories under `.eval/runs/`:

- `backtest-m0-a9a5d3fc5371`
- `backtest-reference-b9b6b2abcee7`
- `eval-practice-m0-b158bfdafa1a`
- `eval-practice-reference-a6c1e8229f8f`
- `calibration-m0-73e8c89855fa`
- `admissibility-m0-c6db96a41818`
- `admissibility-reference-a5cbe1c333d8`

Each contains `summary.json`, `cards.csv`, and a roster. Scored runs also preserve
the official per-card JSON verdict and all three forecast output files. The M0
historical run contains `calibration-diagnostic.json` with every replica mean.
The aggregate breakdowns are also recorded in [BASELINES.md](BASELINES.md).

### Dataset audit and label limits

- 103 practice sources; **3,437,361 donor rows**, **146,692 union rows**.
  Input SHA-256:
  `eaa07cbd29fac4905197fe45ea930c1c9b0f861d415ccd3a92b28ce9f045cf3a`.
- Exactly **20 pseudo-cards per template**. Families: F1 460, F2 540, F3 440,
  F4 620. Target types: level 1,740; log_return 320. Monthly 80; daily 1,980.
- As-of dates span **2005-01-03 to 2024-09-25**, with every year 2005–2024
  represented. Latest cutoffs depend on the availability of future outcomes.
- **100 cards** use documented EM→G10 asset substitutions: the five transfer
  templates have no continuous labelled EM futures in the requested date range.
  Asset count, family, target type and horizon shape are retained; actual EM
  forecasting performance is not measured by those substitute cards.
- The practice roster has **3 explicit-month** labels and **85 inferred-BDay**
  labels; 15 units have no complete sibling outcome. Missing exact holiday rows
  and targets beyond sibling history remain unresolved, without interpolation.
  `make eval-practice FORECASTER=m0 ARGS=--strict-dates` scores only 3 cards,
  mean **5.803162**, and lists all 100 unresolved units. Explicit months still
  do not certify the sealed target's vintage. The README's 75 exact sealed
  matches cannot be reproduced without the sealed dates/vintage convention.
- The union retains **1,045 conflicting macro keys**. No rates conflicts remain
  after excluding the exemplar. Latest-vintage selection is deterministic and
  provenance is kept; this limitation must stay visible in future comparisons.

### Verification and commands

```sh
make test
make reference-smoke
make docker-smoke
make backtest FORECASTER=m0
make backtest FORECASTER=reference
make eval-practice FORECASTER=m0
make eval-practice FORECASTER=reference
make eval-practice FORECASTER=m0 ARGS=--strict-dates
make admissibility FORECASTER=m0
make admissibility FORECASTER=reference
make calibration FORECASTER=m0
.venv/bin/python scripts/calibration_diagnostic.py \
  .eval/runs/backtest-m0-a9a5d3fc5371 --replicates 20
.venv/bin/python -m pip check
```

- **25 tests passed**, including the worked example, four monthly practice
  cards, transfer holes, date intersection, return tripwire, covariance across
  horizons, independent moment integration, byte-identical seeded triplets,
  sibling-only lookup, strict-date refusal and failure-at-8 handling.
- **104/104 M0 outputs pass g0–g3**; maximum measured forecast time **0.060 s**.
- **104/104 reference outputs pass g0–g3**; maximum forecast time **0.057 s**.
  These are local host inference times, not official pull/startup measurements.
- An external `python vendor/track2/scoring/scoring.py score ... --realized ...`
  invocation matches the in-process adapter's complete result exactly.
- `pip check`: **No broken requirements found.** Dependency versions are in
  `constraints-eval.txt`; setup uses the pinned track revision and toolkit tag.
- The vendor checkout is unchanged (`git -C vendor/track2 status --short` empty).

All three images were built with `docker buildx build --platform linux/amd64
--load`, inspected as linux/amd64, and run with `--network=none`, 4 CPUs, 4 GiB
RAM, and the complete exemplar mounted at `/input:ro`. All four gates pass:

| Image | Toolkit in image | Image ID |
|---|---|---|
| `t2-upstream:local` | v2.6.1 (untouched upstream Dockerfile) | `sha256:77ab0c3b9fc29986f8c82ed212fc7263222581165a0cbe958fe77a315884e71e` |
| `t2-pinned:local` | v2.6.0 (only staged Dockerfile tag changed) | `sha256:7feaf7476efc04d267a8a12b03d4f876ee207ecbd651d6fbfedbdf24346cc606` |
| `t2-m0:local` | Not needed for inference; host scorer v2.6.0 | `sha256:12521266138a38b06e5187b4b9aa74954e667668dc444bfcf6f72f81e8d6bf22` |

Logs and JSON evidence are in `.context/docker-*.log` and
`.context/docker-results.json`. A separate offline inspection of the M0 image
confirms no `t2eval` module, vendor tree, or parquet data. `.dockerignore` is an
allowlist; realized values never enter the runtime context or image. Colima's
`agenthon` profile remains running for subsequent work; `colima stop agenthon`
stops it when no longer needed.

### Investigation: why a historical M0 score is not exactly one

Used the investigate workflow. Symptom: historical mean 1.214629 rather than
the requested approximate 1.0. Hypothesis: the normalization is model-expected
error; historical drift/volatility and revised macro outcomes differ from that
model. No inference adjustment was made to force the measurement toward one.

Evidence: published exemplar divisors match; independent quadrature verifies
the joint formula; the single-outcome Gaussian check scores 0.951098. Its random
innovations have variance 0.957585 across 5,260 dimensions, below the theoretical
one. To distinguish sampling variation from a systematic normalization error,
20 further predeclared independent outcome streams score **1.002631 ± 0.003014
(SE)** and have innovation variance **0.999579**. This supports the hypothesis.
Historical scores remain unchanged and are reported separately. No scoring math
was reimplemented, and no forecast was tuned. Status: **DONE_WITH_CONCERNS**;
the historical-data, practice-date and M0-document ambiguities above remain.

## Pre-push validation — 2026-10-14

The release check passed **41 tests**, including 16 additional boundary and
recovery cases in `tests/test_ship_review.py`. `pip check` again reported no
broken requirements. This supplements the original 25-test measurement snapshot
above and in the dated PDF; the historical scores were not rerun or replaced.

`make docker-smoke` rebuilt all three images for linux/amd64 and passed g0–g3
on the exemplar with `--network=none`. The rebuilt image IDs are:

| Image | Pre-push image ID |
|---|---|
| `t2-upstream:local` | `sha256:8782f4eb41da40524072b1599471e3df1adc153db00a944a206da797b72ce3dc` |
| `t2-pinned:local` | `sha256:c0ff5ad0e4f0dc308b68ad20cabc216655c079538b95cc00b5c55c6c2f620311` |
| `t2-m0:local` | `sha256:368990f40002b1f5bbb3175b08b3ef62e6a47eeb1a33bc5f8d617abc1c4f41e9` |

The latest local evidence is `.context/ship-docker-smoke.log` and
`.context/docker-results.json`; the earlier image IDs above remain the record
of the initial measurement run.

## Phase 2 — Step 1 diagnosis (before tuning), 2026-10-14

Frozen baseline: 2,060 historical pseudo-cards, 5,260 marginal cells, 500 draws,
mean normalized score **1.214629**, 24 cards capped at 8. No numeric model
changes or candidate selection preceded this report. Reproduce with
`.venv/bin/python -m t2eval.diagnostics`.

### Calibration and center

Nominal 90% / 98% Gaussian intervals cover **85.13% / 94.09%** of outcomes.
The standardized residual mean is **+0.0193**, median **+0.0030**, and RMS
**1.3825**. The near-zero signed average hides large, opposing regime errors;
it does not show that individual centers are accurate. M0 is underdispersed
in aggregate, especially long rates and monthly macro, but is not uniformly
too narrow. Short rates have 98.33% coverage at the nominal 98% level.

PIT histograms (ten equal bins; dashed uniform reference) are in
[the figure](reports/phase2/m0-pit-histograms.png). The CSV includes every
bin count and both analytic and empirical sample coverage. Buckets use each
card's maximum declared horizon, matching the baseline report; monthly
horizon labels are NOT model steps. Monthly steps still use observation periods.
Coverage pools cells; cards with more cells receive more weight here. Scores
below average cards equally. Overlapping dates and cells are dependent.

| Panel | Horizon bucket | Cards / cells | 90% coverage | 98% coverage | Mean z | RMS z |
|---|---|---:|---:|---:|---:|---:|
| factors_daily | 127+ | 40 / 40 | 92.50% | 95.00% | +0.039 | 1.024 |
| factors_daily | 1–21 | 200 / 260 | 88.46% | 95.77% | -0.006 | 1.181 |
| factors_daily | 22–63 | 60 / 220 | 85.91% | 92.73% | -0.098 | 1.345 |
| factors_daily | 64–126 | 20 / 80 | 77.50% | 91.25% | -0.087 | 1.483 |
| g10_fx_daily | 127+ | 120 / 220 | 83.18% | 93.64% | +0.050 | 1.256 |
| g10_fx_daily | 1–21 | 160 / 160 | 88.12% | 95.00% | +0.089 | 1.182 |
| g10_fx_daily | 22–63 | 200 / 1100 | 89.09% | 95.64% | +0.008 | 1.190 |
| g10_fx_daily | 64–126 | 220 / 280 | 87.50% | 95.00% | +0.053 | 1.150 |
| g10_fx_daily+rates_daily | 22–63 | 80 / 520 | 87.31% | 96.15% | -0.127 | 1.167 |
| g10_fx_daily+rates_daily | 64–126 | 20 / 120 | 78.33% | 90.00% | -0.041 | 1.383 |
| macro_monthly | 127+ | 40 / 80 | 73.75% | 85.00% | -0.029 | 2.377 |
| macro_monthly | 1–21 | 40 / 40 | 87.50% | 92.50% | +0.341 | 1.171 |
| rates_daily | 127+ | 260 / 520 | 73.65% | 88.46% | +0.212 | 2.298 |
| rates_daily | 1–21 | 120 / 120 | 88.33% | 98.33% | -0.027 | 1.007 |
| rates_daily | 22–63 | 240 / 540 | 86.30% | 94.81% | +0.029 | 1.178 |
| rates_daily | 64–126 | 240 / 960 | 84.79% | 94.38% | +0.018 | 1.256 |

### Center versus width loss decomposition

These are **hindsight diagnostics, not deployable forecasts or validation
results**. All scores call the pinned official composite function with the
existing M0 normalizers; reconstructed baseline scores match all 2,060 stored
scores within 1e-9. Hold the actual sample residuals fixed and change the center
or width. The center oracle moves the mean exactly to the realized vector;
the width oracle chooses 0.5, 1, 2, or 4 per card using its outcome.

| Counterfactual | Mean score |
|---|---:|
| Frozen M0 | 1.214629 |
| Zero drift, same width | 1.182455 |
| Twice the width, same center | 1.501331 |
| Hindsight center oracle, original width | 0.520204 |
| Hindsight width oracle, original center | 0.973210 |
| Both hindsight oracles | 0.247128 |

A two-factor Shapley allocation of the reduction from M0 to both oracles is
**0.710254 center** and **0.257248 width**, with **0.247128 residual score**.
That residual is an artifact of the chosen oracle widths, not irreducible
uncertainty. Center errors dominate this diagnostic. Simply doubling all
widths worsens the score substantially. Zeroing drift helps overall, especially
long FX and rates, but hurts monthly macro (long: 2.1226 → 2.4120; short:
1.2523 → 1.6708). This supports testing drift shrinkage, volatility regimes and
selective tail mass separately, with dedicated monthly trend treatment.
Complete panel × horizon counterfactuals are in `m0-loss-groups.csv`.

### All 24 capped cards

For joint cards, the z-score below is the largest absolute marginal z; the
full asset/horizon grid and unrounded values are in `m0-capped-cards.csv`.
These are numeric, provisional classifications, not verified historical causal
attributions. Monthly/vintage means a monthly-card failure with known revised
union data; it does **not** establish that revisions caused the error. No bug
was established. Future volatility and direction are used only for this
postmortem, never as inference features.

Classification rule, applied in order: monthly card → monthly/vintage issue;
removing drift cuts |z| by >50% → drift extrapolation; realized step volatility
≥2× pre-cutoff volatility and absolute mean-step t-statistic <2 → vol spike;
otherwise regime break. Totals: **15 regime breaks, 5 monthly/vintage issues,
3 vol spikes, 1 drift extrapolation, 0 demonstrated bugs**.

| Card suffix | Panel | Assets | As-of | Horizons | Worst asset / horizon | M0 z | Classification |
|---|---|---|---|---|---|---:|---|
| 00039 | rates_daily | UST_2Y | 2021-09-27 | 126,189 | UST_2Y / 189 | +13.392 | regime break |
| 00200 | rates_daily | UST_2Y | 2021-10-01 | 129 | UST_2Y / 129 | +11.504 | regime break |
| 00310 | rates_daily | UST_2Y,UST_10Y | 2007-06-05 | 126,189 | UST_2Y / 189 | -5.121 | regime break |
| 00397 | rates_daily | UST_2Y | 2021-09-09 | 126 | UST_2Y / 126 | +7.452 | regime break |
| 00410 | rates_daily | UST_2Y | 2021-09-17 | 129 | UST_2Y / 129 | +9.887 | regime break |
| 00521 | factors_daily | MKT,QMJ | 2020-02-17 | 21 | MKT / 21 | -8.423 | vol spike |
| 00795 | macro_monthly | CPI_ALL | 2008-08-19 | 140,160 | CPI_ALL / 160 | -5.512 | monthly/vintage issue |
| 00883 | rates_daily | UST_2Y | 2021-10-14 | 126 | UST_2Y / 126 | +12.168 | regime break |
| 00884 | rates_daily | UST_2Y | 2021-10-19 | 126,189 | UST_2Y / 189 | +11.661 | regime break |
| 01131 | factors_daily | MKT | 2011-07-20 | 21 | MKT / 21 | -3.623 | vol spike |
| 01169 | g10_fx_daily | AUD | 2008-08-19 | 64 | AUD / 64 | -3.786 | vol spike |
| 01177 | macro_monthly | CPI_ALL | 2021-08-09 | 140,160 | CPI_ALL / 160 | +6.812 | monthly/vintage issue |
| 01247 | rates_daily | UST_2Y | 2021-12-17 | 126,189 | UST_2Y / 126 | +10.259 | regime break |
| 01263 | g10_fx_daily | AUD | 2020-03-20 | 64 | AUD / 64 | +4.330 | regime break |
| 01268 | g10_fx_daily | JPY | 2021-12-16 | 126,189 | JPY / 189 | +4.746 | regime break |
| 01338 | rates_daily | UST_2Y | 2018-11-08 | 126 | UST_2Y / 126 | -4.481 | drift extrapolation |
| 01430 | macro_monthly | CPI_ALL | 2008-09-09 | 140,160 | CPI_ALL / 140 | -6.494 | monthly/vintage issue |
| 01438 | rates_daily | UST_2Y | 2021-08-18 | 126,189 | UST_2Y / 189 | +11.532 | regime break |
| 01462 | rates_daily | UST_2Y | 2021-09-29 | 126,189 | UST_2Y / 189 | +13.635 | regime break |
| 01490 | g10_fx_daily | AUD | 2008-07-22 | 64 | AUD / 64 | -5.401 | regime break |
| 01680 | macro_monthly | UNRATE | 2008-06-05 | 145,165 | UNRATE / 165 | +6.199 | monthly/vintage issue |
| 01716 | g10_fx_daily | NOK | 2008-09-24 | 21 | NOK / 21 | +6.684 | regime break |
| 01727 | rates_daily | UST_2Y | 2021-09-24 | 126,189 | UST_2Y / 189 | +13.343 | regime break |
| 01956 | macro_monthly | CPI_ALL | 2021-05-27 | 140,160 | CPI_ALL / 160 | +6.572 | monthly/vintage issue |

The repeated UST_2Y cards in August–December 2021 forecast from exceptionally
quiet histories into a sustained move: forecast z reaches +13.63 and subsequent
step volatility is roughly 3.4–4.7× the local estimate. These overlapping cards
are one concentrated failure mode, not independent evidence. Mean reversion
may help drift extrapolation after trends, but this quiet-to-moving transition
primarily calls for a longer-history volatility floor. CPI has both negative
2008 and positive 2021 misses; a universal zero drift would discard useful
index trend. UNRATE needs separate persistence treatment. Factor and FX spikes
motivate a tail component without doubling the entire body.

Limitations carried forward: macro union values are latest observed vintages,
EM shapes use G10 substitutes, synthetic calendars use business days, and
practice dates are proxies. These results do not establish sealed-window
accuracy. This diagnosis inspected M0 outcomes across 2005–2024; subsequent
candidate selection will exclude 2019–2024 and practice proxies.

Detailed artifacts: `reports/phase2/m0-*.csv`, `m0-diagnosis.json`, and
`t2eval/diagnostics.py`. Step 1 is complete; validation is defined next before
any candidate results are measured.

## Phase 2 — Step 2 validation locked before tuning

The full predeclared protocol is [reports/phase2/VALIDATION.md](reports/phase2/VALIDATION.md).
Primary folds are as-of years 2009–2018; 2005–2008 provide warm-up labels only
for fold-fitted width calibration. Fold fitting purges labels whose target
crosses the test-year boundary. Candidate rules use only each card's history.
2019–2024 and the 88 practice proxies are reserved until the winner is frozen.
M0 and all candidates use 2,000 paired draws. Acceptance requires lower primary
CV mean, no extra caps, and no >10% regression in a major group. Fixed candidate
menus and every rejected ablation will be retained. Model selection on CV can
be optimistic; the final time holdout measures that risk. No candidate score
was inspected before writing this protocol.

## Phase 2 — ablations, frozen winner, and final evaluation

Every fixed-menu candidate was evaluated with 2,000 draws and the pinned
composite scorer. Full per-card/year/group evidence is in
[reports/phase2/ablations.json](reports/phase2/ablations.json),
[ablation-breakdowns.csv](reports/phase2/ablation-breakdowns.csv), and
[RESULTS.md](reports/phase2/RESULTS.md). Primary CV includes 1,073 cards in
2009–2018. The width-calibration pass initially failed because cached CSV frames
had reset indexes while in-memory frames retained filtered indexes. No width
result was accepted; resetting the roster index fixed the alignment and the
entire development pass was rerun before freezing. Predictions of the earlier
stages were unchanged. Logs: `.context/phase2/ablations-fixed.log`.

| Ablation vs previous accepted best | CV mean | Caps | Keep? |
|---|---:|---:|---|
| M0, 2,000 draws | 1.033389 | 1 | control |
| Zero drift | 0.963807 | 1 | no: monthly major-group regression |
| 25% drift | 0.959594 | 1 | yes |
| EWMA volatility | 0.960115 | 0 | no: mean worsened |
| Recent/full-history variance blend | 1.025695 | 0 | no: mean/group regressions |
| Empirical overlapping variance ratio | 0.964567 | 1 | no: mean worsened |
| Student-t df 5 | 0.999990 | 0 | no: mean worsened |
| 5% high-vol mixture | 0.973108 | 0 | no: mean worsened |
| Rates mean reversion | 0.963709 | 1 | no: mean worsened |
| Monthly log trend / UNRATE persistence | 0.953506 | 1 | yes |
| Longer correlation / shrinkage / continuation | 0.953077 | 1 | yes |
| Fold-fitted global width | 0.966927 | 1 | no: mean did not improve |

Fold widths: {"2009": 1.2, "2010": 1.1, "2011": 1.1, "2012": 1.1, "2013": 1.0, "2014": 1.0, "2015": 1.0, "2016": 1.0, "2017": 1.0, "2018": 1.0}. Final width retained at 1.0.

The frozen winner uses drift 0.25, monthly handling, and joint shrinkage;
volatility stays recent, tails Gaussian, and width 1.0. Frozen selection and
protocol checksum were recorded before reserved-year scoring. Runtime-only
hardening afterward made missing configuration fall back explicitly to M0,
checked M0 fallback finiteness, and honored the card's minimum draw count;
these changes do not alter the measured valid-card predictions.

| Evaluation | Cards | M0 mean | numeric_v1 mean | M0 caps | numeric caps |
|---|---:|---:|---:|---:|---:|
| Primary CV, 2009–2018 | 1073 | 1.033389 | 0.953077 | 1 | 1 |
| Reserved, 2019–2024 | 554 | 1.480838 | 1.456363 | 15 | 17 |
| All historical | 2060 | 1.210785 | 1.154244 | 23 | 23 |
| Practice proxies | 88 | 2.551735* | 2.435614 | 11* | 9 |

*Practice M0 retains the original 500-draw baseline; historical comparisons
above use 2,000 for both. Numeric medians: CV 0.703835, reserved 0.808653,
all-historical 0.760472, practice 1.376961. Reserved-year wins are 4/6;
equal-year paired delta -0.034823 with year-cluster SE 0.050554. This does not
establish a statistically robust improvement. Reserved monthly macro worsens
from 1.628784 to 2.014311 (26 cards, +23.7%). No model was retuned on those
results. **The capped-card reduction criterion is NOT met on the paired
comparison**, and reserved caps increase. Comparing numeric 23 to the original
500-draw M0's 24 would confound Monte Carlo and model changes.

The full official scorer run agrees with the fast adapter on all 2,060 numeric
cards, maximum score difference 8.88e-16; no failed forecasts or fallbacks.
Official run: `.eval/runs/backtest-numeric_v1-41bd6a29d0e4`. Practice run:
`.eval/runs/eval-practice-numeric_v1-743299aa1923`. Runtime is 24.86 seconds total
for historical forecasts; maximum 0.0941 seconds on the host.

Operational validation: 52 tests pass; pip check passes; 104/104 admissibility
passes with 2,000 draws (maximum recorded host forecast time 0.066 seconds).
The 10-asset card's complete output triplet is **418,931 bytes (0.400 MiB)**,
well below 64 MiB. A neutral optional text signal produces identical output
bytes, and injected failures exercise both recovery levels. All three amd64
images pass offline smoke tests with read-only root and non-executable /tmp.
Source/evaluation/report data stay out of the runtime context except t2agent.
The new image is an evaluated candidate, not a claim that every accuracy gate
passed. No competition pack/upload has been performed.

## Phase 2 — GHCR publication and anonymous verification

The package [agenthon-numeric-v1](https://github.com/hhwolf/agenthon/pkgs/container/agenthon-numeric-v1) is **Public**. GitHub Actions completed 52 tests, 104/104 admissibility gates (maximum Linux forecast time 0.174 seconds), an amd64 build, and the offline smoke test before publishing. [Successful workflow](https://github.com/hhwolf/agenthon/actions/runs/38650043739).

Immutable image:

`ghcr.io/hhwolf/agenthon-numeric-v1@sha256:25ffda44821a0493ba5ba69aeb570ec009a5e1081cd54d5e615fa3d51ac70a01`

The convenience tag is `numeric_v1`; the immutable commit tag is `b1f2225a5ef35a06c6f68e63c4f2c617cf49d300`. The starter-pack anonymous token/manifest check returned HTTP 200, as did all config/layer checks. A real Docker pull passed with an empty temporary credential configuration. The downloaded digest also passed all four official gates offline. The image runs as `runner`, declares no volumes, and contains no evaluation package, vendor tree, or parquet data. Evidence: anonymous-pull.json and published-image-smoke.json.

The package was already Public when published through GitHub Actions; no visibility change or browser login was needed. The verification token was anonymous and never logged. The Docker credential directory was empty and temporary. No competition submission was packed or uploaded.

## Text-layer contract — 2026-10-14

Added `docs/TEXT_LAYER.md` and `t2agent/contracts.py` so the text layer can be
built in parallel with the numeric engine. The contract is `read_text(unit_dir,
NumericSummary, CallBudget) -> TextSignal`; the numeric engine applies the
signal, and `TextSignal.neutral` must reproduce the numeric forecast exactly.
The budget caps admitted House requests at 20 of the 25 allowed per unit.
Development House access is closed, so development uses NVIDIA's hosted
Nemotron 3 Super through the same `MODEL_*` variables; `.env` is gitignored.
Clamp values are initial and will be set by the practice-proxy ablation.
`tests/test_contracts.py` covers the neutral signal and budget refusal.
`numeric_v1.apply_text_signal` already duck-types these types and applies the
same drift and weight bounds (see `docs/NUMERIC_V1.md`).

## Text layer — implementation, 2026-10-14

Implemented `t2agent/text_layer/` behind the frozen contract in `t2agent/contracts.py`
(`read_text(unit_dir, NumericSummary, CallBudget) -> TextSignal`). The contract types were not
changed. The forecaster is not wired; the numeric owner applies the signal via
`numeric_v1.apply_text_signal`, which already accepts these dataclasses (verified by test).

### Setup on this machine

- `make setup` needs Python 3.13 (`qfbench2-common` requires `>=3.13`); none was installed, so
  `python@3.13` was added with Homebrew and the venv rebuilt with
  `PYTHON_BOOTSTRAP=/opt/homebrew/bin/python3.13 make setup`. Toolkit 2.6.0 and track 3.1.0 as pinned.
- `openai==3.31.0` is now a runtime dependency (`requirements-runtime.txt`, `pyproject.toml`); its
  closure is pinned in `constraints-eval.txt` (`pip check` clean). The SDK uses `httpx2` with
  `trust_env`, so the harness's `HTTP(S)_PROXY` is honoured without any code.
- **No `.env` / NVIDIA key exists on this machine**, so the dev-model sweep could not be run. Everything
  below was measured against `tests/mock_house.py`; the dev sweep command is ready
  (`scripts/run_text_layer_practice.py --mode dev`) and caches under `.eval/llm_cache/`.

### Decisions

1. **House client exactly per §3.** `OpenAI(base_url=$MODEL_ENDPOINT.rstrip('/')+'/v1', api_key=$MODEL_TOKEN,
   max_retries=0, timeout)`, `model=$MODEL_NAME`, `temperature=0`, `top_p=1`, `seed=20261014`,
   `max_tokens<=4000`, no tools, `n` never set. `budget.spend()` is called immediately before every
   request, including retries and repairs; a cache hit sends nothing and spends nothing.
2. **Offline = zero attempts.** `QFBENCH_NETWORK=none`, or any of `MODEL_ENDPOINT`/`MODEL_TOKEN`/
   `MODEL_NAME` unset, returns `TextSignal.neutral(reason="offline (...)")` before a client exists.
   A missing `openai` install is a failure (neutral), not offline.
3. **Request plan.** Documents are prioritised (decision/statement 0, release 1, minutes 2, beige book
   and speech 3, landmark 4; one level = 60 days of recency; card keywords earn up to 90 days), split at
   paragraph boundaries into <= 20K-token segments and first-fit packed into <= 45K-token chunks
   (`MAX_INPUT_TOKENS_PER_CALL=48_000` minus 3K prompt overhead, chars/4). Chunks are capped at
   `MAX_EXTRACTION_CALLS=6` and at `budget_remaining - 2`; overflow segments are listed in the
   rationale as "Not sent (budget)". Extraction calls run with thinking off, three in parallel;
   the single synthesis call runs with thinking on. One repair per call, and the synthesis repair
   runs with thinking off so a truncated reasoning trace cannot eat the 4,000-token limit twice.
   A `400 ... context length` reply splits that chunk in two once. Hard cap: worst case
   6 extraction + 6 repairs + synthesis + repair = 14 < 20.
4. **Evidence validation.** Claims whose `doc_id` is not in the corpus are dropped. `established=True`
   survives only when the model's verbatim quote is found in that document (whitespace/case/curly-quote
   tolerant); otherwise the item is demoted to inferred. Narrowing (`vol_mult < 1`) is allowed only when
   at least one established item remains, matching the check `apply_text_signal` repeats.
5. **Clamps as named constants** (`t2agent/text_layer/constants.py`): per-scenario drift +/-1.5, weighted
   mean drift +/-0.5 with proportional rescaling of every scenario's drift for that asset, vol 0.8-2.0
   with the inferred floor at 1.0, tail 1.0-2.0, weight >= 0.05 (smaller scenarios dropped and the rest
   renormalised), 1-4 scenarios. Drifts are rounded to 6 decimals and the mean bound is re-checked after
   rounding. Ablation changes only this file.
6. **Time.** `TIME_BUDGET_S=600` per unit; each request's timeout is `min(120 s, remaining - 30 s)`
   (synthesis up to 240 s), backed by a daemon-thread wall clock so a stalled socket cannot exceed it.
7. **Rationale.** `rationale_md` lists documents read/dropped, an evidence table with E/I flags, the
   scenario table with cited evidence numbers, every clamp applied (before -> after), and an adjustment
   ledger per asset: weighted drift arithmetic, centre shift in value units per horizon, mixture
   vol_mult, tail_mult, and the request log. Neutral signals carry the reason.
8. **Dev cache** keyed by sha256(unit_id, model, full request params incl. messages), opt-in through
   `TEXT_LAYER_CACHE_DIR` (the sweep script sets `.eval/llm_cache/`); it never exists in the image.

### Results (mock House; dev model pending a key)

- `make test`: **85 passed** (54 existing + 31 text-layer tests: clamps, inferred-floor, quote and
  citation validation, neutral fallbacks, budget counting with failed/auth/transient calls, offline mode,
  time budget, hard cap on a 40-document corpus, context-overflow split, JSON repair for extraction and
  synthesis, cache, post-as-of drop, numeric-adapter compatibility, one real practice unit).
- `scripts/run_text_layer_practice.py --mode mock` on all 104 units (`.eval/text_signals_mock/`):
  **104/104 non-neutral, 354 requests total, 2-4 per unit (median 3), max 4 of the 20 cap**, 4.4 s wall.
  Corpora of up to 549K chars pack into 3 extraction requests of <= 48K estimated tokens.
- `--mode mock --mock-scenario extreme` (out-of-range model output, fabricated citations):
  104/104 units inside every bound; vol floored at 1.0 because no established evidence survived.
- `--mode offline` (`QFBENCH_NETWORK=none`): 104/104 neutral, **0 requests**.
- Mock-driven signal statistics (not a text-ablation result): mean |weighted drift| 0.21 sd, mixture
  vol 1.125, tail 1.2, 3 scenarios, about 22 evidence items per unit of which half established.

### Open items

- Run `--mode dev` with a `build.nvidia.com` key in `.env` to produce `.eval/text_signals/` with the
  real model, then the §9 ablation (`numeric_v1` vs `numeric_v1 + apply_text_signal`) by family.
  Verify `enable_thinking=False` on the dev endpoint and the real token counts per request.
- Prompt and clamp values are initial; tune `constants.py` from the ablation, never per unit.

## Phase 2.5 — protocol before scoring, 2026-10-15

Read the Phase 2 diagnosis, validation, results and numeric guide. Existing
`.eval/` is present and is preserved under the published restore instructions.
The unnormalized t5 and mixture tails confound shape with variance (5/3 and 1.4).
Phase 2.5 evaluates the fixed A1–A6 menu in
[VALIDATION_2_5.md](reports/phase2_5/VALIDATION_2_5.md) before any new scores.
Practice proxies now constrain selection under the user's C1 rule; reserved
2019–2024 can veto >15% major-group regressions but cannot rank candidates.
The old runtime config and Phase 2 freeze are protected by SHA-256 checks.

### Phase 2.5 — frozen experiment and independent verification

All 55,005 published evaluation files matched the archive manifest; no restore
or overwrite was necessary. The fixed menu produced 15 candidate rows plus the
bit-identical numeric_v1 control. A1 filtered historical simulation is selected:
CV 0.953077 → 0.951081, practice 2.435614 → 2.415744, held-out 1.456363 → 1.454208.
CV+practice caps stay 10; held-out caps rise 17 → 18, all-historical 23 → 24.
No cap is removed. Synthetic card 01446 (UST_2Y/UST_10Y, 2022-02-11) changes
7.994 → 8.000. These overlapping-card results do not establish robust accuracy:
all paired year-block 95% CIs include zero. The monthly and rate-trend issues
remain unresolved because their alternatives failed the fixed acceptance rule.

The initial runner stopped before scoring because pandas `rows.asof` resolves
its method, not the column; explicit column indexing fixed it. No scoring menu
or inference rule changed after results were seen. The selected engine passed
100 tests and 104/104 official admissibility checks. Independent review
recomputed every candidate metric, breakdown, C1 decision, veto, and paired CI
from tracked CSVs and found no selection mismatch. Post-freeze evaluation-only
hardening will reject mismatched paired rosters and bind caches to input data
and the environment seed; recorded candidate predictions stay frozen.
