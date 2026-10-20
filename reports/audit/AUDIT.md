# Agenthon Track 2 — independent pre-submission audit

Audit date: **2026-10-16** (Final closes 2026-10-25 23:59 AoE; planned upload 2026-10-23).
Auditor scope: re-run, don't trust. No forecaster code, config or frozen selection was changed; nothing was
packed or uploaded; no held-out or practice result was used to tune anything. Writes: `reports/audit/` and
one dated BUILD_LOG section. Scratch evaluation outputs live in the git-ignored `.context/audit/` so that no
existing `.eval/` run was overwritten.

Audited tree: branch `hhwolf/phase4-text-integration` at `ee31323` (clean), vendor track `b9c663d`,
toolkit `qfbench2-common==2.6.0`.

---

## 1. Verdict

**GO WITH FIXES. Upload the card-notes candidate (numeric_v1.1 + card-notes-only text, λ = 0.5,
`models: []`) once blockers B1–B4 are cleared and the full eight-sweep verification passes on the exact
published digest. Keep public numeric_v1.1 (`sha256:f3ec5167…c085c507`) as the fallback, fully prepared.**

**Do NOT ship the LLM-label text layer.** No cached LLM responses exist anywhere this audit could reach
(this workspace, the five sibling workspaces, every remote branch, Actions artifacts, release assets, and a
filesystem-wide search). Its claimed practice gain (−0.145) cannot be reproduced, was measured against
numeric_v1 with an earlier mapping, and was never compared against numeric_v1.1 with the integrated overlay.

As of today **there is no final artifact to upload**: no final image, no final digest, no `submission.json`,
`reports/phase5/release.json` is `"status": "pending"`, and `t2agent/text_config.json` says
`"provisional"`. The plan's "final (with text)" therefore cannot pass §1 today. The numbers below show the
card-notes candidate is a small, low-risk improvement over numeric_v1.1. Clearing the blockers is mostly
process work (license, review, publishing, verification) and fits before Oct 23.

| Option | Practice mean (88) | Caps | House requests | Status today | Recommendation |
|---|---:|---:|---:|---|---|
| **Card-notes candidate** (v1.1 + card notes λ0.5) | **2.378141** | 9 | 0 | local image only, unpushed branch, no license | **Upload after B1–B4** |
| numeric_v1.1 (public `f3ec5167…`) | 2.415744 | 9 | 0 | published, anonymously pullable, mock-final 4/4 modes pass | **Fallback** (needs B2 + B3 too) |
| LLM labels λ0.5 (teammate report) | 2.2905 (vs v1, unverified) | 7 | ~4.4/unit | cache missing, no integrated comparison | Do not ship |

---

## 2. Blockers, warnings, passes

### Blockers (must fix before upload)

| # | Blocker | Evidence | Fix |
|---|---|---|---|
| B1 | **No final image, digest or descriptor exists.** Nothing ties a `submission.json` digest to a CI digest and a mock-graded digest. | `find . -name submission.json` → none; `git ls-remote --tags origin` → only `numeric-v1-20261014`, `numeric-v1.1-20261015-1`, `v0.1.0.0`; `gh run list` → no `final-*` run; `reports/phase5/release.json` status `pending`; `t2agent/text_config.json` status `provisional`. | Freeze `card_notes_only`/0.5 in `release.json` (runtime SHA256s), push a `final-*` tag, then run `t2eval.final_release` on the exact digest; generate the descriptor from that digest. |
| B2 | **No code license.** The descriptor's `license` is a required SPDX field (`submission.schema.json`: required includes `license`), and `prepare_final.py --check` refuses without a `LICENSE` file. This also blocks the fallback. | `ls LICENSE` → missing; schema `required` list (see §5). | The human picks an SPDX license; add `LICENSE`; record it in `release.json`. |
| B3 | **Grep review gate not met for any PR.** None of the 7 PRs has a grep review, comment or status check; PRs #1–#5 were merged without a grep score of 5. The candidate branch (9 commits: text overlay integration, branch fix, release gates) has **no PR**. | `gh api repos/hhwolf/agenthon/issues/N/comments`, `/pulls/N/reviews`, `/commits/SHA/check-runs` for N = 1…7 → empty (only a GitHub Actions `contract` check on #7). | Push the branch and open a PR to `main`. Get grep = 5 on it **and** on the code already merged into the fallback, or record an explicit exception. Under the team rule, nothing without a 5 may be merged. |
| B4 | **The candidate exists only on this laptop.** `hhwolf/phase4-text-integration` is 9 commits ahead of `origin/main` with no upstream. PRs #6 and #7, whose content it merges, are still open. | `git status -sb` (no upstream); `git ls-remote origin \| grep phase4` → nothing. | Push now (single point of failure), then do B3. |

Blocker for the **LLM-label option only** (not for the recommended upload):

