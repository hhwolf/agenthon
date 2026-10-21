# Final alignment — predeclared protocol

2026-10-21; commit this file before any new-answer read or experiment score.
Deadline: 2026-10-23 12:00 America/New_York. After that time, report results as
separate research; no candidate release recommendation for this submission.

## Protected release and scope

Base: origin/main a8fe4df. Existing branch/worktree stays unchanged. Preserve
all release descriptors, frozen configs, published tags and fallback images.
Selected release: ghcr.io/hhwolf/agenthon-numeric-v1@sha256:400fe71078d8f9e3e7859da3402ec7866a531760c14b1c0bc795e8e71db0d674.
House stays disabled. PR #8 is neither modified nor merged. No packing, upload,
Team Key access, or broad Docker pruning. Any justified candidate gets an
explicit opt-in configuration and its own reviewable PR; never merge or replace
the selected release in this task.

Upstream evaluation checkout: 3b51e16b3f7c0fa0e56bcba323c2bb5e81b8bd56
(HEAD verified 2026-10-21; same as the supplied prompt). Separate environment:
qfbench2-common 2.6.1 and this pinned current Track 2 package. Release environment
remains on 2.6.0 / b9c663d239a0e6b86ebd3f3f2d5aead88516067d.
Read-only audit has inspected README, SUBMISSION_CLI, MONTHLY-HORIZONS,
M0-BASELINE, practice-answers/README and input cards/panels, but **no answer
parquet or answer value**. The repository contains 126 input directories,
including 22 -ps1 cards and the exemplar. Earlier historical episodes and 88
proxy outcomes were already examined in prior work; the failed F4 experiment
at b992553 is known. Input histories may overlap official-answer events. The
22 are a reserved confirmation comparison, not a claim of untouched research.

## Audit and separate correctness gate

Reproduce 2.3781408196192855 (88 old proxies, release per-card CRC32 seed,
2,000 draws) using the unchanged release path and identical original inputs.
Investigate any difference; never replace that reference silently. Run the
published digest on all dynamically discovered current units with only each
unit mounted; do not mount practice-answers. Record method/fallback reason,
finite values, output gates, size and timing. Inventory actual target assets,
panels, quote units, cadence, missing/stale rows and monthly mapping. Cross-check
old/current scorers and M0 normalization on common fixtures before comparisons.

An already demonstrated contract discrepancy to test: current M0 §3.7 uses a
strict ratio >2 for horizon override; the release implementation uses >=2.
Reproduce a boundary failure before implementing an opt-in correction. Do not
reinterpret correct quote units or special-case individual unit IDs.
Correctness promotion needs a demonstrated failure, passing regression test,
and explained collateral effects, independently of forecast performance.

## Historical data and splits

Use supplied numeric histories only; no extra data acquisition or model calls.
Keep each panel/source separate: UST Treasury/FRED, G10 Federal Reserve H.10,
and EM ECB-derived USD crosses. Never substitute G10 histories for EM. Do not
claim the Federal Reserve G10 sample validates ECB G10 fixing behavior. No macro
model experiment; monthly vintage validity is uncertified and reported as such.

Construct regular short-horizon pseudo-cards on the first Monday of each month
from 2011 through 2024. Per available group/date create (i) one single asset,
cycled by calendar-month index through sorted group members, horizons 1,2,3,4;
(ii) a joint card for all group members, horizons 1,4. Groups: UST bills
(3M,6M,1Y), other UST (2Y,5Y,10Y,30Y), G10 (EUR,GBP,JPY,CHF), EM
(BRL,INR,KRW,MXN,ZAR). Require at least 300 earlier observations per asset and
exact observations for every business-day target; skip incomplete cases with
reasons. Keep latest-cutoff source data with provenance and report conflicts.
No interpolation, future row in input, source mixing, or manufactured vintage.
Generic generated prose has no crisis/event assertions.

Add an episode cohort from original daily UST/FX cards, retaining their actual
as-of and pre-cutoff card prose and using horizons 1,2,3,4. Use same-source
history for exact outcomes; do not move event descriptions to a different date.
This cohort gives C genuine historical card-note cues without invented shocks.
Exclude all newly constructed cases whose target window overlaps any official
-ps1 target window (as-of+BDay(1) through as-of+BDay(max horizon)), across all
assets. Infer those windows from input card metadata before opening answers.

