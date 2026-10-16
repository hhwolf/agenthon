# Phase M: mock Final harness

Contract source: pinned vendor/track2 README Output folder rules and
SUBMISSION_CLI.md. This emulates the public contract, not unpublished Final
infrastructure or sealed outcomes. Hardware limits scale down to the Docker
server. Practice labels remain local proxies; no sealed scores are claimed.

- Run immutable published digests with the whole staged unit at /input:ro,
  writable /output, read-only root, 64 MiB /tmp, amd64, no swap, and a deadline
  covering staging, pull when requested, container creation and execution.
- Offline mode has no network. Restricted mode puts the solver on an internal
  network; a forwarding proxy alone bridges it to a second internal network
  containing House. House has no route directly from the solver. No service
  exposes host ports. The proxy permits only the mock House origin.
- Reuse tests/mock_house.py canned response generation. Add an admission layer:
  per-unit bearer token/window, exact POST /v1/chat/completions, 25 requests,
  clamped output limits, refused n>1, counts charged before upstream behavior.
  Canned, deterministic chaos, and exact request-hash dev-cache replay modes.
- Stop containers before inspecting the complete output tree. Enforce every
  listed tree rule without following links. Crash/timeout take precedence;
  rejected or missing outputs become no_output; invalid official gates become
  schema_invalid. OOM is reported as resource_oom per vendor. Failures score 8.
- Reuse official.score, official.normalize and expected_errors. Score after the
  ingestion stage so scoring does not consume its separate 43,200 s clock.
  Successful unlabeled units have no invented score; mean denominator is clear.
- Record measured pull time/cache state, per-unit setup/execution/wall time,
  requests, score, aggregate caps, and 104-unit projection versus 21,600 s.
  Optional second digest produces paired rows and a side-by-side summary.
- Verify the Phase 2 numeric_v1 digest on all 104 supplied units offline and
  restricted with zero admitted requests. Exercise all four requested failure
  labels with local broken-image fixtures, plus network/admission/replay probes.

`UNITS=practice` means all 104 supplied units, including the exemplar;
`UNITS=exemplar` means just the exemplar; N selects the first N sorted units.
A warm Docker cache is reported honestly: no cached pull is labeled a true cold
layer download. Helper infrastructure setup is timed separately from ingestion.
