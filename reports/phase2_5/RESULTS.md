# Agenthon Track 2: numeric_v1.1

Phase 2.5 • 15 October 2026 • 2,000 draws • Lower scores are better

## Decision

Frozen selection: **A1_fhs5**. CV mean improves by **0.21%** versus numeric_v1.
The fixed C1 rule and held-out major-group veto determine acceptance, with no added candidates after scoring.
Practice proxies participate in selection; they are not independent validation.

| Partition | Cards | numeric_v1 | numeric_v1.1 | Caps v1 → v1.1 | v1.1 median |
| --- | --- | --- | --- | --- | --- |
| CV 2009–2018 | 1073 | 0.953077 | 0.951081 | 1 → 1 | 0.706113 |
| Practice proxies | 88 | 2.435614 | 2.415744 | 9 → 9 | 1.365856 |
| Report-only 2019–2024 | 554 | 1.456363 | 1.454208 | 17 → 18 | 0.807978 |
| All historical | 2060 | 1.154244 | 1.152537 | 23 → 24 | 0.759077 |


## Paired year-block bootstrap

| Partition | Mean difference | 95% percentile CI | Year wins |
| --- | --- | --- | --- |
| CV 2009–2018 | -0.001996 | [-0.005101, +0.000993] | 7/10 |
| Practice proxies | -0.019870 | [-0.041089, +0.003438] | 15/22 |
| Report-only 2019–2024 | -0.002155 | [-0.010985, +0.004177] | 4/6 |
| All historical | -0.001707 | [-0.004565, +0.000716] | 13/20 |


10,000 whole-year resamples, seed 20261015, pooled card-weighted means. Negative differences favor v1.1.
Intervals include dependence within each year but do not correct for selecting models on these same data.
Previously inspected 2019–2024 is report-only except for a fixed >15% group-regression veto.


# Fixed-menu ablations

Each stage compares alternatives with the best entering that stage. All candidates are retained, including rejected ones.
Full previous-best identifiers, medians, errors, CIs, and breakdowns are in ablations.json and the companion CSVs.

| Candidate | CV mean | Caps | Practice mean | Caps | 2019–24 mean | Caps | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| numeric_v1 | 0.953077 | 1 | 2.435614 | 9 | 1.456363 | 17 | Baseline |
| A1_t5 | 0.944728 | 1 | 2.443867 | 9 | 1.451030 | 17 | Reject |
| A1_mixture | 0.944169 | 1 | 2.472831 | 10 | 1.460843 | 17 | Reject |
| A1_fhs5 | 0.951081 | 1 | 2.415744 | 9 | 1.454208 | 18 | Kept |
| A2_63 | 1.057331 | 0 | 2.341555 | 9 | 1.399092 | 15 | Reject |
| A2_126 | 1.034196 | 0 | 2.353575 | 9 | 1.403075 | 16 | Reject |
| A2_252 | 1.006287 | 0 | 2.367163 | 9 | 1.411043 | 16 | Reject |
| A3_0.25 | 0.966306 | 1 | 2.410641 | 9 | 1.441536 | 18 | Reject |
| A3_0.5 | 0.994654 | 1 | 2.359592 | 9 | 1.426048 | 16 | Reject |
| A4_damp025 | 0.949968 | 1 | 2.491765 | 10 | 1.439492 | 18 | Reject |
| A4_damp05 | 0.946507 | 1 | 2.479900 | 10 | 1.437041 | 18 | Reject |
| A4_window36 | 0.951304 | 1 | 2.490762 | 10 | 1.437440 | 18 | Reject |
| A4_m0 | 0.954830 | 1 | 2.512595 | 10 | 1.448952 | 19 | Reject |
| A5_pool | 0.945439 | 1 | 2.453559 | 9 | 1.456947 | 19 | Reject |
| A6_sign01 | 0.955201 | 1 | 2.391356 | 9 | 1.475665 | 18 | Reject |
| A6_sign025 | 0.976674 | 0 | 2.344106 | 8 | 1.462074 | 19 | Reject |


## Acceptance and ordering

C1 requires a lower CV mean, or at most +0.005 worse with fewer combined CV+practice caps;
practice mean must not worsen, combined caps cannot rise, and no major CV/practice group may worsen >10%.
Major means ≥40 cards, or ≥20 for monthly macro. The reserved-year veto is >15% against either previous best or numeric_v1.
Ties within 0.0005 prefer fewer changed knobs. Year groups themselves are descriptive.

A1 isolates tail shape by normalizing variance. A2 uses exp(−h/τ) recent/long-run variance weights.
A3 floors variance. A4 changes only monthly handling. A5 pools whole joint draws 50/50; A6 replaces daily drift with momentum-sign drift.


# Reserved-year behavior

The precommitted veto checks major family, panel, horizon and single/joint groups.
These results did not rank candidate performance or expand the menu.