| # | Blocker | Evidence | Fix |
|---|---|---|---|
| B5 | LLM-label replay is impossible: no `.eval/llm_cache/` or `.eval/text_signals/` exists anywhere reachable. The §2 text ablation "numeric-only vs final (with text) by family via replay" **could not be reproduced**. | `find / -type d -name llm_cache` → none; BUILD_LOG Phase 5: "cache itself is still absent". | Ship labels only if the cache arrives by about Oct 19 **and** the integrated v1.1 replay comparison, the eight sweeps with `--uses-house`, and a fresh-seed rerun all pass. Otherwise drop it. |

### Warnings (should fix or consciously accept)

| # | Warning | Evidence |
|---|---|---|
| W1 | **The card-notes gain is partly in-sample.** The B4 v2 lexicon rules were revised *after* reading the practice breakdown (Phase 3, self-disclosed). Phase 4 then selected card-notes on the same 88 practice proxies. The −0.0376 gain (95% year-block CI [−0.0681, −0.0132]) is optimistic for the sealed set. Only 15 of 88 cards change; F1 is slightly worse (+0.0014). | BUILD_LOG Phase 3 "This revision was chosen after seeing the practice breakdown"; `reports/audit/gates.json` → `text`. |
| W2 | **Held-out 2019–2024 is not pristine.** The Phase 2 diagnosis inspected M0 errors over 2005–2024 before the candidate menu was written (self-disclosed). The menu's motivation (vol floor, monthly trend, tails) was informed by 2021–22 failures. No candidate was *ranked* on held-out data. | BUILD_LOG Phase 2 Step 1: "This diagnosis inspected M0 outcomes across 2005–2024". |
| W3 | **Monthly macro mid-2022 regression is NOT fixed.** 2022 macro: M0 0.842 → v1 2.796 → v1.1 2.659 (3.2× M0). Held-out macro overall is still +19.1% vs M0 (1.629 → 1.940), above the 15% veto level if M0 were the reference (the protocol uses v1 as the reference, so the veto is not triggered). The A4 monthly alternatives all failed C1. | `reports/audit/macro-monthly-by-year.csv`. |
| W4 | **Caps were never reduced.** Held-out caps: M0 15 → v1 17 → v1.1 18. All-historical: 23 → 23 → 24. Practice: 9 caps, all F4 shock cards, worth **34% of the practice mean** (mean excluding caps 1.738). Five capped cards are only slightly over (unclipped 8.30–9.85). | `reports/audit/comparison-headline.csv`; practice `cards.csv` unclipped column. |
| W5 | **EM transfer cards are completely unmeasured.** All 3 practice transfer units (`brl`, `inr`, `em-transfer-joint`) have no sibling outcome; the 100 synthetic transfer cards use G10 substitutes. | BUILD_LOG Phase 1 dataset audit; practice roster 88/103. |
| W6 | **The eval harness can silently overwrite runs.** The run-directory identity hash ignores `TEXT_LAYER_MODE`/`TEXT_LAYER_LAMBDA`. `eval-practice --forecaster numeric_v1_1` with and without `TEXT_LAYER_MODE=numeric_only` both resolve to `…numeric_v1_1-99549fcc9541` and overwrite each other. Reproduced in this audit; avoided by using separate `--work` dirs. | `t2eval/cli.py` `metadata` dict omits text env; audit runs `eval-A` vs `eval-N` share id `99549fcc9541`. |
| W7 | **The "cold pull" is not a cold layer download.** The digest was removed locally, but the shared `python:3.13-slim` layers stayed cached, so pull time was 3.67 s. The compressed image is about 140 MB (10 blobs). Real cold pull is expected in seconds to tens of seconds, which is negligible against the clock. | `.context/audit/anonymous-pull-v11.json`; mock summary `pull_seconds`. |
| W8 | **numeric_v1.1 is worse than M0 on some practice groups** that the C1 gate (vs v1) does not check: the 22–63-day bucket (1.960 → 2.141), g10_fx (2.071 → 2.150) and F2 (2.000 → 2.034). Card-notes recovers part of F2 and g10_fx. | `reports/audit/comparison-breakdowns.csv`. |
| W9 | The teammate's dev sweep ran on `integrate.api.nvidia.com`, which may differ from the House route's snapshot. 4/104 units ended in JSON parse failures and 29% had vote agreement below 0.8. That matters only if labels ship. | BUILD_LOG "Dev-model sweep". |

### Passes (re-run in this audit)

