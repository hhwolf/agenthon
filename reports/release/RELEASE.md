# Track 2 final release — numeric_v1.1 + card-notes λ0.5 (stopped before pack)

Date: 2026-10-20. Status: **published, verified, descriptors ready. Not packed, not uploaded.**

## Identity

| Item | Value |
|---|---|
| **Final image** | `ghcr.io/hhwolf/agenthon-numeric-v1@sha256:a197cfe0e065f6ddef7696fa0ad261b0a31d08259769b5040fc1176a63428bed` |
| Source commit / tag | `fd4f11a88648a64249415839ea44ac8dd1c794ab` / `final-20261019-1` (image label `org.opencontainers.image.revision` = same commit) |
| CI run | [Publish final forecasting image #39366143060](https://github.com/hhwolf/agenthon/actions/runs/39366143060): 243 tests, prepare_final --check, 104/104 admissibility (max 0.437 s), amd64 build, offline 104/104, GHCR push, anonymous pull |
| PR | [#9](https://github.com/hhwolf/agenthon/pull/9) → main (not merged; awaiting grep = 5) |
| Configuration | `t2agent/text_config.json`: `card_notes_only`, λ = 0.5, `house_calls: false`; `reports/phase5/release.json` frozen with 30 runtime/build SHA-256s |
| Descriptor models / license | `models: []`; `MIT` (LICENSE, pyproject PEP 639, README) |
| **Fallback image** | `ghcr.io/hhwolf/agenthon-numeric-v1@sha256:f3ec5167b28f0172004a78e336d84a4ecd423d27da42d942693e51cfc085c507` (numeric_v1.1, published 2026-10-15; anonymous pull re-checked 2026-10-20) |

## Digest equality (step 9): PASS

`submission.final.json` = CI `publication.json` = CI `submission.json` artifact = CI anonymous-pull check =
all 8 verifier sweeps = 3 audit-variant sweeps = local cold pull, i.e. 17 sources, one digest
(`digest-equality.json`). The final descriptor is byte-equivalent (sorted JSON) to the descriptor CI generated.

## Results

| Check | Result | Evidence |
|---|---|---|
| Tests | 243 passed locally and in CI (2 new tests; each fails when its fix is reverted) | CI log |
| Eval tooling fix | numeric-only and card-notes now get separate run directories; reruns **2.415744** (numeric_v1.1) and **2.378141** (card-notes), Δ = 0 vs frozen per-card CSVs | BUILD_LOG |
| House disabled by config | unit test (socket-level connect counter + mock House): 0 attempts with `MODEL_*` set for default, `text_mode='labels'` and `TEXT_LAYER_MODE=labels`. **Image level:** live listener saw **0** connections; positive control with `house_calls=true` mounted saw 2 | `egress-check.json` |
| Truly cold pull | after `docker image prune -a` + `docker builder prune -a` (0 B left), empty `DOCKER_CONFIG`: **42.64 s**, 9/9 layers downloaded, 0 reused, 139.8 MB | `cold-pull.json` |
| Mock Final, eight sweeps (`t2eval.final_release`, seeds 20261016/20261017) | **104/104 in all 8**; 0 House requests; first sweep pulled cold inside the clock (56.0 s; unit max 58.6 s); otherwise mean 1.77–1.86 s, max ≤ 2.30 s per unit; max output 424,848 B / 3 files | `reports/phase5/verification.json` |
| Same-seed reruns | offline vs offline-repeat and replay vs replay-repeat: forecasts, metadata **and** rationales byte-identical (104/104) | verification.json `determinism` |
| Fresh seed | 2.382360 vs 2.382383; each inside the other's year-block 95% CI ([1.732, 3.202] / [1.734, 3.202]); paired Δ +0.00002, CI [−0.0133, +0.0106]; 104/104 forecasts changed | verification.json `seed_stability` |
| Audit seed variants | per-card default **2.378141**, seed 1111 **2.379504**, seed 2222 **2.389690** (identical to the audit); all 9 caps; outputs 312/312 byte-identical to the audited candidate image | `mock-final-audit-variants.json` |
| Wall clock | worst sweep incl. cold pull: 242 s projected for 104 units = **0.56% of 43,200 s**; warm ≈ 190 s | verification.json |
| Descriptors | both: schema 1.1.0, interface 2.0, forecasting / final / api / public, `models: []`, `MIT`; pass the toolkit 2.6.0 fixture/sealer/C5 parser/JSON schema **and** `pack`'s own `seal_for_team` path (throwaway in-memory key, no zip written) | `descriptor-validation.json`, `ci-descriptor-validation.json` |
| Fallback | anonymous manifest + all blobs HTTP 200, empty-config pull passes, amd64, user `runner` | `anonymous-pull-fallback.json` |

Replay sweeps use an empty replay directory: with zero House requests they are network-mode checks, not
model-cache evidence (no LLM layer ships).

## Commands

```sh
git checkout final-20261019-1
make test
.venv/bin/python scripts/prepare_final.py --check
TEXT_LAYER_MODE=numeric_only .venv/bin/python -m t2eval.cli eval-practice --forecaster numeric_v1_1 --work W   # 2.415744
.venv/bin/python -m t2eval.cli eval-practice --forecaster numeric_v1_1 --work W                                # 2.378141
git tag -a final-20261019-1 fd4f11a && git push origin final-20261019-1                                         # CI publishes
export DOCKER_HOST=unix://$HOME/.colima/agenthon/docker.sock DOCKER_CONFIG=$(mktemp -d)
docker image prune -a -f && docker builder prune -a -f
time docker pull ghcr.io/hhwolf/agenthon-numeric-v1@sha256:a197cfe0e065f6ddef7696fa0ad261b0a31d08259769b5040fc1176a63428bed
docker image rm ghcr.io/hhwolf/agenthon-numeric-v1@sha256:a197cfe0…   # so the verifier's first sweep is cold
.venv/bin/python -m t2eval.final_release --image ghcr.io/hhwolf/agenthon-numeric-v1@sha256:a197cfe0e065f6ddef7696fa0ad261b0a31d08259769b5040fc1176a63428bed \
  --replay-dir EMPTY_DIR --out .context/release/mock
make mock-final IMAGE=…@sha256:a197cfe0… UNITS=practice NETWORK=none ARGS='--proxy-roster .eval/runs/eval-practice-m0-b158bfdafa1a/roster.json'   # + --seed 1111 / 2222
```

## Human handoff (not run by the agent)

```sh
.venv/bin/qfbench2 submission pack --descriptor submission.final.json --team-number <N> --out submission.zip
# fallback only if the final digest becomes unusable:
.venv/bin/qfbench2 submission pack --descriptor submission.fallback.json --team-number <N> --out submission.zip
```

Team number on record: 756. The toolkit prompts for the Team Key privately; never share it. Keep the GHCR
package public through results.

## Open items

- **grep review:** PR #9 has no grep score yet. Per the team rule, do not merge until it scores 5. If grep
  requires runtime changes, a new `final-*` tag, digest and full verification are needed.
- **PR #8** (Aiden) makes LLM labels the image default. It contradicts this release and conflicts with it.
  Do not merge it before Final unless the team deliberately reverses this decision and re-verifies.
- Known model risks are unchanged from `reports/audit/AUDIT.md`: monthly macro 2022, F4 caps, unmeasured EM transfer.