| As-of year | Cards | v1 mean | v1.1 mean | Change | Caps |
| --- | --- | --- | --- | --- | --- |
| 2019 | 91 | 1.3561 | 1.3540 | -0.2% | 0 → 0 |
| 2020 | 95 | 1.4570 | 1.4624 | +0.4% | 1 → 1 |
| 2021 | 110 | 2.0428 | 2.0500 | +0.4% | 12 → 12 |
| 2022 | 119 | 1.7295 | 1.7288 | -0.0% | 4 → 5 |
| 2023 | 97 | 0.7542 | 0.7341 | -2.7% | 0 → 0 |
| 2024 | 42 | 0.9839 | 0.9773 | -0.7% | 0 → 0 |


| Group | Cards | v1 mean | v1.1 mean | Change | Caps |
| --- | --- | --- | --- | --- | --- |
| factors_daily | 77 | 1.0850 | 1.0665 | -1.7% | 1 → 1 |
| g10_fx_daily | 183 | 1.0864 | 1.0918 | +0.5% | 2 → 2 |
| g10_fx_daily+rates_daily | 20 | 1.7232 | 1.7337 | +0.6% | 1 → 1 |
| macro_monthly | 26 | 2.0143 | 1.9397 | -3.7% | 2 → 2 |
| rates_daily | 248 | 1.7646 | 1.7686 | +0.2% | 11 → 12 |
| T2-F1 | 122 | 2.0610 | 2.0483 | -0.6% | 12 → 13 |
| T2-F2 | 144 | 1.2368 | 1.2448 | +0.6% | 1 → 1 |
| T2-F3 | 121 | 1.4984 | 1.4980 | -0.0% | 2 → 2 |
| T2-F4 | 167 | 1.1736 | 1.1690 | -0.4% | 2 → 2 |
| 127+ | 122 | 2.0610 | 2.0483 | -0.6% | 12 → 13 |
| 1–21 | 137 | 1.1258 | 1.1219 | -0.4% | 1 → 1 |
| 22–63 | 158 | 1.3111 | 1.3135 | +0.2% | 1 → 1 |
| 64–126 | 137 | 1.4161 | 1.4198 | +0.3% | 3 → 3 |
| joint | 236 | 1.7469 | 1.7382 | -0.5% | 13 → 14 |
| single | 318 | 1.2407 | 1.2434 | +0.2% | 4 → 4 |


All smaller groups are shown, even when below the veto threshold. Full CV and practice group tables are in ablation-breakdowns.csv.


# Capped cards and known weaknesses

**0 removed, 1 new** capped evaluation rows across historical and practice.
Overlapping practice/historical outcomes are separate rows, not independent events.

| Partition | Change | Card suffix / unit | Assets | As-of | v1 → v1.1 |
| --- | --- | --- | --- | --- | --- |
| held-out | new | 01446 | UST_2Y,UST_10Y | 2022-02-11 | 7.994 → 8.000 |


Full card identifiers and horizon labels: capped-changes.csv.

## Previously identified 2022 regressions

| Historical subset | Cards | v1 mean | v1.1 mean | Caps |
| --- | --- | --- | --- | --- |
| Monthly macro, 2022 | 8 | 2.7957 | 2.6590 | 1 → 1 |
| Rates, 2022 | 55 | 1.8842 | 1.8908 | 1 → 2 |
| All historical, 2022 | 119 | 1.7295 | 1.7288 | 4 → 5 |


These are post-selection diagnostics. Late-2021 zero-bound rates, 2008 and COVID transitions remain important stress cases.
The monthly series use revised historical vintages; improvements here do not establish real-time macro accuracy.


# Reproducibility and delivery

## Frozen rules

```json
{
  "drift": 0.25,
  "volatility": "recent",
  "variance_ratio": false,
  "tails": "fhs5",
  "rates_reversion": false,
  "monthly": true,
  "joint": true,
  "width": 1.0,
  "term_tau": 0.0,
  "vol_floor": 0.0,
  "monthly_damping": 1.0,
  "monthly_window": 12,
  "momentum": 0.0,
  "components": []
}
```

The immutable Phase 2 numeric_config.json and frozen-selection.json are unchanged.
New configuration: reports/phase2_5/numeric_v1_1_config.json; runtime copy: t2agent/numeric_v1_1_config.json.
The protocol was committed as da26396 before scores. All 55,005 archived evaluation files matched their published manifest.

## Operational validation

Operational validation is pending; this draft is not a completed delivery.

Image publication and anonymous-pull verification are pending.

## Limits and reproduction

CV and practice were used for selection. Year-block CIs do not remove that selection bias.
Practice includes 85 inferred business-day target sets and three explicit monthly sets.
Macro values include revisions; EM shapes can use G10 substitutes; historical calendars are approximations.
No sealed outcomes or organizer feedback were used. No competition pack or submission upload was run.

Restore data per reports/EVALUATION_DATA.md. Run `.venv/bin/python -m t2eval.phase2_5` in a fresh output copy;
it refuses to overwrite a freeze. Then run `make test`, `make admissibility FORECASTER=numeric_v1_1`, and
`make backtest FORECASTER=numeric_v1_1`. Every ablation calls the pinned official scoring implementation.
