# Phase 5 status — 2026-10-16

**Prepared, not published. No final tag, final digest, or submission.json exists yet.**

Implemented:

- `final-*` CI workflow: frozen configuration check, full tests, host and image
  offline admissibility, amd64 build/push, anonymous manifest/blob and logged-out
  pull check, descriptor generation, publication artifact.
- Eight-sweep verification using the existing mock Final and official scorer:
  all four modes, offline/replay repeats and fresh seeds; timing, request, size,
  roster, image and replay-hit gates; exact three-file equality; paired year-block
  bootstrap stability checks over the 88 proxies.
- Toolkit fixture/parser/sealer integration, conditional official House row,
  and truthful distinction between a team-unbound pack input and a sealed C5.
- Deterministic rationale rendering, with timing retained in harness reports.

Local preflight evidence (not certification of a published Final digest):

- **241 tests passed**, 15 existing NumPy/M0 warnings.
- **104/104 host admissibility** for the provisional card-notes configuration.
- linux/amd64 build succeeded; no runtime numeric/config changes.
- Repeated offline exemplar: all three files byte-identical, zero requests.
- Repeated labels+canned exemplar: all three files byte-identical, four requests
  each. Canned responses are fixtures, not accuracy or real-cache evidence.

Independent coverage and plan audits found a missing CI scratch directory,
concurrent note ordering, incomplete build-input freeze, and missing orchestration
coverage. These were corrected and regression-tested before committing.

Required inputs and remaining work:

1. Obtain `.eval/text_signals/` for the 88 proxies and `.eval/llm_cache/` covering
   all 104 units, including genuine malformed replies. The new Phase 3 commit
   `2d6601e` reports 100/104 labelled and recommends lambda 0.5, but only its
   BUILD_LOG was pushed. No cache artifact/release asset was found. Its accuracy
   results use numeric_v1 and the earlier mapping, not this integrated version.
2. Complete the integrated Phase 4 comparison and freeze the final mode/config.
   Recorded parse failures must be distinguished from missing cache; do not
   manufacture neutral labels to fill absent data.
3. Obtain the user's code-license choice; the repository currently has none.
   A public derived team alias is optional: without it, human pack derives and
   seals the descriptor. No Team Key is requested or handled by this workflow.
4. Publish through a final-* tag, verify anonymous access and all eight sweeps
   on that exact digest, and write actual submission metadata/verification.

No final publication or full-matrix pass is claimed. The earlier public numeric
images are unchanged. No competition pack/upload was run. The human's planned
October 23 handoff is documented in [FINAL_RELEASE.md](../../docs/FINAL_RELEASE.md).
