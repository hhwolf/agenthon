# Final alignment: retain the verified release

**Model changes: NO-GO. Compatibility repair: GO as an opt-in code change. Selected release replacement: NO-GO.**

The fixed 50/50 recent/EWMA variance blend passed every development gate, then failed the
predeclared confirmation gate. No runner-up, combined arm, parameter change, or further tail
experiment was tried. Keep the selected numeric_v1.1 + card-notes λ=0.5 image, House disabled,
`models=[]`, MIT:

`ghcr.io/hhwolf/agenthon-numeric-v1@sha256:400fe71078d8f9e3e7859da3402ec7866a531760c14b1c0bc795e8e71db0d674`

**Evidence limitation:** the selection/configs were frozen, but review found that the
wrapper source hash changed before confirmation. The exact development wrapper was not
retained, so the confirmation is not certified as source-frozen. The stricter guard now
rejects this situation before answer access. This independently rules out model promotion;
the original evidence is preserved and no confirmation rerun is made.

Its fallback digests, release descriptors, runtime dependency pins and frozen numeric/text
configs are unchanged; hashes are in [protected-files.json](protected-files.json). PR #8 was
not modified. Nothing was packed or uploaded; no Team Key was accessed. This branch is based
on main `a8fe4df`, isolated from the existing `hhwolf/f4-tails-experiment` worktree.

## Current organizer contract

The evaluation checkout is pinned to **3b51e16b3f7c0fa0e56bcba323c2bb5e81b8bd56**, verified as
upstream HEAD on October 21. It is the same revision named in the improvement prompt; no
subsequent upstream change was present when fetched. The separate environment uses
qfbench2-common **2.6.1**, Track 2 **3.1.0**. Release evaluation remains on common **2.6.0** and
Track 2 source **b9c663d239a0e6b86ebd3f3f2d5aead88516067d**.

| Earlier assumption | Verified correction |
|---|---|
| Long-horizon historical/proxy results approximate the ranked Final | Ranked UST/FX inputs use October 26 data; target dates October 27–30, **1–4 business days**. Monthly cards target the next official release in that window; cards without a release by October 30 are dropped. |
| 104 supplied input directories | **126 = original 103 + new 22 short-horizon cards + exemplar**. Discovery is dynamic. |
| Existing UST/FX assets and sources suffice | Added UST 3M/6M/1Y and EM MXN/BRL/ZAR/KRW/INR are present. Final FX uses **ECB reference-rate crosses**. |
| All short-horizon FX practice uses the Final source | The three G10 confirmation cards use **Fed H.10**; the eleven EM cards use **ECB-derived currency/USD crosses**. No claim that H.10 validates ECB G10 fixing behavior. |
| One Final upload | **Up to two**, at most **one per UTC day**; the later upload replaces the first. |
| A check-run status is accuracy feedback | Check runs are **unranked operational checks**. Ranked runs follow the close, with results expected in early November and no provisional standings. |

