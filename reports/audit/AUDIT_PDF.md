# Agenthon Track 2 — independent pre-submission audit

2026-10-16 · tree `hhwolf/phase4-text-integration@ee31323` · toolkit 2.6.0 · vendor `b9c663d` ·
full report and evidence: `reports/audit/AUDIT.md`

## 1. Verdict: GO WITH FIXES

**Upload the card-notes candidate** (numeric_v1.1 + card-notes-only text, λ = 0.5, `models: []`, zero House
requests) **after blockers B1–B4 are cleared** and the eight-sweep `t2eval.final_release` verification passes
on the exact published digest. **Fallback:** the already public numeric_v1.1 digest
`ghcr.io/hhwolf/agenthon-numeric-v1@sha256:f3ec5167b28f0172004a78e336d84a4ecd423d27da42d942693e51cfc085c507`,
which passed all four mock-final modes in this audit. **Do not ship LLM labels**: no response cache exists
anywhere reachable, so the claimed −0.145 practice gain cannot be reproduced and was never measured on
numeric_v1.1 with the integrated overlay.

Today there is **no final artifact**: no final image or digest, no `submission.json`, `release.json` is
`pending`, and `text_config.json` is `provisional`.

| Option | Practice mean (88) | Caps | Requests | Status today |
|---|---:|---:|---:|---|
| **Card-notes candidate** | **2.378141** | 9 | 0 | local image only; branch unpushed; no license |
| numeric_v1.1 public `f3ec5167…` (fallback) | 2.415744 | 9 | 0 | published, anonymous pull OK, mock-final 4/4 modes |
| LLM labels λ0.5 (teammate report, vs v1) | 2.2905 | 7 | ≈4–8 | unreproducible (no cache) |

## 2. Blockers

| # | Blocker | Evidence | Fix |
|---|---|---|---|
| B1 | No final image, digest or descriptor; nothing to match across submission.json / CI / mock grader | no `submission.json`; no `final-*` tag or run; `release.json` `pending` | freeze release, tag `final-*`, run `t2eval.final_release` on the digest, generate the descriptor from it |
| B2 | No code license; `license` is a required SPDX field; blocks the fallback too | `LICENSE` missing; schema `required` | human picks a license; add `LICENSE` |
| B3 | Grep gate unmet: 0 of 7 PRs carry any grep review or score; #1–#5 merged without a 5; the candidate branch has no PR | `gh api …/issues/N/comments`, `/reviews`, `/check-runs` all empty | open a PR, iterate to grep = 5 (also for code merged into the fallback) |
| B4 | Candidate exists only locally (9 commits ahead of main, no upstream) | `git status -sb`; `git ls-remote` | push now |
| B5 (labels only) | No LLM cache: replay ablation impossible | filesystem, branches, artifacts and releases searched | ship labels only if the cache arrives by about Oct 19 and every check passes |

## 3. Key warnings

- **W1** The card-notes gain is partly in-sample: B4 v2 rules were revised after reading practice results
  (Phase 3), then selected on the same proxies. Expect 0 to −0.03 on the sealed set, not −0.038.
- **W3** Monthly macro 2022 is still 3.2× M0 (0.842 → 2.659); held-out macro is +19% vs M0.
- **W4** Caps never fell (held-out 15 → 18). Practice: 9 F4 caps = 34% of the mean; five sit at 8.3–9.9 unclipped.
- **W5** EM transfer cards are unmeasured. **W6** The eval run-id ignores `TEXT_LAYER_MODE`, so numeric-only and
  card-notes practice runs overwrite the same directory. **W7** The "cold" pull reused cached base layers.

<!-- pagebreak -->

## 4. Reproduced comparison (re-run; ⚠ would mark |Δ| > 0.002 vs earlier reports: **none**)

2,000 draws (M0 also at 500), per-card CRC32 seeds, official scorer. Historical cards have no text, so the
final candidate equals numeric_v1.1 there. All 13 reported means reproduce within 5e-7; per-card max |Δ| ≤
1.8e-15; all cap counts match; 0 failures.

| Arm | CV 2009–18 (1,073) mean / caps | Held-out 2019–24 (554) | All hist. (2,060) | Practice (88) mean / median / caps |
|---|---:|---:|---:|---:|
| M0 (500) | 1.035657 / 2 | 1.488258 / 15 | 1.214629 / 24 | 2.551735 / 1.3254 / 11 |
| M0 (2000) | 1.033389 / 1 | 1.480838 / 15 | 1.210785 / 23 | 2.538247 / 1.3399 / 10 |
| numeric_v1 | 0.953077 / 1 | 1.456363 / 17 | 1.154244 / 23 | 2.435614 / 1.3770 / 9 |
| numeric_v1.1 | 0.951081 / 1 | 1.454208 / 18 | 1.152537 / 24 | 2.415744 / 1.3659 / 9 |
| **Final (card-notes λ0.5)** | 0.951081 / 1 | 1.454208 / 18 | 1.152537 / 24 | **2.378141 / 1.3555 / 9** |

