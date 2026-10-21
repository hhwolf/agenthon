# F4 tail experiment — results

Pre-registration: [PLAN.md](PLAN.md) (commit `42ce8bb`).

| candidate | CV F4 (328) | Δ CV F4 [95% CI] | held-out F4 (report-only) | practice F4 (28) | practice overall (88) | Δ practice [95% CI] | caps | worst group | non-F4 identical | gates 1-5 |
|---|---:|---|---:|---:|---:|---|---:|---|---|---|
| current final | 0.961435 | — | 1.169006 | 4.459123 | 2.378141 | — | 9 | — | — | — |
| t5 | 0.959481 | -0.001954 [-0.0160, +0.0126] | 1.175964 | 4.521720 | 2.398058 | +0.019917 [-0.0117, +0.0443] | 8 | panel=factors_daily +1.5% | hist yes, practice 60/60 | ✘✔✔✔✔ |
| t4 | 0.957627 | -0.003808 [-0.0202, +0.0139] | 1.178446 | 4.576086 | 2.415356 | +0.037215 [+0.0074, +0.0658] | 8 | panel=factors_daily +3.0% | hist yes, practice 60/60 | ✘✔✔✔✔ |
| mix10 | 0.956612 | -0.004823 [-0.0180, +0.0095] | 1.176819 | 4.537206 | 2.402986 | +0.024845 [+0.0006, +0.0475] | 8 | family=T2-F4 +1.8% | hist yes, practice 60/60 | ✘✔✔✔✔ |

**Decision: NO-GO** — no candidate passed all five gates; keep the current final.

## Reading (diagnostic only; it changes no decision)

- Every candidate fails gate 1 in the wrong direction: the practice mean *rises* by +0.020 (t5), +0.037 (t4)
  and +0.025 (mix10). The t4 and mix10 year-block CIs exclude zero. Gates 2–5 pass for all three.
- Caps fall from 9 to 8 in all three, always the same card: `t2-F4-mkt-debt-ceiling-2011` (unclipped 8.30 →
  7.66 / 7.99 / 7.79). Of the 28 F4 proxies, 5 improve and 15 worsen under each candidate. Mean normalized
  component changes on F4 are tail penalty +0.44 / +0.58 / +0.16, CRPS +0.06 / +0.10 / +0.05 and variogram
  +0.04 / +0.06 / +0.03. Replacing the empirical FHS shocks with a parametric scale mixture at equal variance
  narrows the 5%/95% quantiles and sharpens the centre more than it helps the far tail. This matches the
  pre-registered prediction.
- CV F4 improves slightly for all three (−0.002 to −0.005; every CI includes zero). Held-out F4 (report-only)
  is slightly worse for all three (1.169 → 1.176–1.178).
- Non-F4 outputs are byte-identical: all 1,440 non-F4 historical scores and all 60 non-F4 practice triplets.

**Outcome: NO-GO. The current final `sha256:400fe710…0d674` remains the submission.** No runtime code,
config, image, tag or descriptor changed.

Reproduce: `.context/f4/run.sh` equivalent, six runs of
`.venv/bin/python -m t2eval.cli {backtest,eval-practice} --forecaster t2eval.f4_tails:forecast_{t5,t4,mix10} --n-draws 2000 --work W`
(with W sharing the audit union/practice/synthetic data), then `.venv/bin/python reports/f4_tails/evaluate.py --work W`.
