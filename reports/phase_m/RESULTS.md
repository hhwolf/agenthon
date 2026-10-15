# Phase M: mock Final verification

The published numeric_v1 digest passes all **104 units offline and restricted**,
with **zero House requests**. All four requested failure labels were reproduced
with deliberately broken Docker images and scored 8.0. The comparison image,
numeric_v1.1, also passes all 104 units offline.

| Image / network | Admissible | Requests | Proxy mean (88) | Caps | Sequential ingestion | Pull included |
|---|---:|---:|---:|---:|---:|---:|
| numeric_v1 / offline | 104/104 | 0 | 2.435741 | 9 | 145.07 s | 0.189 s |
| numeric_v1 / restricted | 104/104 | 0 | 2.435741 | 9 | 159.89 s | 0.500 s |
| numeric_v1.1 / offline | 104/104 | 0 | 2.415744 | 9 | 157.31 s | 0.210 s |

Sixteen units (including the exemplar) have no proxy outcome and remain
unscored after passing admissibility. These are local proxy scores, not sealed
Final results. No inference code or frozen numeric configurations were changed.
The numeric_v1 image's measured mean differs slightly from the earlier native
Phase 2 run; this report scores the actual published Linux image outputs.

## Image identities

- numeric_v1: `ghcr.io/hhwolf/agenthon-numeric-v1@sha256:25ffda44821a0493ba5ba69aeb570ec009a5e1081cd54d5e615fa3d51ac70a01`
- numeric_v1.1: `ghcr.io/hhwolf/agenthon-numeric-v1@sha256:f3ec5167b28f0172004a78e336d84a4ecd423d27da42d942693e51cfc085c507`
- Pinned vendor commit: `b9c663d239a0e6b86ebd3f3f2d5aead88516067d`.
- Runtime/scoring implementation: `t2eval/mock_final.py`,
  `t2eval/mock_house_service.py`, and the existing official/scales adapters.
  Run reports include the source checkout identity; newer reports also include
  exact harness source hashes and a dirty-checkout flag. Initial local sweeps
  preceded the implementation commit; Linux CI verifies the committed version.

## Runtime and network checks

The local Docker server had 4 CPUs and 7.74 GiB RAM;
the solver received 4 CPUs and 6.19 GiB, swap disabled.
Each unit used amd64, read-only root, read-only staged input with panels/,
writable output and a 64 MiB tmpfs. Manifest validation refuses extra or altered
inputs. Outcomes and helper credentials were absent from the solver mounts.

The slowest projected 104-unit sweep was 159.85 seconds,
well below the **21,600-second warning threshold** (half the 43,200-second
platform clock). Official scoring was timed separately. These local timing
measurements are not a Final hardware performance guarantee. All local images
were initially cached: registry pulls were measured, but no local pull is
claimed to be a cold layer download. The CI offline sweep starts from a fresh
host and reports its actual cache state/pull time.

All **104 output triplets and staged input fingerprints match exactly**
between numeric_v1 offline and restricted runs, as do the scores. The largest
numeric_v1 output tree is 418,931 bytes (0.400 MiB), below 64 MiB.

Actual Docker probes verify both networks are internal, House has no published
host port, direct House/internet access is blocked, only the forward proxy can
reach House, foreign origins and CONNECT are refused, and admission requires
the unit bearer token and correct route. The canned probe admits 25 requests
and refuses request 26; pre-admission failures spend no budget. Chaos consumes
six requests across 503/timeout/slow/malformed-wire/malformed-content/success.
Replay consumes two requests for one exact cache hit and one charged 503 miss.
All 27 probe assertions passed. Replay uses a synthetic entry in the teammate's
exact dev-cache format; no real cached dev responses were available.

## Deliberately broken images

| Fixture | Observed status | Score |
|---|---|---:|
| Exit 17 after partial output | `container_crashed` | 8.0 |
| Sleep beyond a 1-second test deadline | `resource_timeout` | 8.0 |
| Write 64 MiB + 1 byte, then exit 0 | `no_output` | 8.0 |
| Invalid parquet with the required triplet present | `schema_invalid` | 8.0 |

Oversized output maps to `no_output` under the pinned vendor README. Crash and
timeout take precedence over tree validity. OOM handling also has regression
coverage. Input/manifest faults and official organizer/scorer errors abort the
harness; they never inflate an image's failure count.

## Tests, evidence and reproduction

- **139 tests passed** locally, including boundary/deadline/admission/replay and
  failure-attribution regression tests; 12 existing M0 warnings remain.
- [Digest comparison](COMPARISON.md), [paired cards](comparison.csv), and
  [Docker probe/failure evidence](verification.json).
- Per-image summary JSON and card CSV files are in this directory. Full staged
  inputs, outputs and logs remain under `.eval/mock-final/` and are gitignored.
- [Usage and contract details](../../docs/MOCK_FINAL.md).
- `.github/workflows/mock-final.yml` repeats tests, Docker probes/failures, and
  all 104 numeric_v1 units in both network modes on a Linux runner. It uses
  admissibility-only scoring there; local proxy comparison uses restored .eval.

```sh
make mock-final IMAGE=<numeric_v1 digest above> UNITS=practice NETWORK=none ARGS='--pull-policy always'
make mock-final IMAGE=<numeric_v1 digest above> UNITS=practice NETWORK=restricted ARGS='--pull-policy always'
make mock-final IMAGE=<numeric_v1 digest above> COMPARE_IMAGE=<numeric_v1.1 digest above> UNITS=practice
.venv/bin/python scripts/verify_mock_final.py
make test
```

Reused the existing teammate `tests/mock_house.py`; no replacement was needed.
No competition submission was packed or uploaded, and no new model image was
published as part of this evaluation-only phase.
