<style>
body { font-size: 10.5pt; line-height: 1.34; color: #172432; }
h1 { font-size: 23pt; line-height: 1.16; margin: 0 0 14pt; color: #17364b; }
h2 { font-size: 14pt; line-height: 1.2; margin: 16pt 0 6pt; color: #17364b; }
p { margin: 0 0 8pt; }
li { line-height: 1.34; margin-bottom: 4pt; }
ul { margin: 6pt 0 10pt; }
table { font-size: 10pt; line-height: 1.3; margin: 8pt 0 12pt; }
th, td { padding: 5pt 7pt; }
th { background: #edf3f6; color: #17364b; }
code { font-size: 9pt; overflow-wrap: anywhere; }
</style>

# Agenthon 2026 · Track 2 results

**Phase 0–1: environment and backtest harness**  
Measured October 14, 2026 · Local evaluation · Lower scores are better

## Main results

The measurement loop is implemented and validated. The published M0 baseline scores lower than the vendor reference CLI on the historical benchmark. Neither forecaster was optimized during this phase.

| Evaluation | Cards | M0 | Reference CLI |
|---|---:|---:|---:|
| Historical pseudo-cards | 2,060 | **1.214629** | **1.394364** |
| Sibling-panel practice proxies | 88 | **2.551735** | **2.557722** |

Both evaluation modes use the official scorer and M0 expected-error normalization. There were **zero forecast failures**. Historical scores reached the 8.0 cap on 24 M0 cards and 22 reference cards; practice scores reached it on 11 and 10 cards, respectively.

**Practice results are proxy measurements.** Of the 88 resolved cards, 85 use inferred business-day target dates and 3 use explicit observation months. They are not verified sealed answers or organizer leaderboard scores.

## Normalization check

| M0-generated outcome experiment | Scored cases | Mean | Standard error |
|---|---:|---:|---:|
| One independent outcome per card | 2,060 | 0.951098 | 0.012463 |
| 20 additional outcomes per card | 41,200 | **1.002631** | **0.003014** |

The repeated-outcome check supports the normalization implementation. Its standard error is measured across 20 replicate means. The original 0.951098 result is retained. Historical outcomes need not follow M0's model, so the historical score is not expected to equal exactly 1.0.

## Validation

- **25 tests passed**, including the published M0 worked example and monthly, transfer-gap, date-alignment, seed and output checks.
- **104/104 units pass g0–g3 for each forecaster.** Maximum measured host inference time: M0 0.060 s; reference 0.057 s.
- **Three linux/amd64 images pass all four gates offline:** untouched upstream reference, toolkit-v2.6.0 reference variant, and the M0 image.

# Historical results by family and panel

All tables on this and the following page describe the same 2,060 historical pseudo-cards. Each card contributes equally to the overall mean.

## Card family

| Group | Cards | M0 | Reference |
|---|---:|---:|---:|
| F1 · Continuation with context | 460 | 1.497624 | 2.110561 |
| F2 · Text-cued regime shift | 540 | 1.087573 | 1.091221 |
| F3 · Cross-asset reasoning | 440 | 1.219362 | 1.280128 |
| F4 · Tail / shock from text | 620 | 1.111968 | 1.208091 |

## Panel

| Group | Cards | M0 | Reference |
|---|---:|---:|---:|
| Daily factors | 320 | 1.122978 | 1.239347 |
| Daily G10 FX | 700 | 1.131343 | 1.193123 |
| G10 FX + rates | 100 | 1.192919 | 1.298607 |
| Monthly macro | 80 | 1.687447 | 2.095316 |
| Daily rates | 860 | 1.275065 | 1.561775 |

M0 scores lower in each family and panel aggregate on this dataset. These comparisons describe this historical sample; they do not establish performance on the sealed Final set.

The family labels preserve the practice templates' shapes. Random historical cutoffs do not recreate the original text-driven regime or shock selection. No text was supplied to the synthetic cards.

# Historical results by target and shape

## Target type

| Group | Cards | M0 | Reference |
|---|---:|---:|---:|
| Level | 1,740 | 1.231485 | 1.422873 |
| Cumulative log return | 320 | 1.122978 | 1.239347 |

## Maximum declared horizon

| Group | Cards | M0 | Reference |
|---|---:|---:|---:|
| 1–21 | 520 | 1.085013 | 1.194082 |
| 22–63 | 580 | 1.104007 | 1.147564 |
| 64–126 | 500 | 1.217396 | 1.230045 |
| 127+ | 460 | 1.497624 | 2.110561 |

Buckets use the largest declared horizon key on a card. Monthly targets retain their published keys while the forecast converts them to calendar-month steps.

## Forecast grid

| Group | Cards | M0 | Reference |
|---|---:|---:|---:|
| Joint: multiple asset/horizon cells | 860 | 1.353166 | 1.723316 |
| Single: one asset at one horizon | 1,200 | 1.115344 | 1.158615 |

## Scoring convention

Each raw component is computed by the official scorer, then divided by M0's expected error on that card. Joint cards use weights 0.5 CRPS, 0.3 variogram and 0.2 tail pinball. Single-cell cards use exact weights 5/7 CRPS and 2/7 tail. Scores are clipped to [0, 8]; a failed forecast remains in the mean at 8.

# Data limits and reproducibility

## Benchmark construction

The union contains **146,692 distinct panel/asset/date rows** from **103 practice units**, drawn from 3,437,361 source rows. The illustrative exemplar is excluded from the union and tested separately.

The historical benchmark has exactly **20 cards per practice template**: 1,980 daily cards and 80 monthly cards. As-of dates span **January 3, 2005 to September 25, 2024**, with every year represented. Target types total 1,740 level and 320 log-return cards. Every generated card contains truncated input panels and a realized outcome file; no text is used.

## Limits that affect interpretation

- **Revised macro history:** 1,045 macro keys have conflicting vintages. The latest source cutoff wins deterministically. This is not a certified point-in-time vintage benchmark; monthly publication lags are preserved when truncating inputs.
- **EM substitutions:** 100 synthetic cards replace unavailable continuous EM histories with matching G10 FX shapes. They preserve family, target type, asset count and horizons, but do not measure actual EM forecasting performance.
- **Practice dates and outcomes:** 15 practice units have no complete sibling outcome under the proxy rules. Missing target rows are not interpolated. Strict-date mode resolves only 3 cards, with M0 mean 5.803162; even explicit months do not certify the sealed vintage. The README's 75 exact sealed matches cannot be verified from the public dates alone.
- **Specification differences:** M0 uses return rows literally as documented; the current reference CLI first applies log1p. For Sahm, current panel dates and named months imply 7/8 steps, while the older M0 table states 8/9. The implementation follows current explicit inputs without per-unit overrides.

## Reproduce these measurements

Use `make backtest FORECASTER=m0` and repeat with `FORECASTER=reference`. The corresponding commands are `make eval-practice`, `make admissibility`, and `make calibration`. Run `make test` and `make docker-smoke` for validation.

Runs use **500 forecast draws**, dataset seed **20261014**, M0's CRC32(unit_id) default seed and the reference's seed 0. Explicit seeds or QFBENCH_SEED override defaults. Local scoring uses **qfbench2-common v2.6.0**, track package **3.1.0**, Python **3.13.7** and pinned numeric dependencies.

Sources: workspace `BASELINES.md`, `BUILD_LOG.md`, and the retained JSON/CSV reports under `.eval/runs/`. Reference checkout: `b9c663d239a0e6b86ebd3f3f2d5aead88516067d`. Evaluation data and realized values are excluded from the runtime image. No forecaster tuning or Final submission was performed.
