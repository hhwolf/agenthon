# numeric_v1.1

Phase 2.5 keeps the Phase 2 engine and freeze intact. The separate module
`t2agent.numeric_v1_1` loads `numeric_v1_1_config.json`. The CLI defaults to this
version; `--forecaster numeric_v1` and `--forecaster m0` remain available.
It is text-free, with the same optional keyword-only `text_signal` hook.
Neutral signals preserve output bytes. Seeds follow explicit argument,
QFBENCH_SEED, then CRC32(unit_id). Default draws: 2,000.

See [results](../reports/phase2_5/RESULTS.md), the
[precommitted protocol](../reports/phase2_5/VALIDATION_2_5.md), and
[frozen selection](../reports/phase2_5/frozen-selection.json) for measured rules
and limitations. The new C1 rule uses practice proxies for selection; they no
longer provide an independent check. Previously inspected 2019–2024 is used
only for reporting and the predeclared major-group veto.

## Candidate implementation

- t5 and 5% high-volatility mixtures have unit innovation variance, correcting
  the width confound in the original Phase 2 candidates. The old candidates
  remain unchanged for reproducibility.
- Filtered historical simulation standardizes changes with lagged EWMA
  variance (half-life 60), samples common multivariate five-change blocks,
  and normalizes the population covariance of the block sums to the target
  segment covariance. It does not normalize the realized Monte Carlo sample.
  Less than 20 complete residual rows uses normalized t5; missing covariance
  dimensions in collinear histories receive independent Gaussian innovations.
- Optional term structure mixes recent and full-input-history step variance
  with exp(-h/tau). A separate floor can bound it relative to long history.
  Monthly indexes use log-change variance and mapped monthly steps.
- Monthly alternatives damp the 12-change trend, extend it to 36 changes, or
  restore M0-style level modeling with the retained global drift coefficient.
- A linear pool draws half the complete joint paths from each component with
  deterministic independent child seeds. It never chooses by realized outcome.
- Momentum alternatives replace daily trailing drift with the sign of the
  last 126 valid changes times a small horizon-SD fraction.

The existing joint correlation rule uses up to 1,260 changes with 20% identity
shrinkage. Cumulative variances use a monotone envelope; each later horizon
adds an independent continuation. All numeric estimates use only supplied
pre-cutoff input. Evaluation rosters, outcomes, caches and reports stay out of
the runtime image through the Docker allowlist.

## Evaluation and runtime

```sh
make test
make admissibility FORECASTER=numeric_v1_1
make backtest FORECASTER=numeric_v1_1
make eval-practice FORECASTER=numeric_v1_1
make docker-smoke FORECASTER=numeric_v1_1
```

Restore `.eval` per [EVALUATION_DATA.md](../reports/EVALUATION_DATA.md).
`.venv/bin/python -m t2eval.phase2_5` runs the fixed menu in a fresh output copy
and refuses to overwrite an existing Phase 2.5 freeze. Every candidate uses
exactly the same cards, normalizers and official composite implementation.
`python -m t2eval.phase2_5_report` rebuilds result tables from recorded scores.
The paired uncertainty calculation resamples entire as-of years, retaining
all cards within a selected year.

The runtime wrapper recovers from numeric exceptions using M0, then a wide
random walk, with the fallback named in the rationale. The existing writer
creates all three files. Valid card metadata and writable storage are required.
No text-model requests are made, and no competition pack/upload is run.

## Image publication

Tags `numeric-v1.1-*` trigger `.github/workflows/numeric-v1-1-image.yml`:
full tests, official 104-card admissibility, amd64 build, offline read-only
exemplar smoke, then GHCR push. The package remains
`ghcr.io/hhwolf/agenthon-numeric-v1`, with a separate `numeric_v1_1` convenience
tag and an immutable source-commit tag. The old `numeric_v1` tag is preserved.
The exact registry digest and credential-free pull evidence are recorded in
`reports/phase2_5/publication.json` and `anonymous-pull.json`.