| Check | Result | Command / evidence |
|---|---|---|
| Test suite | **241 passed**, 0 failed (15 known NumPy/M0 warnings) | `make test` → `.context/audit/make-test.log` |
| Admissibility, final candidate (host) | **104/104** g0–g3, max forecast 1.563 s (under parallel load) | `make admissibility FORECASTER=numeric_v1_1` (run with `--work .context/audit/eval-A`) |
| Headline reproduction | **All 13 previously reported means reproduce within 5e-7; no number differs by > 0.002.** All reported cap counts match. | §3 table; `reports/audit/comparison-headline.csv` |
| Per-card reproduction | max abs diff ≤ **1.8e-15** vs frozen per-card CSVs (v1, v1.1, M0, final) on all 2,060 + 88 cards | `reports/audit/gates.json` → `reproduction` |
| Dataset reproduction | union input SHA-256 `eaa07cbd…f045cf3a` and 2,060-card synthetic set regenerated identically | `generate` log |
| numeric_v1.1 C1 gate vs v1 | **PASS** on all four criteria, plus the held-out veto | §4 |
| Tail variance normalization | **PASS**: t5 scaled by √(3/χ²₅) (= √(3/5) × t5), mixture ÷ √1.4 | §4 code quote |
| Text decision rule / λ / clamps | **PASS** for card-notes: mean improves, caps 9 → 9, λ = 0.5; aggregate drift 0.000 SD on all 88; vol_mult ∈ {1.000, 1.075, 1.125} ≥ 1 | §4 |
| Protocol before scoring | Phase 2.5 protocol `da26396` 00:52 < first scoring artifact 00:54; Phase 4 protocol `27c4402` 16:38 < `.eval/phase4` dir 16:40 | git log + file mtimes |
| Image hygiene (candidate image built from `ee31323`) | linux/amd64, `USER runner` (uid 1000), no `VOLUME`, `/app` = 27 files / 260 KB, no vendor/.eval/realized/.env/cache, 0 practice unit IDs in `/app` or site-packages | §6 |
| Anonymous pull, fallback digest | manifest + 10 blobs HTTP 200, no credentials; empty-`DOCKER_CONFIG` `docker pull` passes | `.context/audit/anonymous-pull-v11.json` |
| Descriptor dry-run (pinned toolkit, no pack) | parser + JSON schema pass for `models: []` and for the House row | §6 |
| Prompts / House client | as-of stated, post-as-of knowledge forbidden, doc_id citations required, "no tools", temperature 0, top_p 1, seed 20261014, `max_retries=0`, max_tokens ≤ 4000 | §6 |
| Mock Final | see §5 | `reports/audit/mock-final.json` |

---

## 3. Comparison table (re-run, not copied)

2,000 draws for every arm except "M0 (500)" (the original baseline). Seeds are per-card CRC32, official
scorer, M0 expected-error normalization. **Historical cards carry no text directory, so the final candidate
equals numeric_v1.1 on historical cards by construction.** The text layer only acts on practice/Final cards.
"Δrep" is this audit minus the previously reported value; ⚠ would mark |Δ| > 0.002 (none occurred).

| Arm | CV 2009–18 (1,073) mean / median / caps | Held-out 2019–24 (554, report-only) | All historical (2,060) | Practice proxies (88) | Δrep (max abs) |
|---|---|---|---|---|---:|
| M0 (500) | 1.035657 / 0.7396 / 2 | 1.488258 / 0.8783 / 15 | **1.214629** / 0.8057 / 24 | **2.551735** / 1.3254 / 11 | 2.6e-7 |
| M0 (2000) | **1.033389** / 0.7389 / 1 | **1.480838** / 0.8736 / 15 | **1.210785** / 0.8122 / 23 | 2.538247 / 1.3399 / 10 | 4.5e-7 |
| numeric_v1 | **0.953077** / 0.7038 / 1 | **1.456363** / 0.8087 / 17 | **1.154244** / 0.7605 / 23 | **2.435614** / 1.3770 / 9 | 3.2e-7 |
| numeric_v1.1 | **0.951081** / 0.7061 / 1 | **1.454208** / 0.8080 / 18 | 1.152537 / 0.7591 / 24 | **2.415744** / 1.3659 / 9 | 1.8e-7 |
| **Final candidate (card-notes λ0.5)** | 0.951081 / 0.7061 / 1 | 1.454208 / 0.8080 / 18 | 1.152537 / 0.7591 / 24 | **2.378141** / 1.3555 / 9 | 1.8e-7 |
| LLM labels λ0.5 (teammate, vs v1) | — | — | — | 2.2905 / — / 7 | **not reproducible (B5)** |

Bold = value that was previously reported and was reproduced. Failures: 0 in every run.

### Breakdown by family / panel / horizon / shape (means; caps for final)

Practice (88):

| Dimension | Group | n | M0 | v1 | v1.1 | Final | Final caps |
|---|---|---:|---:|---:|---:|---:|---:|
| family | F1 | 19 | 0.932 | 0.848 | 0.842 | 0.843 | 0 |
| family | F2 | 23 | 2.000 | 2.027 | 2.034 | 1.975 | 0 |
| family | F3 | 18 | 1.376 | 1.285 | 1.278 | 1.277 | 0 |
| family | F4 | 28 | 4.817 | 4.588 | 4.529 | 4.459 | 9 |
| horizon | 1–21 | 23 | 4.882 | 4.601 | 4.526 | 4.442 | 7 |
| horizon | 22–63 | 28 | 1.960 | 2.140 | 2.141 | 2.094 | 1 |
| horizon | 64–126 | 18 | 2.138 | 1.804 | 1.809 | 1.803 | 1 |
| horizon | 127+ | 19 | 0.932 | 0.848 | 0.842 | 0.843 | 0 |
| panel | factors_daily | 13 | 4.712 | 4.502 | 4.438 | 4.427 | 5 |
| panel | g10_fx_daily | 28 | 2.071 | 2.174 | 2.150 | 2.059 | 1 |
| panel | macro_monthly | 3 | 5.804 | 3.934 | 3.876 | 3.876 | 1 |
| panel | rates_daily | 39 | 2.087 | 2.001 | 1.999 | 1.983 | 2 |
| panel | mixed (fx/factors + rates) | 5 | 1.063 | 1.022 | 1.021 | 1.021 | 0 |
| shape | joint | 36 | 1.502 | 1.405 | 1.395 | 1.394 | 1 |
| shape | single | 52 | 3.256 | 3.149 | 3.123 | 3.059 | 8 |

