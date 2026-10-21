# Track 2 final release — numeric_v1.1 + card-notes λ0.5 (stopped before pack)

Date: 2026-10-20. Status: **published, verified, Greptile-reviewed, descriptors ready. Not packed, not uploaded.**

## Identity

| Item | Value |
|---|---|
| **Final image** | `ghcr.io/hhwolf/agenthon-numeric-v1@sha256:400fe71078d8f9e3e7859da3402ec7866a531760c14b1c0bc795e8e71db0d674` |
| Source commit / tag | `f680ca656c3ce889f3277defd248b2e0ad4e0e0a` / `final-20261020-1` (image label `org.opencontainers.image.revision` = same commit) |
| CI run | [Publish final forecasting image #39382405566](https://github.com/hhwolf/agenthon/actions/runs/39382405566): 244 tests, prepare_final --check, 104/104 admissibility (max 0.675 s), amd64 build, `/app/LICENSE` check, offline 104/104, GHCR push, anonymous pull |
| PR | [#9](https://github.com/hhwolf/agenthon/pull/9) → main (not merged) |
| Configuration | `t2agent/text_config.json`: `card_notes_only`, λ = 0.5, `house_calls: false`; `reports/phase5/release.json` frozen (30 runtime/build SHA-256s) |
| Descriptor models / license | `models: []`; `MIT` (LICENSE in repo **and** at `/app/LICENSE` in the image; OCI `licenses=MIT` label; PEP 639 pyproject; README) |
| **Fallback image** | `ghcr.io/hhwolf/agenthon-numeric-v1@sha256:f3ec5167b28f0172004a78e336d84a4ecd423d27da42d942693e51cfc085c507` (numeric_v1.1; `submission.fallback.json` unchanged) |
| Superseded final (still public, not deleted) | `…@sha256:a197cfe0e065f6ddef7696fa0ad261b0a31d08259769b5040fc1176a63428bed` (`final-20261019-1`, `fd4f11a`): identical forecasts, no LICENSE in the image. Evidence in `superseded-a197cfe0/` |

## Why the digest changed

Greptile's only remaining finding was "Image lacks its license" (P2). The fix copies `LICENSE` into the image and
adds an OCI label. No `t2agent` file changed. The predicted forecast impact was none, and that is what we measured:
a local build first produced 312/312 identical files on all 104 units versus `a197cfe0`, and the published
`400fe710` reproduces **every** output file of the `a197cfe0` verification byte for byte (8 sweeps: 2,496/2,496;
audit seed variants: 936/936).

## Digest equality: PASS

`submission.final.json` = CI `publication.json` = CI `submission.json` artifact = CI anonymous-pull check =
verifier report = all 8 sweeps = 3 audit-variant sweeps = local cold pull, i.e. 17 sources, one digest
(`digest-equality.json`). The final descriptor equals the CI-generated one (sorted JSON).

## Results on `400fe710`

| Check | Result | Evidence |
|---|---|---|
| Tests | 244 passed locally and in CI | CI log |
| House disabled by config | live listener: **0** connections with `MODEL_*` set and `TEXT_LAYER_MODE=labels`; positive control (`house_calls=true` mounted) 2 | `egress-check.json` |
| Cold pull | `image prune -a` + `builder prune -a` (0 B left), empty `DOCKER_CONFIG`: **4.64 s**, 10/10 layers downloaded, 0 reused. The registry CDN was warm after CI; `a197cfe0`'s first cold pull took 42.64 s. The verifier's first sweep pulled cold again in 4.82 s | `cold-pull.json` |
| Mock Final, 8 sweeps (`t2eval.final_release`, seeds 20261016/20261017) | **104/104 in all 8**; 0 House requests; unit wall mean 1.73–1.80 s, max 7.28 s (incl. pull); max output 424,848 B / 3 files | `reports/phase5/verification.json` |
| Same-seed reruns | offline and replay repeats: forecasts, metadata, rationales byte-identical 104/104 | verification.json |
| Fresh seed | 2.382360 vs 2.382383; each inside the other's year-block 95% CI; paired Δ +0.00002, CI [−0.0133, +0.0106]; 104/104 forecasts changed | verification.json |
| Audit seed variants | per-card default **2.378141**, seed 1111 **2.379504**, seed 2222 **2.389690**; 9 caps each | `mock-final-audit-variants.json` |
| Wall clock | ≤ 187 s projected per 104 units = **0.43% of 43,200 s** | verification.json |
| Descriptors | final and fallback: schema 1.1.0, interface 2.0, forecasting / final / api / public, `models: []`, `MIT`; pass toolkit 2.6.0 fixture/sealer/C5 parser/JSON schema and `pack`'s `seal_for_team` path (throwaway in-memory key, no zip) | `descriptor-validation.json` |

Replay sweeps use an empty replay directory: with zero House requests they are network-mode checks, not
model-cache evidence.

## Greptile review

| Round | Commit | Score | Findings |
|---|---|---|---|
| 1 | `9668c63` | 4/5 | (1) image lacks license, (2) audit scripts not portable, (3) docs label example stays offline. All P2 |
| 2 | `ffa67d1` | 5/5 | (2) and (3) fixed; (1) listed as non-blocking |
| 3 | `5061f0f` | **5/5** | none; (1) confirmed fixed |

## Commands

```sh
git checkout final-20261020-1
make test
.venv/bin/python scripts/prepare_final.py --check
git tag -a final-20261020-1 f680ca6 && git push origin final-20261020-1                    # CI publishes
export DOCKER_HOST=unix://$HOME/.colima/agenthon/docker.sock DOCKER_CONFIG=$(mktemp -d)
docker image prune -a -f && docker builder prune -a -f
time docker pull ghcr.io/hhwolf/agenthon-numeric-v1@sha256:400fe71078d8f9e3e7859da3402ec7866a531760c14b1c0bc795e8e71db0d674
docker image rm ghcr.io/hhwolf/agenthon-numeric-v1@sha256:400fe710…   # verifier's first sweep pulls cold
.venv/bin/python -m t2eval.final_release --image ghcr.io/hhwolf/agenthon-numeric-v1@sha256:400fe71078d8f9e3e7859da3402ec7866a531760c14b1c0bc795e8e71db0d674 \
  --replay-dir EMPTY_DIR --out .context/release2/mock
make mock-final IMAGE=…@sha256:400fe710… UNITS=practice NETWORK=none ARGS='--proxy-roster .eval/runs/eval-practice-m0-b158bfdafa1a/roster.json'   # + --seed 1111 / 2222
```

## Human handoff (not run by the agent)

```sh
.venv/bin/qfbench2 submission pack --descriptor submission.final.json --team-number <N> --out submission.zip
# fallback only if the final digest becomes unusable:
.venv/bin/qfbench2 submission pack --descriptor submission.fallback.json --team-number <N> --out submission.zip
```

Team number on record: 756. The toolkit prompts for the Team Key privately. Keep the GHCR package public
through results.

## Release protection (until results are published)

- **No GHCR version of `ghcr.io/hhwolf/agenthon-numeric-v1` may be deleted, untagged or made private until
  final results are published.** Organizers re-pull the submitted digest for verification reruns. This covers
  all three release digests: final `400fe710…`, secondary fallback `a197cfe0…` and fallback `f3ec5167…`.
  GHCR has no deletion lock, so this is a team rule.
- GitHub ruleset `protect-final-release-tags` (id 25516830, active, no bypass actors) blocks deletion,
  update and force-push of `refs/tags/final-*`; new `final-*` tags can still be created.
- Upload steps for the human: [UPLOAD_CHECKLIST.md](UPLOAD_CHECKLIST.md).

## Open items

- PR #9 was merged on 2026-10-21 as `0baf535` after Greptile scored head `face303` 5/5 with all checks green.
- PR #8 (LLM labels as image default) contradicts this release; it was not touched.
- Model risks are unchanged from `reports/audit/AUDIT.md` (monthly macro 2022, F4 caps, EM transfer unmeasured).
