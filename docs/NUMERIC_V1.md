# numeric_v1

A text-free, 2,000-draw forecaster with an optional text-signal adapter. The
candidate improves mean scores but **has not met the paired capped-card reduction
gate**. See [Phase 2 results](../reports/phase2/RESULTS.md) and the
[predeclared protocol](../reports/phase2/VALIDATION.md).

## Runtime

```python
from t2agent.numeric_v1 import forecast
frame = forecast(card, panels, None, asof, n_draws=2000, seed=7)
# Optional: keyword-only text_signal=signal
```

The six existing positional arguments remain compatible. The Phase 2 image defaults to numeric_v1 and 2,000 draws. The newer CLI/image
default to numeric_v1_1; use `--forecaster numeric_v1 --text-mode numeric_only` for this numeric freeze; `--forecaster m0` preserves the
500-draw baseline. Explicit seed wins over `QFBENCH_SEED`, otherwise CRC32 of the
unit identifier supplies a deterministic seed. Numeric sampling never opens text or evaluation artifacts. Phase 4 optionally reads text after sampling; see [the integration guide](PHASE4_TEXT.md). Inference never opens realized values or per-unit answer tables.

The frozen JSON configuration retains 25% of the trailing drift, 300-observation
volatility, square-root time scaling, and Gaussian innovations. Positive monthly
indexes instead extrapolate the last 12 monthly log changes; UNRATE persists.
Monthly steps preserve the existing observation-period and publication-lag
mapping. Correlation uses up to 1,260 aligned changes and 20% shrinkage toward
identity. Each interval has one multivariate shock per draw; later horizons add
independent continuation. The covariance is positive semidefinite by construction.

The longer-history volatility blend, EWMA, empirical variance ratio, Student-t,
small high-volatility mixture, rate reversion, and fold-fitted global width were
evaluated but rejected. Their rules remain available through `Config` for
reproduction; runtime loads only the frozen configuration.

## Text adapter

`apply_text_signal(samples, card, signal, seed)` accepts dictionaries or the
teammate's dataclasses by attribute access, without importing or changing their
separate contract branch. A signal can contain `scenarios`, each with `weight`,
`drift_sd` by asset (in numeric horizon-SD units), and `vol_mult`; a simple mapping
with `drift_sd` and `vol_mult` also works. Optional `tail_mult` and established
evidence are supported. One scenario is selected for the complete joint draw.

There are 1–4 scenarios; weights must be finite and at least 0.05 before
normalization. Drift is bounded at ±1.5 SD per scenario and aggregate drift at
±0.5 SD per asset (±0.6 for the explicit Phase 4 binary branches). Volatility is bounded at 0.8–2, with narrowing allowed only
with established evidence. Tail scaling is 1–2 and affects only the outer 5% of
numeric draws. A neutral signal returns the original samples without consuming
RNG; sample bytes remain identical. An invalid signal leaves numeric samples unchanged and records the problem in the rationale. Current engines can read text after sampling; the provisional Phase 4 card-notes choice makes zero House calls.

## Recovery and output

Inference exceptions fall back to M0, then to a wide random walk. Missing or
unreadable panels at the CLI enter the same recovery path. Recovery preserves the
complete asset/horizon grid and writes forecast.parquet, forecast_meta.json, and
forecast_rationale.md through the existing validated writer. The rationale names
fallbacks. A valid card and writable output filesystem are necessary: a missing
card cannot supply the required grid, and no program can guarantee writes to a
full or unwritable disk.

## Reproduce measurements

Restore the Phase 1 evaluation archive documented in
[EVALUATION_DATA.md](../reports/EVALUATION_DATA.md), then:

```sh
make setup
.venv/bin/python -m t2eval.diagnostics
# Use a separate checkout/output copy if reproducing development: the runner
# refuses to overwrite an existing frozen-selection.json.
.venv/bin/python -m t2eval.ablations develop
.venv/bin/python -m t2eval.ablations holdout
make backtest FORECASTER=numeric_v1
TEXT_LAYER_MODE=numeric_only make eval-practice FORECASTER=numeric_v1
make admissibility FORECASTER=numeric_v1
make docker-smoke FORECASTER=numeric_v1
```

The ablation adapter calls the pinned official composite, and a full official
CLI pass verifies all 2,060 resulting scores. Detailed candidate and yearly/group
scores are tracked under reports/phase2; full forecast draws remain in .eval.
The image context allowlist excludes both.

## Publish

The GitHub Actions workflow `numeric-image.yml` runs tests, all 104 gates, an
amd64 build, and an offline read-only smoke test before pushing to
`ghcr.io/hhwolf/agenthon-numeric-v1`. It triggers on `numeric-v1-*` tags and manual
dispatch. The immutable commit tag and registry digest identify the image;
`numeric_v1` is a convenience tag. Public visibility and credential-free pull
are separately verified and recorded in the Phase 2 publication evidence.
No competition pack or submission upload command is run.
