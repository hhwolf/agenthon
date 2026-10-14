"""Render tracked Phase 2 evidence into a readable report (no new fitting)."""
from pathlib import Path
import json
import pandas as pd


def main():
    out=Path('reports/phase2')
    result=json.loads((out/'final-evaluation.json').read_text())
    ablations=json.loads((out/'ablations.json').read_text())
    practice=json.loads(Path('.eval/runs/eval-practice-numeric_v1-743299aa1923/summary.json').read_text())
    lines=['''# Agenthon Track 2 — Phase 2 results

Measured October 14, 2026 · 2,000 draws · Lower scores are better

## Verdict

The frozen numeric_v1 improves the development CV and reserved-year means, and
passes all 104 admissibility checks. **The paired capped-card reduction target
is unmet.** It ties M0's total cap count and increases caps in 2019–2024.
The final mean improvement is small relative to year-to-year uncertainty, so
these results do not establish a robust improvement in the sealed final window.
No candidate was tuned after revealing reserved-year or practice results.

## Main results

| Evaluation | Cards | M0 mean | Numeric mean | M0 caps | Numeric caps | Numeric median |
|---|---:|---:|---:|---:|---:|---:|
''']
    for label,a,b in [('Primary year CV: 2009–2018',result['primary_m0'],result['primary_cv']),
                      ('Reserved: 2019–2024',result['holdout_m0'],result['holdout']),
                      ('All historical, descriptive',result['all_m0'],result['all_frozen'])]:
        lines.append(f"| {label} | {a['cards']} | {a['mean']:.6f} | {b['mean']:.6f} | {a['capped']} | {b['capped']} | {b['median']:.6f} |\n")
    lines.append(f"| Practice proxies, report only | 88 | 2.551735* | {practice['mean']:.6f} | 11* | {practice['clipped']} | {practice['median']:.6f} |\n")
    lines.append('''
*Practice M0 is the original 500-draw measurement; all historical paired rows
recompute M0 at 2,000 draws. Original historical M0 was 1.214629 with 24 caps;
its 2,000-draw control is 1.210785 with 23. Comparing 23 numeric caps against
24 original M0 caps would confound model and Monte Carlo changes.

Reserved-year wins: **4 of 6**. The equal-year mean paired delta is **−0.034823**,
with year-cluster standard error **0.050554** (only six years). This uncertainty
includes zero improvement. The primary CV winner was selected using the same
development CV scores, so its CV result may be optimistic.

## Validation protocol

Step 1 diagnosis was written to BUILD_LOG before Step 2; the protocol was
recorded before any candidate score. Development uses 2005–2018, with 2005–2008
warm-up labels and one primary test fold for each year 2009–2018 (1,073 cards).
Fixed rules estimate moments only from each card's pre-cutoff history. The only
outcome-fitted parameter is global width; each fold fits it on earlier years,
purging cards whose targets cross the test-year boundary. The final rule was
frozen before scoring 2019–2024 (554 cards), then practice proxies.

M0 outcomes across all years were inspected in the required diagnosis, so the
reserved period is a candidate holdout, not a completely untouched dataset.
Practice uses 85 inferred dates and 3 explicit monthly targets. Latest-vintage
macro unions, G10 substitutions for EM shapes, and business-day calendars remain
limitations. No sealed outcomes or organizer feedback were used.

## Ordered ablations

Each row is compared with the previous accepted best, identified in the detailed
JSON. Accept only a lower primary mean, no increase in caps, and no >10% loss in
a major family/panel/horizon/shape group. Major means at least 40 cards, or 20
for monthly macro. Every candidate and its full breakdowns are retained.

| Candidate | CV mean | Median | Caps | Change in mean | Decision |
|---|---:|---:|---:|---:|---|
''')
    breakdown=[]
    for row in ablations:
        reason='Kept' if row['accepted'] else '; '.join(row.get('reasons',[])) or 'Other eligible candidate preferred'
        if row['name']=='m0_2000':reason='Control'
        lines.append(f"| {row['name']} | {row['mean']:.6f} | {row['median']:.6f} | {row['capped']} | {row.get('delta',0):+.6f} | {reason} |\n")
        for dimension,groups in row['breakdowns'].items():
            for group in groups:breakdown.append({'candidate':row['name'],'previous':row['previous'],'dimension':dimension,**group})
    pd.DataFrame(breakdown).to_csv(out/'ablation-breakdowns.csv',index=False)
    lines.append('''
The kept rules are 25% trailing drift, monthly positive-index log trend over
12 changes with UNRATE persistence, and 20% correlation shrinkage using up to
1,260 aligned changes. Each draw shares multivariate shocks across assets;
later horizons add independent continuation. Volatility remains the original
300-observation estimate, tails remain Gaussian, and width remains 1.0.

Zero drift improved the aggregate but hurt monthly macro beyond the limit.
The EWMA and high-volatility alternatives reduced development caps but worsened
mean score. Longer-history variance made quiet-period distributions too broad.
Rate reversion and empirical variance ratios also failed the mean gate. The
joint-stage gain is only 0.000428 and should not be treated as independently
statistically established. All tuning menus were fixed in advance.

## Reserved-year breakdowns

| Group | Cards | M0 mean | Numeric mean | M0 caps | Numeric caps |
|---|---:|---:|---:|---:|---:|
''')
    for dimension in ['family','panel','horizon_bucket','shape','year']:
        baseline={x['group']:x for x in result['holdout_m0_breakdowns'][dimension]}
        for r in result['holdout_breakdowns'][dimension]:
            b=baseline[r['group']]
            lines.append(f"| {dimension}: {r['group']} | {r['cards']} | {b['mean']:.4f} | {r['mean']:.4f} | {b['capped']} | {r['capped']} |\n")
    lines.append('''
## M0 diagnosis before tuning

Nominal 90% and 98% intervals cover **85.13% and 94.09%** of 5,260 cells.
Mean z is +0.0193, median +0.0030, RMS 1.3825. Opposing regime errors cancel in
the signed average. Long rates and monthly macro are the weakest calibration
areas; uniformly doubling width worsens mean score from 1.2146 to 1.5013.

Hindsight center/width experiments allocate 0.7103 of score reduction to center
and 0.2572 to width, leaving 0.2471 at the chosen oracle widths. These are
postmortem oracle diagnostics, not deployable predictions or irreducible risk.
Zero drift alone scores 1.1825 overall but hurts monthly macro.

The original 24 capped cards comprise 15 provisional regime breaks, five
monthly/vintage issues, three volatility spikes, and one drift extrapolation.
No bug was demonstrated. Repeated UST_2Y cards in late 2021 are overlapping
examples of the same quiet-to-moving transition. "Monthly/vintage" flags the
known data limitation; it does not prove revisions caused the error.

Full capped-card inventory, all panel × horizon coverage, and methodology are
in [DIAGNOSIS.md](DIAGNOSIS.md). The CSV files retain all values and PIT bins.

![M0 PIT histograms by panel and horizon](m0-pit-histograms.png)

## Operational checks

- 52 tests pass, including neutral-hook byte identity, seed determinism,
  future-data exclusion, independent continuation, monthly mapping, and both
  fallback levels. Existing macOS NumPy BLAS warnings remain finite-output
  warnings in baseline tests; numeric_v1 uses explicit NumPy contractions.
- 104/104 official admissibility passes at 2,000 draws, maximum host forecast
  time 0.066 seconds in the recorded sweep. Historical maximum is 0.094 seconds.
- Full official CLI scoring of 2,060 numeric forecasts agrees with the fast
  ablation adapter within 8.9e-16. Zero inference failures.
- linux/amd64 build and offline docker-smoke pass g0–g3 with read-only root,
  no network, and a small non-executable temporary filesystem.
- The image contains only runtime code and numerical dependencies. The build
  allowlist excludes evaluation data, vendor code, reports and realized values.
- No competition pack or submission upload command was run.

''')
    pub=out/'publication.json'
    if pub.exists():
        data=json.loads(pub.read_text())
        lines.append('## Image publication\n\n'+data['report']+'\n\n')
    else:lines.append('## Image publication\n\nGHCR publication and anonymous-pull verification are pending.\n\n')
    lines.append('''## Artifacts and reproduction

See [VALIDATION.md](VALIDATION.md), [ablations.json](ablations.json),
[ablation-breakdowns.csv](ablation-breakdowns.csv),
[frozen-selection.json](frozen-selection.json), and
[final-evaluation.json](final-evaluation.json). Per-card candidate CSV files
include every development/warm-up card; primary means filter 2009–2018.
The [numeric engine guide](../../docs/NUMERIC_V1.md) gives commands and the
optional text-signal contract. BUILD_LOG contains the chronological audit.

Status: the numeric engine and evaluation are implemented. The requested
accuracy gate remains open because capped-card count did not improve on the
paired historical comparison and increased in the reserved period.
''')
    (out/'RESULTS.md').write_text(''.join(lines))


if __name__=='__main__':main()