| Practice by group | n | M0 | v1 | v1.1 | Final | caps |
|---|---:|---:|---:|---:|---:|---:|
| F1 | 19 | 0.932 | 0.848 | 0.842 | 0.843 | 0 |
| F2 | 23 | 2.000 | 2.027 | 2.034 | 1.975 | 0 |
| F3 | 18 | 1.376 | 1.285 | 1.278 | 1.277 | 0 |
| F4 | 28 | 4.817 | 4.588 | 4.529 | 4.459 | 9 |
| horizon 1–21 / 22–63 | 23 / 28 | 4.882 / 1.960 | 4.601 / 2.140 | 4.526 / 2.141 | 4.442 / 2.094 | 7 / 1 |
| horizon 64–126 / 127+ | 18 / 19 | 2.138 / 0.932 | 1.804 / 0.848 | 1.809 / 0.842 | 1.803 / 0.843 | 1 / 0 |
| panel macro_monthly / rates | 3 / 39 | 5.804 / 2.087 | 3.934 / 2.001 | 3.876 / 1.999 | 3.876 / 1.983 | 1 / 2 |
| panel g10_fx / factors | 28 / 13 | 2.071 / 4.712 | 2.174 / 4.502 | 2.150 / 4.438 | 2.059 / 4.427 | 1 / 5 |
| shape joint / single | 36 / 52 | 1.502 / 3.256 | 1.405 / 3.149 | 1.395 / 3.123 | 1.394 / 3.059 | 1 / 8 |

**Text ablation (numeric_v1.1 → card-notes):** −0.037603, year-block 95% CI [−0.068127, −0.013183]; F1
+0.0014, F2 −0.0589, F3 −0.0010, F4 −0.0700; caps 9 → 9 (none new or removed); 15/88 cards change. The
LLM-label arm could not be run (B5).

## 5. Acceptance gates

| Gate | Result |
|---|---|
| v1.1 vs v1: CV mean | PASS 0.953077 → 0.951081 (CI [−0.0051, +0.0010]) |
| v1.1 vs v1: practice mean | PASS 2.435614 → 2.415744 (CI [−0.0411, +0.0034]) |
| v1.1 vs v1: CV + practice caps | PASS 10 → 10 |
| No major group > 10% worse | PASS (worst CV +0.38%, practice −0.84%) |
| Held-out veto > 15% | PASS (worst +0.65%, F2) |
| Tails variance-normalized | PASS: `np.sqrt(3./rng.chisquare(5.))` (= √(3/5)·t5); mixture `/np.sqrt(1.4)`; FHS normalizes block covariance |
| Monthly mid-2022 fixed? | **NO.** Macro 2021: M0 5.685 / v1 4.079 / v1.1 4.361; 2022: 0.842 / 2.796 / 2.659 |
| Text rule → card-notes λ = 0.5 | PASS: mean improves, caps equal; labels unavailable → correctly *provisional* |
| Clamps | PASS: drift 0.000 SD on all 88; vol_mult ∈ {1.0, 1.075, 1.125}; never < 1 |
| Post-hoc choices on report-only data | W1 (practice-informed B4 v2, medium); W2 (2019–24 seen in diagnosis, low) |

<!-- pagebreak -->

## 6. Mock Final (empty `DOCKER_CONFIG`; local 4-CPU Colima; 104 units; 88 proxies)

No final digest exists, so the matrix ran on the **public fallback digest** (cold anonymous pull) and on the
**candidate image built from `ee31323`** (local, `--allow-local-image`). It must be repeated on the real digest.

| Sweep | Pass | Proxy mean | Req. max | Wall mean / max (s) | Σ104 (s) |
|---|---:|---:|---:|---:|---:|
| fallback offline (cold pull 3.7 s) | 104/104 | 2.415744 | 0 | 1.30 / 5.66 | 134.9 |
| fallback restricted canned / chaos / replay | 104/104 ×3 | 2.415744 | 0 | 1.35 / ≤1.92 | ≈140.6 |
| candidate offline / repeat | 104/104 ×2 | 2.378141 | 0 | 1.82 / 2.29 | 189.3 / 184.3 |
| candidate restricted canned / chaos / replay | 104/104 ×3 | 2.378141 | 0 | ≈1.87 / ≤2.38 | ≈194 |
| candidate seeds 1111 / 2222 | 104/104 ×2 | 2.379504 / 2.389690 | 0 | 1.84 / 2.10 | 190.9 / 218.8 |
| *LLM-labels variant* canned (fixture labels, not accuracy) | 104/104 | 2.343591 | 8 | 2.89 / 10.29 | 300.2 |
| *LLM-labels variant* chaos (12 units, 65 injected-fault requests) | 12/12 | — | 7 | 122.9 / 124.6 | 1,474.8 |

- **All gates PASS for the candidate and the fallback:** 104/104 in every mode; 0 requests; zero non-House
  egress (internal networks + allowlisting proxy); projected about 190 s per 100 units (0.44% of 43,200 s);
  output ≤ 424,845 B / 3 files, 0 symlinks, 0 blank rationales.
