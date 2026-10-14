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
[the figure](m0-pit-histograms.png). The CSV includes every
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
