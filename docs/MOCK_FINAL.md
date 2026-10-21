# Mock Final harness

`make mock-final` runs an immutable published image against the pinned public
Final contract, then calls the official scorer and the existing M0 normalization
code. It emulates the documented runner; it does not certify private CodaBench
infrastructure, GPU behavior, or sealed Final scores.
See the [measured verification results](../reports/phase_m/RESULTS.md) and
[Phase M plan](../reports/phase_m/PLAN.md) for the checked digests and scope.

```sh
make mock-final \
  IMAGE=ghcr.io/hhwolf/agenthon-numeric-v1@sha256:25ffda44821a0493ba5ba69aeb570ec009a5e1081cd54d5e615fa3d51ac70a01 \
  UNITS=practice NETWORK=none

make mock-final \
  IMAGE=ghcr.io/hhwolf/agenthon-numeric-v1@sha256:25ffda44821a0493ba5ba69aeb570ec009a5e1081cd54d5e615fa3d51ac70a01 \
  UNITS=practice NETWORK=restricted \
  ARGS='--house-mode chaos --pull-policy always'

make mock-final \
  IMAGE=ghcr.io/hhwolf/agenthon-numeric-v1@sha256:25ffda44821a0493ba5ba69aeb570ec009a5e1081cd54d5e615fa3d51ac70a01 \
  COMPARE_IMAGE=ghcr.io/hhwolf/agenthon-numeric-v1@sha256:f3ec5167b28f0172004a78e336d84a4ecd423d27da42d942693e51cfc085c507 \
  UNITS=practice
```

Run from the repository root after `make setup`. Docker must be running with
linux/amd64 execution support. Restore proxy labels as described in
[EVALUATION_DATA.md](../reports/EVALUATION_DATA.md); if the published roster is
absent, the existing sibling-panel proxy builder runs automatically. Use
`--no-proxy-scores` for admissibility alone. No model-provider key is needed.
The runtime image build context remains unchanged: evaluation code, labels,
mock services, fixtures, and reports never enter the submission image.

`UNITS=practice` discovers all supplied units, including the exemplar: **104** in
the default release checkout or **126** in the isolated current checkout.
`UNITS=exemplar` selects one; a positive integer selects the first N sorted unit
directories. A request for more units than available is an error. `--units-root`
overrides the public unit directory. `--proxy-roster` supplies a JSON roster in
the existing evaluation format; relative realized paths resolve from this repo.
Use the [Final-alignment reproduction guide](../reports/final_alignment/REPRODUCE.md)
for the separate current-toolkit environment and `--units-root vendor/current/units`.

## Container execution and clock

Each unit is copied to an isolated input directory. A checksum manifest is
required and checked with the official verifier; unlisted files are rejected.
Root panel files are copied into `panels/`, matching organizer staging.
The entire directory is mounted at `/input:ro`. `/output` is writable by a
non-root image user. The root filesystem is read-only and `/tmp` is a 64 MiB
`noexec,nosuid` tmpfs. Only the staged input and output are mounted into the
solver. Realized outcomes and House state are never mounted into it.

Images must be immutable `name@sha256:digest`, linux/amd64, have the interface
2.0 label, and declare no Docker volumes. `--allow-local-image` resolves a local
tag to an immutable image ID for deliberate test fixtures only. The invocation
is the organizer's `forecast --panels /input/panels --text /input/text --asof
DATE --out /output/forecast.parquet`.

The CPU grant is `min(16, Docker-server CPUs)`. Memory is `min(128 GiB, 80% of
Docker-server memory)`, with swap disabled. The reserve leaves room for the
Docker daemon and mock services. These are local measurements, not estimates of
Final hardware speed. The two House helpers each have a separate 0.5 CPU/256 MiB
cap and are initialized before the ingestion clock, like an existing service.

The default deadline is 1,800 seconds from unit setup, including any requested
pull and container creation. A timeout kills the daemon's container before
inspecting outputs; terminating the Docker CLI alone would leave it running.
The remaining 43,200-second ingestion budget further limits each unit. Cleanup
and output checking are recorded in wall time. Official scoring runs only after
ingestion, on its separate clock.
Use `--timeout SECONDS` and `--platform-clock SECONDS` for shorter test budgets;
both must be positive and cannot exceed 1,800 and 43,200 seconds, respectively.

`--pull-policy missing` uses an existing local image or pulls the first time it
is needed. `always` performs a registry pull for the first unit even if cached.
Pull duration and the initial cache state are reported separately **and** pull
duration remains in that unit's wall time. A cached registry check is not called
a cold layer download. The runner never purges a user's image cache.

`QFBENCH_SEED` is always injected. By default it is the existing per-card CRC32
seed, honoring an inherited `QFBENCH_SEED`; `--seed` overrides it for all units.

## Restricted House

Offline execution uses Docker's `none` network. Restricted execution uses two
private `--internal` networks. The solver joins only the evaluation network.
The House server joins only the backend network. A forward proxy joins both,
forwarding solely to the fixed House backend. No ports are published on the
host. The solver cannot reach House directly or reach the internet.

The runtime receives uppercase and lowercase HTTP(S) proxy variables, loopback
`NO_PROXY`, `MODEL_ENDPOINT=http://house.internal:8000` (an origin without a
path), a fresh per-unit `MODEL_TOKEN`, `MODEL_NAME=house`,
`QFBENCH_NETWORK=restricted`, and the seed. The proxy rejects other origins and
CONNECT. This mock uses HTTP within its isolated Docker networks, rather than
emulating the production service's TLS deployment.

