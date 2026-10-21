# Opt-in compatibility container checks

Local immutable image ID: `sha256:a1e704ea78cfd0bd85bb232235c0569aab8688f3c5da2cb57aa3f2cb0a6cc9f5`.

Built for linux/amd64 with DEFAULT_FORECASTER=numeric_alignment; no model arm selected.
Not published to GHCR; selected release and descriptors unchanged. House disabled.

| Mode | Passed | Mean seconds | Max seconds | Requests | Max output bytes |
|---|---:|---:|---:|---:|---:|
| offline | 126/126 | 2.083 | 2.722 | 0 | 424843 |
| canned | 126/126 | 2.092 | 2.838 | 0 | 424843 |
| chaos | 126/126 | 2.005 | 2.497 | 0 | 424843 |
| replay | 126/126 | 1.929 | 2.507 | 0 | 424843 |

All four modes used seed 1111. Every forecast, metadata file and rationale is byte-identical across modes.
All units used numeric_v1.1/FHS; no numeric or text-hook fallback was reported.
Replay used an empty cache: zero requests proves the offline dependency boundary, not LLM replay quality.
These local-image runs are warm-cache runs; no candidate registry cold-pull claim is made.
Selected-image anonymous cold pull is separately recorded in selected-cold-pull.json.
CPU/memory caps are scaled to this host (4 CPU, ~6.19 GiB); root read-only, unit input read-only, 64 MiB tmpfs.
The projected 126-unit sequential time is far below 21,600 seconds (half the platform clock).
Earlier partial checks of the pre-review image were discarded after a fallback repair; these rows all use the rebuilt image.

See container-verification.json and evidence/compat-*-cards.json.gz for exact hashes and per-unit measurements.