- **Determinism:** offline vs repeat, and offline vs canned/chaos/replay: 104/104 byte-identical triplets.
- **Fresh seeds:** each mean lies inside the other's bootstrap CI; paired Δ +0.0102, CI [−0.0024, +0.0239];
  caps 9/9; every parquet changed (the seed is honored).
- Chaos is vacuous for zero-request images. The House-failure path was exercised with an LLM-labels variant
  (above): 12/12 units produced valid forecasts; 9 fell back to neutral with the reason recorded in the rationale
  (`CallFailed: JSONDecodeError … numeric-only`), 3 kept labels after excluding 1 of 3 failed vote runs. No crash.

## 7. Rules and readiness

linux/amd64 ✔ · non-root `runner` ✔ · no VOLUME ✔ · `/app` = 27 files, 260 KB, allowlisted `.dockerignore` ✔ ·
no vendor/.eval/realized/.env/keys/LLM cache ✔ · 0/104 unit IDs anywhere in the image ✔ · fallback anonymous
manifest + 10 blobs HTTP 200 ✔ · descriptor dry-run via the pinned toolkit (no pack): schema 1.1.0, interface
2.0, forecasting / final / api / public, `models: []` (no learned model) ✔; the House row
`nvidia/nemotron-3-super-120b-a12b`, `rl-030326-fp8`, `unpublished`, `api` also validates · license ✘ (B2) ·
prompts: as-of stated, post-as-of knowledge forbidden, doc_id citations required, no tools, temperature 0,
seed 20261014, `max_retries=0`, max_tokens ≤ 4000 ✔.

## 8. Risk review

| Risk | Likelihood | Cost | Mitigation |
|---|---|---|---|
| Text hurts on sealed 2025–26 (memorization) | labels med–high; card-notes low | labels: gain may vanish or reverse; card-notes ≤ +0.02 | ship card-notes only |
| House outage / slowness | n/a for card-notes (0 calls); labels medium | labels: neutral fallback, ≤ 400 s/unit | card-notes removes the dependency |
| Monthly cards | medium | high per card (2022-type regime) | accept; post-competition fix |
| EM transfer cards | medium | unknown (never measured) | accept; admissible |
| 10-asset joint | low | low (0.946; 0.40 MiB) | none |
| Wall-clock overrun | very low (≈190 s total) | catastrophic | labels worst case 100 × 400 s = 93% of the clock: don't ship labels |
| LLM nondeterminism at rerun | none (byte-identical) | labels: 29% low-agreement units | card-notes |

<!-- pagebreak -->

## 9. Improvements, ranked by gain ÷ risk

**Do before upload** (everything must end with a full mock-final rerun on the published digest by Oct 22):

| # | Action | Effect | Effort | Safe before Oct 23? |
|---:|---|---|---:|---|
| 1 | Push branch, open PR, iterate to grep = 5 (B3, B4) | enables upload | 1–4 h | yes |
| 2 | Choose and add a license (B2) | enables upload | 0.25 h | yes |
| 3 | Freeze release, tag `final-*`, publish, run the 8 sweeps (fresh daemon for a true cold pull), write submission.json (B1) | −0.038 practice vs fallback (in-sample; sealed 0 to −0.03) | 3–5 h | yes |
| 4 | Prepare the fallback descriptor for `f3ec5167…` now | insurance | 0.5 h | yes |
| 5 | Eval-only: add text env to the run identity (W6) | avoids wrong comparisons | 0.5 h | yes (no image change) |

**Not worth the risk now:** LLM labels (cache missing; F4-concentrated −0.43 claim unverified; memorization;
House and clock exposure; 10–14 h). F4 family-aware tail floor (could pull five near-cap cards under 8, but it can
only be validated on the same practice set). Monthly trend fix (all A4 variants failed; no clean data left).

**After the competition:** point-in-time macro vintages; regime-switch volatility for quiet-to-moving transitions;
EM data; LLM labels tested only on post-training-cutoff episodes; an explicit cap-avoidance objective.

## 10. Reproduce

```sh
git checkout ee31323
make test                                   # 241 passed
make admissibility FORECASTER=numeric_v1_1  # 104/104 (audit used --work .context/audit/eval-A)
reports/audit/scripts/run_evals.sh                 # generate + 4 backtests + 5 practice arms + admissibility
.venv/bin/python reports/audit/scripts/analyze.py  # comparison-*.csv, gates.json, macro-monthly-by-year.csv
reports/audit/scripts/run_mock.sh                  # 11 mock-final sweeps + labels variant (empty DOCKER_CONFIG)
.venv/bin/python reports/audit/scripts/mock_summary.py
# numeric-only practice arms must use their own --work dir (W6):
TEXT_LAYER_MODE=numeric_only .venv/bin/python -m t2eval.cli eval-practice --forecaster numeric_v1_1 --work .context/audit/eval-N
# after B1:
.venv/bin/python -m t2eval.final_release --image ghcr.io/hhwolf/agenthon-numeric-v1@sha256:<FINAL> --replay-dir <dir>
```