The only supported House operation is `POST /v1/chat/completions`. Missing or
invalid bearer credentials receive 401, a missing `/v1` prefix receives 403,
and `n` other than 1 is refused before admission. Omitted `max_tokens` becomes
4,000; larger values are clamped; smaller positive integers are preserved.
Each unit gets **25 admitted requests**, with atomic counters persisted before
upstream behavior. Upstream failures, timeouts, and replay misses consume a
request; invalid pre-admission requests do not. The token expires with the unit
deadline and is deactivated after exit. Retries do not reset counters.

Modes:

- `canned`: reuses the teammate's `tests/mock_house.py` extraction and synthesis
  responses. That original fixture remains unchanged.
- `chaos`: deterministic cycle of 503, delayed timeout, slow response, malformed
  wire JSON, malformed content JSON, and a normal canned response. Defaults are
  120 seconds for the timeout and 1 second for the slow response; tune with
  `--chaos-timeout` and `--chaos-slow` for short tests.
- `replay`: `--house-mode replay --replay-dir /path/to/cache` reads the teammate's
  `ResponseCache` files. It reconstructs the exact SHA256 key from unit ID,
  request parameters and the cached dev model, reversing the SDK's
  `extra_body.chat_template_kwargs` merge. A changed prompt or parameter is a
  miss and returns 503; there is no real provider fallback. Request hashes,
  matched cache hashes and hit/miss results are recorded without prompt text or
  bearer credentials.

Streaming and tool calls are not supported by this mock. Canned responses use
a documented four-character token estimate to simulate truncation; this is not
the production tokenizer. Replay verification in Phase M uses a synthetic
cache entry in the teammate's format, not real dev responses.

## Output rules and scoring

The checker walks the entire output tree without following links, including
empty directories. It enforces all rules in the pinned vendor README: at most
256 files, 4,096 total entries, seven nested folders, no symlinks/hardlinks or
special files, no special permission bits on files, 64 MiB per-file and total
limits, no heavily sparse files, and canonical UTF-8/NFC names without case
collisions, backslashes, controls or top-level drive-style prefixes. Host
filesystem semantics still apply; tests inject Linux-style case/Unicode names
to exercise those checks on case-insensitive macOS filesystems.

| Condition | Status | Score |
|---|---|---:|
| Unit/platform deadline | `resource_timeout` | 8.0 |
| Docker reports OOM kill | `resource_oom` | 8.0 |
| Other nonzero exit/start failure | `container_crashed` | 8.0 |
| Exit 0, refused tree or missing required file | `no_output` | 8.0 |
| Triplet exists but official gates reject it | `schema_invalid` | 8.0 |
| Official gates pass, proxy exists | `passed` | Official score / M0 expected error |
| Official gates pass, no proxy | `passed` | Unscored |

Crash/timeout takes precedence over output-tree contents. Oversized output from
a successful process is `no_output`, following the vendor's stated mapping.
Required files are `forecast.parquet`, `forecast_meta.json`, and
`forecast_rationale.md`. Scoring delegates to `t2eval.official.score`,
`t2eval.official.normalize`, and `t2eval.scales.expected_errors`; no new scoring
math is implemented.
Invalid source manifests, bad proxy labels, and official organizer/scorer faults
abort the harness rather than being charged to the submitted image.

Successful unlabeled units never receive invented numeric scores. The aggregate
mean includes resolved proxies and any failures; its denominator is explicit.
`proxy_mean`/`proxy_caps` also report the fixed proxy subset alone. These are
local proxy results, with inferred-date and revised-vintage limitations from
Phase 1; they are not sealed Final performance.

## Reports and verification

Outputs go to a new `.eval/mock-final/<run>/` directory. `--out PATH` sets a
fresh location; existing runs are never overwritten. Each image has
`summary.json`, `cards.json`, and `cards.csv`, plus per-unit input, output,
container logs, and ingestion records. Restricted runs include `house-stats.json`.
Credentials are kept in private ephemeral files, removed on completion, and
omitted from reports. Runtime-written container logs may contain whatever the
submitted image itself prints, so inspect those before sharing.

Summaries include status counts, requests, score denominators/means/caps, pull
time, sequential ingestion time, scoring time, host limits and image identity.
The selected roster's unit count determines the wall-time projection; it is flagged
if it exceeds **21,600 seconds**, half the platform clock. The legacy
`projection_104_seconds` field remains available. `vendor_commit` records the selected
input tree's Git revision, or null for standalone untracked inputs.
`COMPARE_IMAGE` runs the two digests sequentially with
the same unit roster, seed policy and network mode, and writes `COMPARISON.md`,
`comparison.csv`, and `comparison.json` with paired score/time/request rows.

```sh
.venv/bin/python -m pytest tests/test_mock_final.py tests/test_mock_final_audit.py tests/test_mock_house_service.py
.venv/bin/python scripts/verify_mock_final.py
```

The integration script builds deliberately broken local images, verifies all
four requested failure labels, and probes the real Docker network topology in
canned/chaos/replay modes. It leaves inspectable evidence under `.eval`, removes
its containers and networks, and neither publishes fixtures nor packs/uploads
a competition submission. Run the full image sweeps separately with the Make
commands above. The default pytest suite needs no Docker daemon.
