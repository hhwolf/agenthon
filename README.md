# Track 2 measurement loop

This workspace implements the published M0 baseline and local evaluation for
Agenthon 2026 Track 2. It does not optimize the forecaster or use text yet.
See [BUILD_LOG.md](BUILD_LOG.md) for provenance, ambiguities and measured results.

Use Python 3.13 or newer and the pinned upstream checkout:

```sh
PYTHON_BOOTSTRAP=python3.13 make setup
make test
make reference-smoke
make docker-smoke
```

On this Mac, the environment is already installed in `.venv`. Docker runs in
Colima's `agenthon` profile (`colima start agenthon` after a restart). Every image
build uses `docker buildx build --platform linux/amd64 --load`. The Docker smoke
script checks the untouched upstream Dockerfile, a staged toolkit-v2.6.0 variant,
and our inference-only image, offline, against all four official gates.

Run the measurement loop:

```sh
make backtest FORECASTER=m0
make backtest FORECASTER=reference
make calibration FORECASTER=m0
make eval-practice FORECASTER=m0
make eval-practice FORECASTER=reference
make admissibility FORECASTER=m0
make admissibility FORECASTER=reference
```

Measured results are in [BASELINES.md](BASELINES.md) and the
[four-page results PDF](reports/Agenthon_Track2_Results_2026-10-14.pdf)
([Markdown source](reports/Agenthon_Track2_Results_2026-10-14.md)). For an optional repeated
Gaussian-outcome diagnostic, run `scripts/calibration_diagnostic.py` with the M0
backtest report directory and `--replicates 20`; BUILD_LOG records the exact command.

`backtest` generates **2,060 historical pseudo-cards** by default (20 for each
practice template), then prints normalized score tables. `CARDS=...` changes the
size; `ARGS='--limit 10'` scores a labelled debug subset. Shared optional flags
include `--dataset-seed`, `--seed`, `--n-draws`, `--work`, and `--units`. Run
`.venv/bin/python -m t2eval.cli --help` for the full interface.

Each report contains raw components, M0 divisors, normalized components, unclipped
and clipped scores, failures, warnings, forecast timing, per-card provenance and
breakdowns by family, panel, target type, maximum-horizon bucket and single/joint
shape. Failed forecasts stay in the mean at 8.0. The official scorer receives
`score --card ... --forecast ... --realized ...` through its Python CLI entrypoint;
no CRPS, variogram or tail scoring math is copied here.

Evaluation artifacts live under `.eval/`, which is gitignored and excluded from
Docker. This includes the union, donor provenance, generated cards with truncated
panels and `realized.parquet`, forecasts, and reports. The 103 practice units are
the union sources; the small illustrative exemplar is tested separately. The
union preserves all source vintages and uses the latest source cutoff to resolve
revisions. Synthetic cards preserve template families, target types, asset
counts, horizons and actual daily/monthly cadence. Missing continuous EM histories
are represented by matching G10 FX shapes, with the substitution in the manifest.
The family label reproduces the shape distribution; randomly chosen historical
cutoffs do not recreate the original text-driven regime/shock selection.

Read scores with these limits:

- **Historical backtest:** actual outcomes from the panel union. Later macro
  revisions may be present; this is not a certified point-in-time vintage test.
  Monthly input truncation preserves each template's publication lag.
- **Calibration:** the same inputs/shapes, with an independently drawn M0 Gaussian
  outcome for each card. M0 should average approximately 1 here. Historical
  outcomes need not follow the M0 model and need not average 1.
- **Practice evaluation:** exact sibling-panel row lookup at explicit dates/months
  or, when dates are sealed, inferred `asof + BDay(horizon)` dates. It never
  interpolates missing target rows. Cumulative factor targets sum `log1p` of future
  simple returns through the target date. Latest available sibling vintage wins.
  These are **local proxy labels**, not certified sealed answers. Use
  `ARGS=--strict-dates` to refuse date inference. Unresolvable units are listed
  before establishing the evaluation roster; forecast failures within the roster
  always count as 8.0. Comparisons must use the same roster.
- The default return-step implementation follows the M0 document literally; the
  current reference CLI applies `log1p` first. The Sahm monthly mapping also differs
  from the older table in M0's document. Both are recorded in BUILD_LOG.

The forecaster interface is:

```python
forecast(card, panels: dict[str, DataFrame], text_dir: Path | None,
         asof: str, n_draws: int, seed: int | None) -> DataFrame
```

`card` is the parsed TOML dictionary with optional `card['forecast_spec']`.
Panels are keyed by filenames, preserving M0's sorted-file precedence. Returned
frames contain `draw:int32`, `asset:str`, `horizon:int32`, `value:float64`; each draw
spans the complete asset/horizon grid. Set `frame.attrs['rationale']` to the
derivation, or pass a rationale explicitly to `write_forecast`. M0 works with
`text_dir=None`. A future forecaster can be selected with
`FORECASTER=my_package.module:forecast` without modifying the scorer.

M0 defaults to 500 draws and CRC32(unit_id); explicit `--seed` or `QFBENCH_SEED`
overrides it. The reference wrapper defaults to seed 0 and forwards the environment
seed explicitly. Generated outcomes and dataset sampling use separate RNG streams.

For the submission command:

```sh
.venv/bin/python -m t2agent.cli --panels /input/panels --text /input/text \
  --asof YYYY-MM-DD --out /output/forecast.parquet
```

The image exposes this as `forecast` on PATH. Its context is allowlisted to runtime
source and dependencies. It contains no vendor tree, evaluation package, panels,
realized values, practice unit IDs or lookup tables.
