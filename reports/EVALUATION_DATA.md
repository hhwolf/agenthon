# Published evaluation data

The complete local `.eval/` snapshot from October 14, 2026 is published with
[release v0.1.0.0](https://github.com/hhwolf/agenthon/releases/tag/v0.1.0.0).

- [Evaluation archive](https://github.com/hhwolf/agenthon/releases/download/v0.1.0.0/agenthon-track2-evaluation-2026-10-14.tar.gz)
- [Per-file manifest](https://github.com/hhwolf/agenthon/releases/download/v0.1.0.0/agenthon-track2-evaluation-2026-10-14.manifest.json)
- [SHA-256 checksums](https://github.com/hhwolf/agenthon/releases/download/v0.1.0.0/SHA256SUMS)

Archive size: 446,455,832 bytes (426 MiB compressed); file contents total
605,353,825 bytes (577 MiB before compression). Filesystem allocation accounts
for the larger 733 MiB local directory measurement.

Archive SHA-256:
`a0f2de2294acec6fef9eea5f0ebf15cd2d4b656f605c596612d36ba5d3a1697b`.

The archive contains all 55,005 generated files: donor and union panels with
provenance, synthetic cards and truncated input panels, realized outcomes,
practice labels, forecasts and rationales, official score verdicts, rosters,
CSV/JSON reports, and the repeated-outcome calibration diagnostic. Preliminary
and debug runs are included; use the final run IDs listed in
[BUILD_LOG.md](../BUILD_LOG.md) for the published baseline numbers.

These are local evaluation artifacts. Practice outcomes include inferred target
dates, historical macro values include revisions, and some synthetic EM shapes
use G10 substitutes. Read [the result limitations](../BUILD_LOG.md#decisions-and-ambiguities)
before comparing scores. The archive is excluded from the inference image.

## Restore the snapshot

From a repository checkout, download the three assets into a temporary directory:

```sh
snapshot_dir=$(mktemp -d)
gh release download v0.1.0.0 --repo hhwolf/agenthon --dir "$snapshot_dir" \
  --pattern 'agenthon-track2-evaluation-2026-10-14.*' --pattern SHA256SUMS
(cd "$snapshot_dir" && shasum -a 256 -c SHA256SUMS)
```

Extract only if the checkout does not already have an `.eval/` directory:

```sh
if [ -e .eval ]; then
  echo '.eval already exists; preserve it or use a fresh checkout.'
else
  tar -xzf "$snapshot_dir/agenthon-track2-evaluation-2026-10-14.tar.gz"
fi
```

The archive restores relative `.eval/...` paths. The manifest records each file's
path, byte count, and SHA-256 hash. Install the pinned vendor checkout and Python
dependencies with `make setup` before rerunning evaluation commands. Existing
reports can be read without those dependencies.