Development: chronological as-of-year folds 2011–2018; the forecaster is fitted
only from its own cutoff history, no cross-fold learned parameters. Purge any
target window crossing a year boundary. No overlapping target windows between
year folds. Report 2019–2024 separately; previously examined, never selects or
vetoes. Data availability can shorten a group's period; record omissions.
Maximum 2,000 pseudo-cards total and 24,000 card-arm-seed evaluations. Use every
eligible case in deterministic order up to that limit, stratified by year/group
if needed, chosen before scoring. Do not increase budgets after results.

## Exactly three independent ablations

Only daily UST/FX level cards with every target horizon <=4 are eligible.
Preserve all other paths, tails, joint construction and House-disabled policy.
Compare each independently against the unchanged release. Never combine A/B/C.

A: zero drift (from current 0.25 multiplier), same covariance/FHS/text overlay.
B: innovation variance = 0.5 * existing recent variance + 0.5 * lagged EWMA
variance, half-life 20 observations, adjusted unbiased sample variance with
minimum 20 observations, shifted by one observation. Last increment is excluded
from the EWMA estimate. Scale covariance and each joint segment by the same
per-asset factors; retain correlations, drift, FHS residuals, path nesting and
marginal target variances. Assert PSD and target diagonal preservation.
C: disable card-notes widening, same numeric distribution. Do not turn F4 into
an inevitable shock. Generic pseudo-card prose may make C identical there;
report the real-note cohort separately. Omit a genuinely identical ablation.

2,000 draws. Common explicit seeds [1111, 2222, 3333] for each arm/card, including
confirmation. Old reference reproduction additionally uses per-card CRC32.
No further seed, parameter, tail law, monthly model, corpus extraction or fourth
forecasting experiment. A necessary compatibility correction is a separately
reported arm; it is not silently folded into any candidate comparison.

## Metrics, uncertainty and selection

Call official scoring math; normalize components by M0's input-only expected
errors under the current specification, weights 0.5/0.3/0.2 (single-cell 5/7,
0,2/7), score cap 8. Cross-check this against the official normalized adapter.
Report normalized aggregate/components, UST bills/other UST/EM/G10, every
horizon, joint vs single-asset, 90%/98% interval coverage, caps, failures,
fallback counts and runtime. Group scores are per-card averages; horizon/cell
coverage is explicitly cell-weighted. Mixed-group cards have their own label.

Average seeds within each card for primary mean comparisons. Bootstrap paired
card deltas by shared as-of ISO week, keeping all assets/cards/seeds in the same
block (10,000 resamples, bootstrap seed 20261021). Report year folds and
seed-specific results. Adequately represented group = >=40 cards and >=12
weeks in development; smaller groups reported without confidence claims.

Development promotion requires ALL:
- mean improves by >=1% versus unchanged release;
- 95% paired week-block CI of mean difference has upper endpoint <0;
- no adequately represented group >5% worse;
- no new runtime failures or numeric fallbacks;
- capped-card count does not increase for any of the three seeds;
- mean improves for every seed;
- mean still improves after removing the single most helpful shared event week.

Freeze one winner, the lowest development mean (ties within 0.0005 prefer fewer
knobs, then A,C,B), before opening official answers. Record whether it clears
development gates. If none improves, freeze the unchanged release as winner
and report NO-GO; do not search alternatives. Evaluate only M0, unchanged
release, and that frozen winner on the 22 official cards, with the same three
seeds. No post-confirmation tuning or runner-up substitution. To promote, its
confirmation mean must be no worse than release, no new failures/caps, and its
old 88-proxy mean must not regress >5%. Weak/contradictory evidence => NO-GO.

Cache identity includes runtime/evaluation source hashes, config, complete input
and roster hashes, upstream and toolkit/scorer versions, draws and seed. Do not
reuse scores across identities. Answers and generated datasets stay outside
runtime image context. Record the unblinding time and frozen selection hash.

## Delivery / stop boundary

Relevant tests, unaffected-output equality, deterministic reruns, zero House
calls, expanded host admissibility and candidate amd64 mock-Final matrix are
required for accepted runtime changes. Existing selected image/descriptors stay
untouched; a candidate must have separate artifact names. If a candidate is
published, require separate tag/digest, anonymous pull, verification and matching
candidate descriptor. A reviewable PR needs the repository shipping workflow
and Greptile 5/5 on its exact head; record any unavailable check as unavailable.
Deliver RESULTS.md, reproducible CSV/JSON evidence and BUILD_LOG entry with
separate correctness/model GO decisions and pinned source corrections.
No upload record is visible in the repository yet; remaining attempt count is
unknown, not assumed to be two. Human checks actual CodaBench history before
any upload. This task never merges, packs, uploads or replaces the release.
