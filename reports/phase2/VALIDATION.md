# Phase 2 validation protocol — fixed before candidate scoring

Recorded after the M0 diagnosis and before implementing/scoring candidates.

- Dataset: the existing 2,060-card manifest, seed 20261014. No new cards selected
  in response to candidate performance. All input histories stop at card cutoff.
- Development: as-of 2005–2018; 2005–2008 are warm-up years. Primary CV folds
  are each as-of year 2009–2018, pooled with equal weight per held-out card.
  Fixed numeric rules estimate moments only from the card's supplied history;
  they never fit to realized card outcomes. Thus their forecasts are directly
  out-of-year/out-of-outcome predictions. Selecting among those rules using CV
  is model selection, so the CV winner's reported score can be optimistic.
- Any outcome-fitted width multiplier for a held-out year uses only earlier
  as-of years whose last target date precedes January 1 of that held-out year.
  This purges targets crossing fold boundaries. No future-year labels train
  a fold. Final width fitting uses only labels ending before 2019-01-01.
- Reserved final evaluation: 2019–2024, scored for the frozen winner only.
  These outcomes were seen in the requested M0 diagnosis, so this is a candidate
  holdout, not a completely untouched dataset. No candidate adjustment after
  its results are revealed. Also report all 2,060 cards descriptively.
- Secondary: 88 practice proxies, report only after freeze, never select on them.
- Draws: 2,000 and fixed per-unit CRC32 seed (or explicit QFBENCH_SEED).
  Recompute M0 at 2,000 for paired comparisons; retain the original 500-draw
  baseline in reports. Normalize via existing M0 expected-error adapter and
  call the pinned official scorer; do not copy scoring math.
- Ordered ablations versus previous accepted best: (1) drift 0 or 0.25 versus
  trailing 1; (2) EWMA half-life 60 or equal blend of recent 300 and full-history
  variance, then empirical overlapping-horizon variance ratios; (3) Student-t
  df=5 with the same central scale, then 5% high-volatility (3x) mixture;
  (4) rates reversion to trailing 5-year mean, half-life 3 years;
  (5) monthly index log trend over 12 months and UNRATE persistence;
  (6) 1,260-step correlation with 20% shrinkage toward identity, shared shocks
  and independent continuation; (7) one global width in {0.9, 1, 1.1, 1.2},
  fitted separately within each expanding fold. Small fixed menus only.
- Keep a change only if primary held-out mean strictly decreases, cap count
  does not increase, and no major family/panel/horizon/shape group worsens more
  than 10% relative to previous best. Major means >=40 held-out cards, except
  monthly macro >=20. Report smaller groups too; do not silently drop them.
  In a stage with multiple alternatives choose the eligible lowest mean.
- Report every candidate, including rejected ones: mean, median, cap count,
  yearly fold results and all required group breakdowns. Retain per-card scores.
  Report paired year-cluster uncertainty and year wins for the frozen winner;
  overlapping cards are not independent samples.
- Delivery gate: frozen winner beats paired M0 on primary CV and 2019–2024
  means and total cap count, plus 104 admissibility passes. If not, report the
  unmet criterion rather than tune on the reserved years. Runtime fallback
  activations must be recorded separately; no failed card may disappear.