Sources: [participant guide](https://github.com/Agenthon-2026/track2-forecasting-public/blob/3b51e16b3f7c0fa0e56bcba323c2bb5e81b8bd56/README.md),
[submission contract](https://github.com/Agenthon-2026/track2-forecasting-public/blob/3b51e16b3f7c0fa0e56bcba323c2bb5e81b8bd56/SUBMISSION_CLI.md),
[answer provenance](https://github.com/Agenthon-2026/track2-forecasting-public/blob/3b51e16b3f7c0fa0e56bcba323c2bb5e81b8bd56/practice-answers/README.md),
[M0 specification](https://github.com/Agenthon-2026/track2-forecasting-public/blob/3b51e16b3f7c0fa0e56bcba323c2bb5e81b8bd56/docs/M0-BASELINE.md),
[monthly mapping](https://github.com/Agenthon-2026/track2-forecasting-public/blob/3b51e16b3f7c0fa0e56bcba323c2bb5e81b8bd56/docs/MONTHLY-HORIZONS.md).

The human upload target remains October 23; this improvement pass's deadline is October 23
12:00 America/New_York. The organizer close is October 25 23:59 AoE (October 26 11:59 UTC).
No actual upload record is available here: **remaining attempts are unknown**, not assumed to
be two. The corrected [human checklist](../release/UPLOAD_CHECKLIST.md) requires checking the
team's actual CodaBench history.

## Compatibility audit and repair

The exact published image passed **126/126** current cards offline. Mean wall time was
**1.87670 s**, maximum **9.44848 s**, maximum output **424,845 bytes**, and House requests **0**.
That was a warm-cache run. A separate anonymous cold pull into a disposable Docker daemon
with **zero initial images** took **8.02020 s**; no user image or builder cache was pruned.
Amortizing that separately measured pull over the 126-card run gives **1.94035 s/unit**;
this is a combined estimate, not an end-to-end cold inference measurement.

Every card used the intended **numeric_v1.1/FHS5** path: **0 numeric fallbacks, 0 internal
Student-t FHS fallbacks, 0 text-hook failures**, and no identity-correlation fallback. FHS
had 108–6,224 usable residual rows. At 1–4 days it uses the corresponding remainder block;
longer horizons retain a shared earlier path plus independent continuation. All audited
covariance matrices were positive definite. Added assets work through panel membership,
without a per-unit lookup or asset-specific answer path.

Daily target histories end at their cutoff, with no duplicate observations. Rates are
percentage points per annum; FX quote direction follows each card (for example EUR is
USD/EUR while INR is INR/USD); joint mixed units are retained. The shortest new EM history
has 154 observations and still has enough filtered residuals. Monthly histories can lag the
cutoff by up to 72 calendar days: this is reported separately from a daily stale-input fault.
Named observation periods anchor to the last available observation month. Monthly vintage
correctness remains **uncertified**; the union exposes 1,045 conflicting macro keys, and no
macro model experiment or synthetic macro claim is made here.

A concrete contract discrepancy is repaired behind `--forecaster numeric_alignment`:
M0 §3.7 uses a ratio **strictly greater than 2** for its target-date horizon override. The
release uses `>=2`. A declared horizon 2 with counted spacing 4 therefore becomes 4 in the
release and stays 2 in the corrected profile. Reverse ratio 2 is also tested; ratio >2
behavior is preserved. Strict interpretation propagates through M0 and wide-random-walk
fallbacks. Config-load errors still reach the never-fail wrapper.

**None of the 126 supplied cards hits this exact boundary.** Their host compatibility
forecasts and rationales are identical to the default release path, and deterministic
reruns match. The largest host ARM64 versus published amd64 sample difference is
6.44e-13. The repair passes its correctness gate; it provides no demonstrated score gain
on this supplied roster and is not a reason to replace the selected release automatically.

The mock harness now records the selected units' upstream revision and projects the clock
using the dynamically selected count, retaining the old `projection_104_seconds` field for
backward compatibility. Standalone non-Git input trees report a null revision rather than
failing after inference. The initial published audit ran before this reporting fix: its
summary incorrectly names the old vendor revision/104 projection. Per-unit input hashes
and the corrected audit preserve the actual current checkout provenance.

Evidence: [per-card paths](evidence/audit-cards.csv), [per-asset input inventory](evidence/audit-assets.csv),
[audit summary](evidence/audit-summary.json), [cold pull](selected-cold-pull.json).

## Frozen evaluation and baseline reproduction

[PLAN.md](PLAN.md) was committed as **7a0e891** before reading a new official answer.
The old 88-proxy roster, 2,000 draws and per-card CRC32 seeds reproduce
**2.3781408196192846**, versus the recorded **2.3781408196192855**, with **9 caps** and no
fallbacks. This is the identical historical regression reference, not a new headline metric.
Old/current scorer paths produce identical single-cell, two-cell and eight-cell fixture
results. The adapter also matches the official CLI on single and joint fixtures. All model
comparisons call official scoring math and divide by **input-only M0 expected component
errors**, never M0's realized loss. Weights are 0.5/0.3/0.2, or 5/7,0,2/7 for one cell, capped
at 8. [Cross-check](scorer-crosscheck.json).

The fixed roster contains **1,158** short-horizon historical pseudo-cards: **738 development
(2011–2018)** and **420 report-only (2019–2024)**. There are 1,113 regular first-Monday cases
and **45 real-note episode cases** retaining their original as-of and card metadata/prose.
UST bills, other UST, Fed H.10 G10 and ECB EM sources stay separate. Donor conflicts are zero
in these three daily panels. EM history ends March 2021; coverage is not manufactured beyond
that point. Each forecast sees only rows at or before its cutoff. Outcomes require exact
business-day target observations; no interpolation or G10-for-EM substitution occurs.

There are 245 omissions: **201 missing exact targets**, **43 reserved confirmation-window
overlaps**, and **1 year-boundary purge**. The 22 official target windows were identified
from input card metadata before answer access and excluded across all assets.
Previously inspected historical events and old proxy outcomes limit independence; this is
not described as untouched research.

All arms use **2,000 draws**, common seeds **1111, 2222, 3333**. Primary means average seeds
within each card. Paired 95% intervals use **10,000 shared ISO-week block bootstrap draws**,
seed 20261021, keeping cards/assets/seeds from an episode together. Coverage is cell-weighted;
score summaries are card-weighted. CSVs include groups, years, shapes, cohorts, seeds,
components, horizons, caps, failures, fallbacks and runtime. Each run's identity includes
code/config hashes, input/reference hashes, complete roster, toolkit/upstream versions,
draws and seeds. These are measured-source snapshots, not claims that later reporting-only
edits were present during an earlier run.

Review also hardened environment-independent seeds/text policy, per-card failure gates, exact
seed rosters, input-source revision labels, and frozen-evidence validation before confirmation.
The original runs had the declared environment and complete rosters; stored scores and the
NO-GO decision remain unchanged. This does not certify an unchanged source implementation. Unexpected evaluation errors abort the comparison instead of silently
dropping cases. Failure-gate counterexamples are exercised in tests, not claimed as live failures.

Two development starts were discarded before inspecting model comparisons: generated regular
cards still inherited a harmless but wrong UST template description; a first correction
attempt used a system Python without tomllib. Generic metadata was corrected and the full
comparison restarted with unchanged cards/outcomes/candidates. Partial checkpoints retain
2,100 and 1,200 arm/seed rows; final development has 13,896. Including reference/regression
and confirmation runs, plus the final 88-card reference recheck, gives 18,362 retained scored
rows. Including failed-start and bounded unflushed work remains below 19,100 and the 24,000 budget. No extra arm, seed, parameter, or score-driven roster change was introduced.

## Three ablations and confirmation

Caps below are per-seed counts in seed order 1111/2222/3333. There were no runtime failures
or numeric fallbacks in any completed comparison.

| Arm | Development mean | Difference vs release (95% week CI) | Development caps | 2019–2024 report-only mean | Report-only caps |
|---|---:|---:|---|---:|---|
| Unchanged release | 1.124426 | — | 4 / 4 / 4 | 1.335766 | 8 / 8 / 9 |
| A: zero short drift | 1.126243 | +0.001817 [−0.000120, +0.003855] | 4 / 4 / 4 | 1.339677 | 8 / 8 / 8 |
| B: fixed 50/50 recent + lagged EWMA20 variance | **1.097721** | **−0.026705 [−0.036770, −0.016622]** | 4 / 4 / 4 | 1.286169 | 9 / 8 / 8 |
| C: remove short card-notes overlay | 1.124280 | −0.000146 [−0.000335, −0.000018] | 4 / 4 / 4 | 1.336453 | 8 / 8 / 8 |

A fails the mean and uncertainty gates. C is exactly identical on generic regular cards;
it improves real-note development episodes from 1.189760 to 1.184864 but misses the overall
1% improvement gate. It was retained as the single predeclared ablation because that
historical-note cohort is nonidentical.

B improves development by **2.37497%**, clears every seed's mean/cap gate, and improves after
removing its most helpful week (2014-W49): difference **−0.025093**. All four development
groups meet the ≥40-card/≥12-week representation threshold:

| Development group | Release | B |
|---|---:|---:|
| UST bills | 1.212452 | 1.190537 |
| Other UST | 1.079523 | 1.069508 |
| Fed H.10 G10 | 1.216745 | 1.169954 |
| ECB EM | 0.990078 | 0.962410 |

B's selection and parameter choice were frozen at commit **dc223e2**, selection SHA-256
`55412ac57103f2332519afcc4016f13828f6b7e82a4d82fdc1239d4ecbb1882c`.
First official-answer access was logged at **2026-10-21 18:12:37 UTC**, after that commit.
Only **M0, unchanged release and B** were evaluated on the 22 official cards.

A later guard audit found a source mismatch between the development and confirmation
identities: `t2agent/numeric_alignment.py` changed from `48d50743…` to `d14c6717…`.
Configs, dependency versions and official scorer match. The confirmation wrapper was
recovered and hash-verified from a review log; the exact development wrapper is not retained,
so its change cannot be certified harmless. Evaluation-helper source hashes also changed.
The original comparison would fail the new live-implementation guard. Treat the table below
as the recorded comparison, **not a certified source-frozen confirmation**. No promotion or
rerun follows from this audit. [Exact hashes and roster audit](guard-audit.json).

| Official 22-card confirmation | Mean | Caps (each seed) | 90% coverage | 98% coverage |
|---|---:|---|---:|---:|
| M0 | 1.139913 | 0 / 0 / 0 | 88.68% | 100% |
| Unchanged release | **1.096704** | 0 / 0 / 0 | 88.68% | 100% |
| Selected B | 1.115096 | 0 / 0 / 0 | 92.45% | 100% |

B's paired difference is **+0.018391** (95% week CI **[−0.039605, +0.088300]**), a **1.67696%**
mean regression. The confirmation gate fails regardless of the wide interval. Group counts
are sparse (7 bills, 1 mixed UST, 3 G10, 11 EM); do not infer group confidence from these means:

| Confirmation group | Release | B |
|---|---:|---:|
| UST bills | 1.049344 | 1.058148 |
| Mixed UST | 0.992532 | 0.987354 |
| Fed H.10 G10 | 1.564266 | 1.577925 |
| ECB EM | 1.008796 | 1.036721 |

Counterexamples matter: BRL `t2-F4-fx-brl-019-ps1` worsens **2.814385 → 3.307016**;
UST1Y `t2-F1-curve-ust1y-001-ps1` worsens **1.622869 → 1.992075**. Improvements include
UST3M `t2-F1-curve-ust3m-002-ps1` **1.413897 → 1.215862** and ZAR
`t2-F1-fx-zar-009-ps1` **1.317906 → 1.128184**. This mixed confirmation evidence supports NO-GO.

The old 88 proxies at the three explicit seeds have mean **2.388046**, **9 caps per seed**,
and identical scores for release, B and the compatibility profile (the old eligible daily
cards are outside the short-horizon scope). Do not confuse that seed-average with the
CRC32 reference **2.378141**. Both old-roster comparisons use input cards from the old
`b9c663d` checkout. The three-seed run uses the current `3b51e16` scorer/normalization; its
original identity labels this evaluation checkout `upstream_commit`, not the input source.
The exported final reference recheck explicitly records the separate input Git revision and
reproduces the reference mean again. The report-only 2019–2024 cohort never selected or vetoed a model.

## Implemented changes and release boundary

- Opt-in strict horizon-ratio interpretation, including both fallback levels; release defaults unchanged.
- Explicit research A/B/C routes and fixed lagged EWMA variance calculation, retained for reproduction;
  none is selected by the runtime CLI. `numeric_alignment` selects only the compatibility repair.
- Isolated current-upstream setup, source-separated historical construction, official normalized scoring,
  fixed selection/confirmation gates, hash identities, and compact comparison evidence.
- Dynamic mock-Final provenance/count and safe reporting for non-Git unit trees.
- Updated human upload guidance, with unknown remaining quota and operational-check semantics.

The local amd64 candidate has its own tag/immutable image ID in [local-image.json](local-image.json).
It is **not published**, has no replacement submission descriptor, and cannot replace the selected
release without a separate release decision. Its mock-Final matrix is recorded in
[CONTAINER_CHECKS.md](CONTAINER_CHECKS.md). A future publication would need a separate candidate
CI tag/digest, anonymous pull, complete digest verification and matching candidate descriptor;
never repoint existing tags or reuse the selected descriptor for different bytes.

**Verification:** the complete release environment passes **279 tests** (15 existing NumPy
matmul warnings), and the current environment passes all **35 alignment tests**. The final
local amd64 image passes **126/126 in each of four modes**, with identical output triplets,
zero requests, mean wall time 1.93–2.10 s and maximum 2.839 s. Runtime hashes match the tested
image. All ten protected files match both their recorded hashes and `origin/main`.

Tests cover strict/reverse horizon boundaries, both forced numeric fallbacks, config-load failure,
lagged variance and joint PSD/marginals, unaffected outputs, deterministic short FHS paths, future-row
exclusion, source isolation, reserved-window exclusion, official normalization, exact seed rosters,
per-card failure/fallback gates, major-group and cap gates, immutable selection and one-shot confirmation. Selection additionally requires the exact
declared development roster; confirmation checks the live model/evaluation sources, JSON
configs, library versions and scorer fingerprint against the development identity before
any answer access. Tests reject complete-card partial checkpoints and implementation drift.
Two old CLI tests intentionally reject common 2.6.1; the complete release-env suite runs under 2.6.0,
while the new alignment/current-scorer tests run separately under 2.6.1. No dependency guard was weakened.

Independent code reviews identified the strict fallback propagation bug and evaluation
provenance/guard weaknesses; these were corrected and regression-tested. One cosmetic
observation remains: when initial preparation fails, the compatibility profile annotation
may be absent from the rationale, although the fallback method/reason and strict numerical
mapping remain correct. This does not affect emitted samples or the promotion decision.

Changed runtime files are `t2agent/{cli,m0,numeric_v1,numeric_v1_1,numeric_alignment}.py`.
Evaluation changes are `t2eval/{cli,official,mock_final,final_alignment,alignment_selection,
alignment_audit}.py`; tests are `tests/test_{final_alignment,alignment_review}.py`. Setup,
scorer-fixture, cold-pull, matrix-verification and evidence-export scripts, a separate CI
workflow, and the reports/checklist complete the review package. Frozen release files are
listed separately in `protected-files.json` and remain unchanged.

For the human submission: review this PR without merging or changing the chosen image during this task;
retain the selected digest unless separately authorizing a new verified release. Check actual upload
history and the latest organizer notices, then follow the human-only checklist. Keep selected and
fallback images public until results. No local score estimates leaderboard placement.

## Reproduction and evidence

See [REPRODUCE.md](REPRODUCE.md) for commands. [evidence/](evidence/) contains deterministic gzip
CSV/JSON files, plain summary tables and a SHA-256 manifest. It excludes raw panels and answer values.
Use `pandas.read_csv('...csv.gz')` or `gzip -dc` to inspect every card/seed/component/horizon result.
The historical data are regenerated from pinned input panels; old proxies restore from the existing
published evaluation snapshot. Answers, caches, vendor trees and reports remain excluded from the
inference image by the unchanged Docker allowlist.
