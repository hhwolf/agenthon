# Phase 4 protocol — frozen before scoring

Baseline: the frozen Phase 2.5 numeric_v1.1 (A1_fhs5), 2,000 draws,
card-derived seed unless QFBENCH_SEED is explicitly supplied. Keep both earlier
numeric configuration files and Phase 2 frozen selection unchanged.

Compare the same 88 locally resolvable practice proxies with the official scorer
and existing M0 expected-error normalization. These are development proxies,
not the sealed Final and not an untouched validation set. The inherited B4 v2
pre-pass already saw practice results in Phase 3; disclose that exposure.

Arms, fixed in advance:

1. numeric_v1.1, text disabled;
2. cached Phase 3 model labels, lambda 0.5;
3. the identical cached labels, lambda 1;
4. B4 card-prose-only pre-pass, lambda 0.5 (no corpus reads or LLM calls).

The label-to-number constants are the user's fixed starting values, motivated
by SOLVER-PLAYBOOK sections 3–5. The playbook supplies principles, not these exact
coefficients. Retain Phase 3's event width floor 1.15 and tail multiplier 1.25;
no outcome-based coefficient fitting. Keep the inherited B4 v2 lexicon rules
unchanged, but supply no corpus documents. Card description and text.notes count
as card prose. Its existing volatility-ratio guard remains a numeric feature.

Before scoring, correct these integration semantics: disagreement suppresses
all scenario drift (including binary branches) and directional tails; binary
branches use signed +/-1 sd without adding the ordinary direction shift; branch
probabilities normalize then clip to [0.2,0.8]. The binary mean-drift allowance is
0.6 sd, implied by those explicit limits, rather than rescaling the +/-1 branches
to the old generic 0.5-sd limit. Lambda shrinks drift and (vol-1)/(tail-1).
One branch choice covers every asset and horizon of a draw. Crisis or F4 with a
named side fattens that side of the outer 5% of draws; do not add a second,
unrequested crisis-shock mixture. Unnamed tails stay symmetric. All signal
failures and lambda zero preserve completed numeric draws exactly.

The card-notes arm cannot invent asset branch signs from an event name; zero
signs mean no directional branch effect. Established/inferred evidence is shown
in the rationale. Inferred evidence cannot narrow volatility.

Decision (balanced), without retuning:

- Select labels at lambda 0.5 only if all 88 have replay provenance, the mean
  improves strictly and caps do not increase versus numeric_v1.1.
- Upgrade to lambda 1 only if it also improves the overall mean versus lambda
  0.5, caps do not increase versus either, and every family improves versus the
  numeric baseline and does not worsen versus lambda 0.5.
- Otherwise select card-notes-only lambda 0.5 if its mean improves and caps do
  not increase; otherwise numeric-only.
- Missing cached labels are unavailable measurements, never synthetic model
  responses, neutral stand-ins, or scored rows counted as successful replay.
  A decision made without all 88 cached labels is explicitly provisional.

Report overall mean, median, capped-card count, family means/caps, paired per-card
score deltas, and new/removed caps. Include a paired as-of-year block bootstrap
95% CI (10,000 resamples, seed 20261015); this is descriptive, not another gate.
Check deterministic/neutral behavior, shared branch signs, asymmetric tails,
no-network B4, evidence writing, malformed text fallback, and all 104 public
units for admissibility. Keep labels, caches, outcomes and evaluation outputs
out of the runtime image. Do not pack or upload a competition submission.

## Implementation correction before any model-label scoring

A regression test exposed a non-opposing binary case: an 80/20 rise-versus-hold
label (+1/0 signs) was rescaled to +0.75/0 by the proposed 0.6-SD mean limit.
The user's fixed +/-1-by-sign rule takes precedence. Binary branches now allow
their implied maximum weighted mean of 1 SD; opposing +/-1 branches still imply
at most 0.6 SD under the probability clips. Generic non-binary signals retain
the 0.5-SD mean cap. This correction changes no card-notes scores (its signs are
all zero), and neither model-label arm has been scored. No value was fitted.