CV 2009–18 / held-out 2019–24 (family; synthetic family ≡ horizon bucket by template construction):

| Family | CV M0 | CV v1 | CV v1.1 | HO M0 | HO v1 | HO v1.1 | HO caps v1.1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| F1 | 1.080 | 0.986 | 0.981 | 2.184 | 2.061 | 2.048 | 13 |
| F2 | 0.975 | 0.907 | 0.906 | 1.269 | 1.237 | 1.245 | 1 |
| F3 | 1.074 | 0.959 | 0.961 | 1.472 | 1.498 | 1.498 | 2 |
| F4 | 1.021 | 0.965 | 0.961 | 1.156 | 1.174 | 1.169 | 2 |
| macro_monthly panel | 1.366 | 1.283 | 1.278 | 1.629 | 2.014 | 1.940 | 2 |

Full panel/horizon/shape tables for all partitions: `reports/audit/comparison-breakdowns.csv`.

### Text ablation by family (practice, numeric_v1.1 → final card-notes)

| Family | n | numeric-only | card-notes λ0.5 | Δ | caps |
|---|---:|---:|---:|---:|---|
| F1 | 19 | 0.841566 | 0.842977 | +0.001411 | 0 → 0 |
| F2 | 23 | 2.033922 | 1.974978 | −0.058943 | 0 → 0 |
| F3 | 18 | 1.277705 | 1.276660 | −0.001045 | 0 → 0 |
| F4 | 28 | 4.529173 | 4.459123 | −0.070050 | 9 → 9 |
| **All** | 88 | 2.415744 | 2.378141 | **−0.037603** [−0.068127, −0.013183] | 9 → 9, none new or removed |

The LLM-label arm ("final with LLM text") could not be run: no cache (B5).

---

## 4. Acceptance gates

### numeric_v1.1 vs numeric_v1 (Phase 2.5 C1 + held-out veto), recomputed independently

| Gate | v1 | v1.1 | Result |
|---|---:|---:|---|
| CV mean strictly improves | 0.953077 | 0.951081 | PASS (Δ −0.00200, year-block CI [−0.00510, +0.00099]) |
| Practice mean does not worsen | 2.435614 | 2.415744 | PASS (Δ −0.01987, CI [−0.04109, +0.00344]) |
| CV + practice caps do not rise | 10 | 10 | PASS |
| No major group > 10% worse (CV, practice) | — | worst CV +0.38% (fx+rates, n = 63); worst practice −0.84% (single, n = 52) | PASS |
| Held-out veto (> 15% vs v1) | — | worst +0.65% (F2, n = 144) | PASS (no veto) |

None of the v1.1 improvements is statistically distinguishable from zero. It is a safe, tiny step.

### Tail candidates variance-normalized? Yes.

`t2agent/numeric_v1_1.py:98-102`:

```python
def tail_scale(rng, count, kind):
    if kind == 'student_unit':
        return np.sqrt(3./rng.chisquare(5., count))      # = sqrt(3/5) * sqrt(5/chi2_5): t5 rescaled to unit variance
    if kind == 'mixture_unit':
        return np.where(rng.random(count) < .05, 3., 1.)/np.sqrt(1.4)   # 0.95*1 + 0.05*9 = 1.4
```

The selected FHS tail (`fhs5`) normalizes the block-sum covariance to the target covariance
(`block_shock`, lines 129–163). Fewer than 20 residual rows fall back to the unit-variance t5.

### Monthly macro: mid-2022 regression NOT fixed (W3)

| Year | cards | M0 (2000) | numeric_v1 | numeric_v1.1 |
|---|---:|---:|---:|---:|
| 2021 | 4 | 5.685 (2 caps) | 4.079 (1 cap) | 4.361 (1 cap) |
| 2022 | 8 | 0.842 (0 caps) | 2.796 (1 cap) | 2.659 (1 cap) |

v1.1 improves 2022 by only 5% vs v1 and is still 3.2× M0. 2021 gets slightly worse than v1. All years:
`reports/audit/macro-monthly-by-year.csv`.

### Text decision rule

