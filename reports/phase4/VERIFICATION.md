# Phase 4 verification

Code: `43a7a32` on `hhwolf/phase4-text-integration`. This is local verification;
no Phase 4 image or submission has been published. The full model-label accuracy
comparison is still unavailable because the 88 dev-label artifacts are missing.

- Full suite: **224 passed**, 15 existing M0/NumPy warnings, 22.81 seconds.
- Final host admissibility: **104/104**, 2,000 draws; maximum forecast time 0.424 s.
- Final linux/amd64 image matches all **26 runtime Python/JSON files** exactly.
- Wheel includes text_config.json. Runtime dependency remains openai==3.31.0.
- Image excludes t2eval, vendor, evaluation outcomes and parquet inputs.
- Protected Phase 2 config/selection and numeric_v1.1 numeric config are unchanged.

| local container check | passed | requests | proxy mean | caps | ingestion seconds |
|---|---:|---:|---:|---:|---:|
| final build, offline | 104/104 | 0 | 2.378141 | 9 | 194.24 |
| card-notes build, restricted | 104/104 | 0 | 2.378141 | 9 | 199.52 |
| final build, restricted exemplar | 1/1 | 0 | not scored | — | 2.58 |
| final build with explicit labels mode, restricted canned House | 1/1 | 4 | not scored | — | 2.77 |

The 104-unit restricted run predates the rise-versus-hold branch correction;
**all 104 forecast.parquet and forecast_meta.json files are byte-identical**
to the final build's offline outputs. The correction affects nonzero model-label
branch shifts, not the card-only pre-pass's zero branch shifts. Current-build
restricted smoke checks cover both the selected card-notes mode and explicit
labels mode. The latter confirms mapping and the evidence ledger after four
mock requests; canned responses are not accuracy evidence.

All card-notes rationales confirm the selected mode without a silently ignored
text hook. The largest output triplet is **424,862 bytes** (well below 64 MiB).
Tests cover neutral draw identity, zero-lambda/no-request behavior, text failure
recovery, shared branch signs across assets/horizons, opposing and rise/hold
binary branches, disagreement, asymmetric adverse tails, inferred-evidence width
floors, evidence writing, replay provenance rejection and the decision rule.

Local final image ID:
`sha256:69a30bf26d5d6e18ed494ac80e806e717f140aac7ee15a666d2dc735faa7a546`.
The other image IDs, host resource limits, input/source provenance and exact
statistics are in [verification.json](verification.json). The image IDs are
local identifiers, not published registry digests. Docker tests use the mock
Final runner's read-only input/root, writable output, tmpfs, amd64 platform,
resource caps and restricted proxy network.

The first offline attempt was invalidated when a local rebuild replaced its
image reference after 44 units. Its 60 image-unavailable starts are excluded
from accuracy evidence; the final immutable-reference run passed all 104.
The failed attempt remains under `.eval/mock-final/phase4-none/` for audit.

Full outputs remain under `.eval/mock-final/phase4-final-none/`,
`.eval/mock-final/phase4-restricted/`, `phase4-final-restricted-exemplar/`, and
`phase4-final-labels-canned/`. `.github/workflows/phase4.yml` reproduces tests,
host admissibility and both full 104-unit network sweeps for the current image
when the branch is submitted to CI. That workflow has not run remotely yet.

The only GitHub release assets are the earlier evaluation archive; Actions
has no cached-label artifacts, and the teammate's remote branch remains at
`61b3d75343622668d57c4e4a7122cef5144bbf06`. Supply the dev-label directory to
`t2eval.phase4 --labels-dir PATH` to complete the two remaining accuracy arms.
