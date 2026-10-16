# Final image and human submission handoff

Phase 5 uses the existing mock Final harness and official scoring adapter. Its
protocol is [reports/phase5/VALIDATION.md](../reports/phase5/VALIDATION.md).
The current release is **pending**, not a published or verified Final image.
The Phase 3 branch now reports a successful dev sweep, but its raw cache and
per-unit labels have not been shared in this workspace. Its comparison uses
numeric_v1, whereas the integrated Phase 4 comparison uses numeric_v1.1.

## Freeze and publish

Complete the Phase 4 replay comparison using the real teammate cache. Resolve
the code license, write LICENSE, update the selected runtime text config, and
freeze the mode, lambda, license, every runtime Python/JSON SHA256, and the
Dockerfile, runtime requirements, .dockerignore and LICENSE SHA256 in
`reports/phase5/release.json`. `scripts/prepare_final.py --check` refuses a
pending release, a changed runtime or a missing license. Do not put caches or
practice data in t2agent or the image.

The `final-*` tag workflow tests the frozen tree, checks all 104 offline outputs,
builds linux/amd64, and pushes `ghcr.io/hhwolf/agenthon-numeric-v1:<final-tag>`.
It checks the immutable digest with the existing anonymous manifest/blob check
and a fresh empty Docker credential configuration. It retains the digest and
pack input as the `final-publication` Actions artifact. The package must remain
public until results. No workflow calls `submission pack` or CodaBench.

## Verify the published digest

Run with an empty Docker credential configuration and an explicit Docker host
so that the workstation's current context does not hide credential use. The
first sweep must find the final image absent locally; do not run the separate
anonymous pull script first on this daemon. Use a separate fresh daemon if the
image is already present. Shared base layers may still be cached and this is
recorded rather than described as a full cold layer download.

```sh
.venv/bin/python -m t2eval.final_release \
  --image ghcr.io/hhwolf/agenthon-numeric-v1@sha256:ACTUAL_DIGEST \
  --replay-dir /path/to/llm_cache --uses-house
```

Omit `--uses-house` only when the frozen configuration sends no model requests.
For a model-free choice, replay is a zero-request network-mode check, not
evidence of model cache coverage. Each underlying invocation is equivalent to
`make mock-final IMAGE=... UNITS=practice NETWORK=... ARGS=...`.

The eight sweeps check the four modes, same-seed offline/replay repeats, and
fresh-seed offline/replay runs. The verifier rejects missing cache requests,
duplicate/missing units, wrong digests/seeds, timing/request/output violations,
nonidentical output triplets and unstable proxy means. Request seeds stay fixed;
fresh QFBENCH_SEED changes numeric sampling, not dev model responses.

Rationales omit elapsed-time values and sort concurrent request entries to make
their bytes reproducible. Harness reports retain measured timing. The proxy
scores still use the official scorer and M0 normalization. The final report is
`reports/phase5/verification.json`; full outputs remain gitignored under `.eval`.

## Descriptor and October 23 handoff

```sh
.venv/bin/python scripts/prepare_final.py --image IMAGE_BY_DIGEST --team-id PUBLIC_TEAM_ALIAS
```

This starts from the toolkit's forecasting_final fixture, uses schema 1.1.0 and
interface 2.0, records the license and conditional House disclosure, and seals
and validates using toolkit functions plus its JSON schema. It does not pack.
If the public alias is omitted, `submission.json` is a pack input without
team_id/descriptor_digest. Validation then uses an explicitly marked temporary
in-memory alias; the on-disk input is not claimed to be a fully sealed C5 file.
Do not insert a fake team alias: the pack command refuses one that disagrees
with the real team number/key.

On the user's planned October 23 date, the human runs:

```sh
.venv/bin/qfbench2 submission pack --descriptor submission.json --team-number N --out submission.zip
```

The toolkit prompts privately for the Team Key, derives the alias, reseals the
descriptor, and creates the team proof. The human uploads to CodaBench Final.
Never send the Team Key to this agent or store it in the repository. Keep the
image public through results, including organizer reruns after Final closes.

Official references checked 2026-10-16:
[descriptor](https://github.com/Agenthon-2026/Agenthon2026-public/blob/main/starter-packs/track2/SUBMISSION-DESCRIPTOR.md),
[House identity](https://github.com/Agenthon-2026/Agenthon2026-public/blob/main/docs/HOUSE-MODEL.md),
[public image policy](https://github.com/Agenthon-2026/Agenthon2026-public/blob/main/docs/IMAGE-SUBMISSIONS.md).
Evaluation remains pinned to toolkit 2.6.0 for comparison consistency; the
organizer's current installation examples use 2.6.1. Do not silently change
scoring versions during the release.
