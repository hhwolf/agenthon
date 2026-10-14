# Phase 0–1 measurement loop

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
