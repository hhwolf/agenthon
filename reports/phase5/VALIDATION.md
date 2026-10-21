# Phase 5 final release protocol

Frozen before Phase 5 execution on 2026-10-16. The numeric configuration remains
numeric_v1.1 (A1_fhs5), 2,000 draws. Phase 4's integrated replay comparison must
finish before changing its provisional card-notes selection to a final selection.
The teammate's 2026-10-15 results at `2d6601e` support labels at lambda 0.5 but
use numeric_v1 and the earlier mapping, so they do not replace that comparison.

Publish an immutable linux/amd64 image through a `final-*` CI tag. Keep the
package public until results. No competition packing, Team Key handling, or
CodaBench upload is performed by these scripts.

Run the same published digest on all 104 supplied units in eight sequential
sweeps: offline, restricted+canned, restricted+chaos, restricted+replay, offline
repeat, offline fresh seed, replay repeat, and replay fresh seed. The baseline
numeric seed is 20261016 and the fresh seed is 20261017. Do not select seeds
after seeing scores. Model request seeds retain the Phase 3 fixed values.

Each sweep must pass all 104 output/schema gates, mean per-unit wall time
(including pull when needed) <=240 s, maximum <600 s, at most 20 admitted
requests per unit, and total output strictly below 64 MiB per unit. The
43,200-second platform clock and its half-clock warning remain reported.
Offline and model-free configurations must send zero requests. A model-using
replay must have at least one admitted request per unit and every admitted
request must match the supplied cache; replay misses cannot pass as fallbacks.
Real cached malformed model replies may legitimately exercise neutral fallback.

Use a credential-free Docker configuration for the full suite. Record whether
the image was present before each sweep; a cached pull does not demonstrate a
cold pull. The first sweep must start without the final image locally. Shared
base layers may already exist; report this limitation explicitly. Also run the
starter pack's anonymous manifest/blob check. Do not delete unrelated images
or caches to manufacture a cold run.

Compare all three deliverables byte-for-byte for the same-seed offline pair
and replay pair. The runtime rationale omits measured times and sorts the
concurrent request ledger, while timing remains in harness reports. Do not
normalize files after the fact to manufacture identical outputs.

For each of offline and replay, pair exactly the 88 practice proxies and
bootstrap whole as-of-year blocks (10,000 resamples, fixed bootstrap seed
20261016). Report each run's mean and 95% percentile interval; require each
seed's mean to lie inside the other seed's interval. Also report the paired
fresh-minus-baseline mean and its interval. These are Monte Carlo stability
checks, not a claim of out-of-sample accuracy or fresh model-response coverage.

Write submission metadata from the toolkit's forecasting_final fixture, using
schema 1.1.0, interface 2.0, forecasting/final/api, public image access, the
published digest and an explicitly chosen code license. Include the official
House disclosure only when the selected mode calls House. Validate with both
the toolkit JSON schema and SubmissionDescriptor.from_mapping, using the
toolkit's seal_descriptor_digest. If no public team alias is supplied, leave
team_id absent in the pack input; validate a clearly marked in-memory alias
copy and report that the on-disk input is not yet a sealed C5 descriptor.

Human handoff: pack with the team number and hidden Team Key prompt, then upload
to CodaBench Final on the user's planned October 23 date. Never store or publish
the Team Key. October 23 is the user's target date, not a newly asserted
organizer deadline.
