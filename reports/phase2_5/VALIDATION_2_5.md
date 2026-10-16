# Phase 2.5 validation: precommitted before candidate scoring

Date: 2026-10-15. Baseline: frozen numeric_v1, unchanged. This menu is committed
before any Phase 2.5 scores. Results and the new freeze live in reports/phase2_5/.
The existing evaluation snapshot is preserved, per reports/EVALUATION_DATA.md.

## Data and uncertainty

Use the same 2,060 historical cards and 88 practice proxies, 2,000 draws,
per-unit CRC32 seeds (QFBENCH_SEED honored), and pinned official composite and
M0 normalization. Primary CV is pooled card-weighted mean over as-of years
2009–2018 (1,073 cards); 2005–2008 are descriptive only. Each fixed rule uses
only supplied pre-cutoff observations; no outcome-fitted parameter is added.
Practice proxies now participate in selection by explicit C1 instruction.
They are not an independent validation set. Previously inspected 2019–2024
(554 cards) is report-only except for the precommitted veto below. It must not
rank candidates or motivate new candidates. No sealed outcomes are available.

Report every candidate's CV, practice, held-out and all-historical mean, median,
cap count, yearly and family/panel/horizon-bucket/single-vs-joint breakdowns.
Paired bootstrap: 10,000 resamples of whole as-of years with replacement,
seed 20261015; retain all cards in each sampled year and recompute the pooled
mean difference. Report percentile 95% CIs versus numeric_v1 and the preceding
best, separately by partition. Overlapping cards and reuse for selection limit
inference; these intervals do not correct for model selection. Practice and
historical caps are counted as separate evaluation rows even when overlapping.

## C1 and selection

Compare each alternative with the best entering its stage. Accept only if:
1. CV mean strictly improves, OR CV mean is at most +0.005 worse and the
   combined CV+practice capped count strictly decreases.
2. Practice mean does not worsen (floating tolerance 1e-12).
3. Combined CV+practice capped count does not rise.
4. No major group mean worsens >10%, checked separately in CV and practice.

Major groups follow Phase 2: >=40 cards per family, panel, horizon bucket or
single/joint shape, except macro_monthly >=20. Smaller groups are still reported.
Year cells are reported but are not major groups. The held-out veto rejects any
candidate whose major group worsens >15% versus the entering best OR the frozen
numeric_v1 baseline. No held-out mean or cap ranking influences selection.

Within a stage, all alternatives use the same entering best. Among C1-eligible,
non-vetoed alternatives, select lowest CV mean; candidates within 0.0005 are
ties, settled by fewer changed knobs, then fewer CV+practice caps, then name.
If none qualify retain the entering best. Record eligibility, veto, and final
decision separately. No expansions or repeats of the menu after observing scores.

## Ordered menu

A1 tails (same marginal innovation variance as Gaussian):
- Student t5: Gaussian scale sqrt(3 / chi-square(5)); variance exactly one.
- Mixture: 5% at 3x Gaussian SD, divided throughout by sqrt(1.4).
- Filtered historical simulation: lagged EWMA (half-life 60) standardized
  input changes, common aligned residual rows, fixed block length 5. Resample
  independent overlapping five-change blocks (and partial final block).
  Demean block sums and normalize their theoretical sampling covariance to
  the requested segment covariance, so serial dependence/tails do not silently
  change width. Monthly positive indexes use log residuals. Fewer than 20
  complete aligned residual rows use normalized t5. No residual outcome data.

A2 horizon variance term structure: per-step variance(h) = exp(-h/tau)*recent
+ (1-exp(-h/tau))*long-run variance, tau in {63,126,252}. Recent is existing
300-observation estimate; long-run uses all supplied valid changes. h is model
steps, including monthly mapping. Monthly indexes use log-change variances.
Multiply by h for cumulative variance; ensure nondecreasing variance for joint
independent continuations using the existing monotone envelope.

A3 volatility floor: per-step variance >= f*long-run variance,
f in {0.25,0.5}, on top of the entering best's term structure if retained.

A4 monthly (daily behavior unchanged): log-trend multiplier 0.25 or 0.5
on the existing 12-change trend; OR 36-change trend at multiplier 1;
OR disable dedicated monthly handling, restoring M0-style level changes
with the retained global drift rule. UNRATE persistence remains in log-trend
variants. Publication lag and observation_periods mapping stay unchanged.

A5 one linear pool: 50/50 whole joint draws from the best two structurally
different evaluated variants through A4 (including numeric_v1). Rank solely
by CV mean with the tie rule above; constituents need not individually pass C1.
Structural difference means a different tail law, term-structure rule, floor,
or monthly rule, not only a different numeric setting within the same rule.
Use independent deterministic child seeds and split draws floor(n/2), remainder.
Evaluate the pool against the entering best; never select cells or per-unit winners.

A6 low-priority momentum-sign drift, evaluated once after A5: replace daily
trailing drift by sign of the most recent 126 valid daily changes' sum times
{0.1,0.25} of that cell's forecast SD. Monthly rule unchanged. For a selected
pool apply to both components. Zero available momentum gives zero added drift.

## Freeze and delivery

Freeze selected configuration and source/protocol fingerprints in this directory.
Preserve t2agent/numeric_config.json and reports/phase2/frozen-selection.json.
Ship a separately selectable numeric_v1_1 with identical optional text hook and
numeric -> M0 -> wide-random-walk recovery contract. No text model calls here.
Require tests, official 104/104 admissibility, amd64 offline smoke, CI tag
numeric-v1.1-*, GHCR publication and anonymous pull, and a five-page PDF.
List new/removed capped rows versus numeric_v1 by partition, including all years.
No competition packing or submission upload. Failure to improve must be reported,
not hidden by adjusting the precommitted protocol.