- Rule (`reports/phase4/VALIDATION.md`): labels λ0.5 only with all 88 replayed; otherwise card-notes λ0.5 if
  the mean improves and caps do not rise; else numeric-only. Labels are unavailable, so the rule selects
  **card-notes λ0.5**: mean 2.415744 → 2.378141, caps 9 → 9. **λ = 0.5 is what the rule says.** The decision
  is correctly labeled *provisional*.
- Clamps (rationale ledgers for all 88 practice outputs): aggregate drift **+0.0000 SD on every card**
  (card-notes cannot invent signs). vol_mult = 1.000 (68), 1.125 (16, "elevated" 1.25 at λ0.5), 1.075 (4,
  binary floor 1.15 at λ0.5) with tail 1.125. **vol_mult < 1 never occurs.** |drift| ≤ 0.5 SD holds trivially.
- No House requests in any card-notes run (0 per unit).

### Choices made after looking at report-only data

| Finding | Severity |
|---|---|
| Phase 3 B4 v2 rules revised after reading practice per-unit results, then selected on the same practice set in Phase 4 (W1). | Medium: selection bias on a −0.038 gain |
| Phase 2 diagnosis saw 2019–2024 M0 failures before the menu was written (W2). | Low: informs menu design, no ranking |
| Phase 2.5 used practice for selection. This was explicitly allowed by the C1 protocol, and held-out was veto-only. | Allowed, not a violation |
| Phase 4 binary-branch correction made before any label scoring; card-notes scores unchanged. | OK |
| Teammate's dev sweep: sizing tuned from token usage, not outcomes. | OK |

---

## 5. Mock Final, end to end

Harness: `t2eval.mock_final` (the code behind `make mock-final`), official scorer, M0 normalization, 104 units
(103 practice + exemplar), proxy scores on 88. `DOCKER_CONFIG` was a fresh empty temp dir and `DOCKER_HOST`
was explicit. Local Colima VM: 4 CPUs, 6.6 GB, amd64 under Rosetta. Driver: `.context/audit/run_mock.sh`.
Results: `reports/audit/mock-final-matrix.csv`, `mock-final.json`.

**Which digest?** No final digest exists (B1), so §4 could not run "on the exact submission digest". It ran on
(a) the **published fallback digest** `ghcr.io/hhwolf/agenthon-numeric-v1@sha256:f3ec5167…c085c507`, pulled
anonymously after removing the local copy, and (b) the **candidate image built from `ee31323`**
(`sha256:47df21ea…`, run with `--allow-local-image`). Image (b) is behaviorally what a `final-*` tag would
publish, but its digest will differ, so the eight sweeps must be repeated on the real digest.

| Sweep | Image | Network / House | Pass | Proxy mean (88) | Caps | Requests max/unit | Wall mean / max (s) | Σ wall 104 units (s) | Max tree |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| pub-offline (cold pull) | fallback | none | 104/104 | 2.415744 | 9 | 0 | 1.30 / 5.66 | 134.9 | 418,910 B, 3 files |
| pub-canned | fallback | restricted / canned | 104/104 | 2.415744 | 9 | 0 | 1.35 / 1.80 | 140.7 | 418,910 B |
| pub-chaos | fallback | restricted / chaos | 104/104 | 2.415744 | 9 | 0 | 1.35 / 1.92 | 140.4 | 418,910 B |
| pub-replay | fallback | restricted / replay | 104/104 | 2.415744 | 9 | 0 | 1.35 / 1.69 | 140.7 | 418,910 B |
| fin-offline | candidate | none | 104/104 | **2.378141** | 9 | 0 | 1.82 / 2.29 | 189.3 | 424,845 B, 3 files |
| fin-canned | candidate | restricted / canned | 104/104 | 2.378141 | 9 | 0 | 1.86 / 2.32 | 193.0 | 424,845 B |
| fin-chaos | candidate | restricted / chaos | 104/104 | 2.378141 | 9 | 0 | 1.89 / 2.33 | 196.1 | 424,845 B |
| fin-replay | candidate | restricted / replay | 104/104 | 2.378141 | 9 | 0 | 1.85 / 2.38 | 192.9 | 424,845 B |
| fin-offline-repeat | candidate | none | 104/104 | 2.378141 | 9 | 0 | 1.77 / 2.23 | 184.3 | — |
| fin-seed-a (`QFBENCH_SEED=1111`) | candidate | none | 104/104 | 2.379504 | 9 | 0 | 1.84 / 2.24 | 190.9 | — |
| fin-seed-b (`QFBENCH_SEED=2222`) | candidate | none | 104/104 | 2.389690 | 9 | 0 | 2.10 / 6.45 | 218.8 | — |
| lab-canned (informational: **LLM-labels variant**, not the candidate) | candidate + `TEXT_LAYER_MODE=labels` | restricted / canned | 104/104 | 2.343591 (canned fixtures, **not accuracy**) | 8 | 8 | 2.89 / 10.29 | 300.2 | 440,730 B |
| lab-chaos (informational, first 12 units) | same | restricted / chaos | 12/12 | — | — | 7 | 122.9 / 124.6 | 1,474.8 | 102,489 B |

Gate-by-gate:

- **104/104 admissible in every mode**: PASS (11/11 sweeps, both images).
- **Requests per unit ≤ 20, none over 25**: PASS. The candidate and the fallback send **0** House requests in
  every mode. The labels variant sent at most 8 (canned).
- **max_tokens ≤ 4000**: PASS. Clamped in the client (`client.py:261`); all 649 admitted labels-variant
  requests logged max_tokens 4000.
- **Zero non-House egress**: PASS by construction. The solver sits on `--internal` Docker networks whose only
  route is the fixed-backend proxy, and the proxy returns 403 for any origin other than `house.internal:8000`.
  The harness does not count refused attempts. Phase M's 27 network-probe assertions cover this path (per BUILD_LOG; not re-run in this audit).
- **Wall time incl. pull: mean ≤ 240 s, max < 600 s**: PASS by a wide margin. Candidate mean 1.8 s, max 2.4 s
  (one 6.45 s outlier under host load). Fallback cold-pull unit 5.66 s. **Projected 100 units: about 190 s,
  0.44% of the 43,200 s clock.** Caveats: the base layers were already cached (W7), and the candidate was not
  pulled at all (local image).
- **Chaos mode**: the candidate and the fallback make no requests, so chaos is vacuous for them; outputs are
  byte-identical to offline. The House-failure path was exercised with the labels variant (below).
- **Determinism**: candidate offline vs offline-repeat: **104/104 identical triplets** (parquet, meta,
  rationale). Offline vs canned/chaos/replay: 104/104 identical triplets for both images.
- **Fresh-seed rerun**: proxy means 2.379504 (seed 1111) and 2.389690 (seed 2222) vs 2.378141 (default
  per-card seeds). Each lies inside the other's year-block bootstrap 95% CI ([1.722, 3.187] / [1.732, 3.196]);
  paired Δ = +0.0102, CI [−0.0024, +0.0239] includes 0. Caps 9/9. 104/104 parquets changed (the seed is
  honored). PASS.
- **Output tree**: max 424,845 bytes and 3 files (limits 64 MiB / 256 files), 0 symlinks, 0 blank rationales.
  PASS.
- **Chaos, House-failure path (labels variant, 12 units, 65 admitted requests: 13× 503, 12× 120 s timeout, 12×
  slow, 12× malformed JSON, 8× malformed content, 8× valid)**: PASS. **12/12 units wrote a valid forecast
  (exit 0, no crash).** 9 ended in a neutral signal whose rationale records the reason (`**Neutral signal** —
  CallFailed: JSONDecodeError … The forecast is numeric-only.`). 3 kept labels after excluding 1 of 3 failed
  vote runs (`1 of 3 synthesis run(s) failed and were excluded from the vote`, with a per-request log such as
  `extract_1=503, … labels_3=None`). Harness-admitted counts equal the rationale-reported counts on all 104
  canned units. A single injected 120 s timeout makes a unit take about 123 s, which projects to about
  12,300 s per 100 units (28% of the clock). That is acceptable, but persistent House slowness up to the
  400 s hard stop would use 93%.
- **Rationale cites doc_ids when text is used**: card-notes reads no corpus documents. Its ledger states
  "no validated document evidence | Card cues are inferred; no document citation invented", which is correct
  rather than fabricated citations. The labels variant's rationales carry doc_id evidence tables on 104/104 canned units.

---

## 6. Rules and submission readiness

| Item | Status |
|---|---|
| linux/amd64 | candidate image `sha256:47df21ea…` (local build of `ee31323`) and public `f3ec5167…`: amd64 ✔ |
| Public anonymous pull | fallback ✔ (manifest + 10 blobs 200, empty-config pull). Candidate: **not published (B1)** |
| Non-root | `USER runner`, uid 1000 ✔ |
| No `VOLUME` | `Config.Volumes` absent ✔ |
| No vendor/, .eval/, realized/parquet data, .env, keys, cached LLM responses | ✔. `.dockerignore` is an allowlist (`t2agent/**`, minus `__pycache__`, `*.parquet`, `realized*`). The in-image `find` shows only pyarrow's own test fixtures as parquet. Env holds only Python's public `GPG_KEY` signing-key ID. `TEXT_LAYER_CACHE_DIR` is unset. |
| No per-unit answers | ✔. 0 of 104 unit IDs appear anywhere in `/app` or site-packages (`grep -rIlF -f unit_ids`). The runtime has no data files beyond 3 JSON configs. |
| Output tree < 64 MiB, ≤ 256 files, no symlinks | ✔ (see §5) |
| `submission.json` | **does not exist (B1)**. Dry-run via `t2eval.final_release.make_descriptor` (pinned toolkit fixture, sealer, parser, JSON schema; no pack): schema 1.1.0, interface 2.0, track forecasting, phase final, category api, image_access public, license required. `models: []` for card-notes / numeric (correct: no learned model, per SUBMISSION_CLI.md §"api"). With House: `{name: nvidia/nemotron-3-super-120b-a12b, version: rl-030326-fp8, revision: rl-030326-fp8, training_cutoff: unpublished, access: api}` passes. |
| team_id | 756 is the website team number; the alias is derived at pack time. Correctly not written. |
| Prompts (only relevant if labels ship) | `prompts.py:64` "AS-OF DATE … You know nothing after this date. Do not use any knowledge of what happened after …"; rules require exact `doc_id`, "never cite outcomes or events after the as-of date"; system prompts say "no tools and no web access"; `client.py:258-262` temperature 0.0, top_p 1.0, seed 20261014 (+k for vote runs), `max_tokens=min(…, 4000)`; `client.py:230,292` `max_retries=0`. No `tools` parameter is ever sent. |

---

## 7. Risk review

| Risk | Likelihood | Cost if it happens | Mitigation |
|---|---|---|---|
| Text layer hurts on sealed 2025–26 cards (memorization inflated the practice gains) | **LLM labels: medium–high.** Practice episodes are famous (COVID, GFC, 2021 FOMC); the model may "know" outcomes despite the prompt. **Card-notes: low.** No LLM; it only widens 20/88 cards by ≤ 12.5% and never shifts the centre. | LLM: a large share of the −0.145 could vanish or reverse. Wrong-way widening on calm cards costs about +0.01–0.03 each. Card-notes worst case on practice-like cards: about +0.01–0.02 mean. | Ship card-notes, not labels. If labels ever ship, only at λ ≤ 0.5 with neutral fallback. |
| House outages / slowness | Not applicable to card-notes or numeric (0 requests). For labels: medium. Dev sweep had a network outage that turned 63 units neutral. | Labels: units fall back to numeric (the chaos test shows a neutral signal, not a crash); time per unit is bounded by the 400 s hard stop. | Card-notes removes the dependency entirely. |
| Monthly cards in the Final | Medium (practice has 4 monthly units; the sealed set likely has a few) | High per card: 2022-like macro regime gives v1.1 2.66 vs M0 0.84; 1 of 3 practice monthly cards is capped (covid-nfp, unclipped 248) | Accept for now (A4 alternatives failed). Post-competition: vintage-aware data and damped trend. |
| EM transfer cards | Medium (3/104 practice units are EM transfer) | Unknown, never measured (W5). Numeric path is generic and should be admissible (104/104 includes them). | Accept. They pass admissibility; scoring is unknown either way. |
| 10-asset joint cards | Low–medium (1/104 practice) | Low. Practice 10-asset card scores 0.946 (v1.1) vs M0 1.089; output 0.40 MiB vs 64 MiB limit. | None needed. |
| Wall-clock overrun | Very low for card-notes: about 1.3 s/unit locally, about 130 s per 100 units (0.3% of 43,200 s) | Catastrophic if it happened (failed cards = 8) | For labels: worst case 100 × 400 s = 40,000 s = 93% of the clock. Do not ship labels without lowering `TIME_BUDGET_S`. |
| LLM nondeterminism at verification rerun | None for card-notes (0 requests; same-seed reruns byte-identical, §5) | Labels: 29% of units had vote agreement < 0.8, so a rerun moves cards | Card-notes eliminates it. |
| Process: unreviewed, unpushed code, no license (B2–B4) | Certain today | Cannot upload at all | Do these first (Oct 17–18). |

---

## 8. What could still be improved (ranked by expected gain ÷ risk)

### Do before upload (all must finish by Oct 22, including the full mock-final rerun)

| Rank | Action | Evidence | Est. effect | Effort | Safe and fully re-verifiable before Oct 23? |
|---:|---|---|---|---:|---|
| 1 | Push the branch, open a PR, get grep = 5 (B3/B4) | §2 | enables any upload | 1–4 h (review loop) | Yes |
| 2 | Choose and add a license (B2) | schema requires `license` | enables any upload | 0.25 h (human) | Yes |
| 3 | Freeze `release.json` (card_notes_only, 0.5, runtime SHA256s), tag `final-*`, publish, run `t2eval.final_release` (8 sweeps, cold pull on a fresh daemon), write `submission.json` from the verified digest (B1) | `docs/FINAL_RELEASE.md` | −0.038 practice vs fallback (in-sample; expect 0 to −0.03 on the sealed set) | 3–5 h (about 1 h of machine time) | Yes, the tooling exists |
| 4 | Prepare the fallback descriptor for `f3ec5167…` now (same license) and store it next to the primary | §6 dry-run passes | insurance against a late failure | 0.5 h | Yes |
| 5 | Eval-only: add `TEXT_LAYER_MODE`/`LAMBDA` to the `t2eval/cli.py` run identity (W6) | §2 W6 | prevents wrong comparisons; no image change | 0.5 h | Yes, no image rerun needed |

### Not worth the risk now

| Action | Evidence | Est. effect | Effort | Why not now |
|---|---|---|---:|---|
| LLM labels λ0.5 | teammate: −0.145 practice vs v1, caps 9 → 7, gain concentrated in F4 (−0.43) | sealed: unknown, could be ≈ 0 or positive (memorization) | 10–14 h after the cache arrives | Cache missing; integrated v1.1 comparison never run; House dependency; nondeterminism; wall-clock exposure. Revisit only if the cache arrives by about Oct 19 **and** every check passes. |
| F4 family-aware tail floor (playbook recommends Student-t / heavier tails for F4) | 5 practice caps at 8.3–9.85 unclipped; F4 = 34% of practice mean | possibly −0.05 to −0.15 on F4-heavy sets | 4–6 h + full rerun | Can only be validated on the practice set it would be tuned on. Synthetic F4 cards are random dates, not shocks. High overfit risk. |
| Monthly trend damping / vintage fix | W3 | macro-only | 6+ h | All A4 variants failed C1; no clean validation data left |

### Ideas for after the competition

Vintage-aware (point-in-time) macro data; regime-switch volatility for quiet-to-moving transitions (the
2021 UST_2Y cluster); measured EM transfer data; LLM labels evaluated only on post-training-cutoff episodes;
an explicit cap-avoidance objective (caps are about a third of the practice loss).

---

## 9. Reproduce everything

```sh
# 0. Tree under audit
git checkout ee31323            # hhwolf/phase4-text-integration
# 1. Tests and admissibility (canonical make targets; this audit used --work .context/audit/eval-A to avoid touching .eval/)
make test
make admissibility FORECASTER=numeric_v1_1
# 2. Backtests and practice (exact audit driver: reports/audit/scripts/run_evals.sh)
.venv/bin/python -m t2eval.cli generate --work .context/audit/eval-A
.venv/bin/python -m t2eval.cli backtest --forecaster m0 --work .context/audit/eval-A
.venv/bin/python -m t2eval.cli backtest --forecaster m0 --n-draws 2000 --work .context/audit/eval-A
.venv/bin/python -m t2eval.cli backtest --forecaster numeric_v1 --work .context/audit/eval-A
.venv/bin/python -m t2eval.cli backtest --forecaster numeric_v1_1 --work .context/audit/eval-A
.venv/bin/python -m t2eval.cli eval-practice --forecaster m0 --work .context/audit/eval-A
.venv/bin/python -m t2eval.cli eval-practice --forecaster m0 --n-draws 2000 --work .context/audit/eval-A
.venv/bin/python -m t2eval.cli eval-practice --forecaster numeric_v1_1 --work .context/audit/eval-A      # final (card-notes)
# numeric-only arms MUST use a separate --work dir (W6); union/practice/synthetic symlinked from eval-A
TEXT_LAYER_MODE=numeric_only .venv/bin/python -m t2eval.cli eval-practice --forecaster numeric_v1   --work .context/audit/eval-N
TEXT_LAYER_MODE=numeric_only .venv/bin/python -m t2eval.cli eval-practice --forecaster numeric_v1_1 --work .context/audit/eval-N
.venv/bin/python reports/audit/scripts/analyze.py          # -> reports/audit/{comparison-*.csv,gates.json,macro-monthly-by-year.csv}
# 3. Image build and inspection
DOCKER_HOST=unix://$HOME/.colima/agenthon/docker.sock DOCKER_CONFIG=$PWD/.context/docker-config \
  docker buildx build --platform linux/amd64 --load -t audit-final:ee31323 .
.venv/bin/python scripts/verify_ghcr_public.py ghcr.io/hhwolf/agenthon-numeric-v1@sha256:f3ec5167b28f0172004a78e336d84a4ecd423d27da42d942693e51cfc085c507 --out .context/audit/anonymous-pull-v11.json
# 4. Mock Final matrix (exact driver: reports/audit/scripts/run_mock.sh; empty DOCKER_CONFIG, explicit DOCKER_HOST)
make mock-final IMAGE=ghcr.io/hhwolf/agenthon-numeric-v1@sha256:f3ec5167…c085c507 UNITS=practice NETWORK=none ARGS='--pull-policy always'
make mock-final IMAGE=… UNITS=practice NETWORK=restricted ARGS='--house-mode canned|chaos'
make mock-final IMAGE=… UNITS=practice NETWORK=restricted ARGS='--house-mode replay --replay-dir .context/audit/empty-replay'
# candidate (local image until B1): add --allow-local-image; fresh seeds: ARGS='--seed 1111' and '--seed 2222'
.venv/bin/python reports/audit/scripts/mock_summary.py     # -> reports/audit/mock-final.{csv,json}
# 5. Once B1 is done, the release verifier on the exact digest:
.venv/bin/python -m t2eval.final_release --image ghcr.io/hhwolf/agenthon-numeric-v1@sha256:<FINAL> --replay-dir <dir>
```

Audit artifacts: `reports/audit/AUDIT.md` (this file), `Agenthon_Track2_PreSubmission_Audit_2026-10-16.pdf`,
`comparison-headline.csv`, `comparison-breakdowns.csv`, `gates.json`, `macro-monthly-by-year.csv`,
`mock-final-matrix.csv`, `mock-final.json`. Raw run outputs: `.context/audit/` (git-ignored).
