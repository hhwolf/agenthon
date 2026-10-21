# Reproduce the Final-alignment comparison

Run from this branch's repository root with Python 3.13 and Docker. All `.eval/`, `.context/`,
`vendor/` and isolated environments are ignored and excluded from the image. Commands below
are local research/verification; none packs, uploads, publishes or accesses a Team Key.

## Environments and old reference

Restore the original evaluation snapshot into a separate checkout using
[the existing restore instructions](../EVALUATION_DATA.md). Run `bash scripts/setup.sh` there
to obtain the old pinned vendor and common 2.6.0 environment. Set `alignment_old_root` to that
checkout; it must contain the original 88-card roster and `.eval/practice/` labels.

```sh
alignment_old_root=/absolute/path/to/restored-old-checkout
mkdir -p .context vendor
# On a fresh checkout; keep any existing correctly pinned old vendor tree.
ln -s "$alignment_old_root/vendor/track2" vendor/track2
bash scripts/setup_final_alignment.sh
# Keep the original environment separate; this link is local and gitignored.
ln -s "$alignment_old_root/.venv" .venv-release

PYTHONPATH=. .venv-release/bin/python scripts/alignment_scorer_fixture.py > .context/scorer-old.json
PYTHONPATH=. .venv-current/bin/python scripts/alignment_scorer_fixture.py > .context/scorer-current.json
.venv-release/bin/python -m t2eval.final_alignment old \
  --old-root "$alignment_old_root" --units-root "$alignment_old_root/vendor/track2/units" \
  --out .eval/final_alignment/old-reference-v2 --arms release --crc32 --normalization release
```

Expected mean: **2.378140819619285** within floating-point tolerance, **9 caps**.
The scorer fixture JSON has different common version labels but identical `rows` arrays.
The complete release-env test suite runs with `.venv-release/bin/python -m pytest`.
Current-env new-path/scorer tests run with
`.venv-current/bin/python -m pytest tests/test_final_alignment.py tests/test_alignment_review.py`.
Two old CLI tests intentionally require common 2.6.0; do not weaken that guard to run them under 2.6.1.

## Historical construction, three arms, freeze, confirmation

The original PLAN and selection commits are `7a0e891` and `dc223e2`. A replication is already
answer-exposed research; it does not recreate a fresh blinded experiment. Use new output paths
if a directory exists. The tools refuse to overwrite selection or confirmation evidence.

```sh
.venv-current/bin/python -m t2eval.final_alignment build --out .eval/final_alignment/data
.venv-current/bin/python -m t2eval.final_alignment develop \
  --data .eval/final_alignment/data --out .eval/final_alignment/development-v3 --workers 2
.venv-current/bin/python -m t2eval.alignment_selection select \
  --development .eval/final_alignment/development-v3 \
  --frozen .eval/final_alignment/replication-selection.json
# Inspect/commit the replication freeze before the following command. Do not overwrite the tracked freeze.
.venv-current/bin/python -m t2eval.alignment_selection confirm \
  --frozen .eval/final_alignment/replication-selection.json \
  --development .eval/final_alignment/development-v3 --out .eval/final_alignment/confirmation
.venv-current/bin/python -m t2eval.final_alignment old \
  --old-root "$alignment_old_root" --out .eval/final_alignment/old-regression \
  --arms release B compatibility
```

Expected roster: **1,158** cases, development **738**, report-only **420**. Seeds are fixed at
1111/2222/3333, 2,000 draws. The **recorded original outcome** selected B and returned
**NO-GO**; a fresh versioned replication must report its own results.
No arm combinations are evaluated. The new code validates unique declared seeds, the exact declared development roster, per-card
new failures/fallbacks and boundary rounding. Before confirmation it also checks live source,
config, dependency and scorer fingerprints against the development snapshot. Do not edit
implementation files between development and confirmation; a mismatch aborts before answers.
The original complete roster remains valid, but its wrapper-source drift would fail this new
guard. The original artifacts and NO-GO decision are preserved; do not reuse them to rerun confirmation.

Score snapshots retain source hashes, but the development wrapper's source content was not
retained and its hash differs from confirmation. [guard-audit.json](guard-audit.json) records
this limitation. A fresh run of the final code is a versioned replication, not a certified
reproduction of the original source-frozen model. No claim of identical original A/B/C
forecasts is made. The old three-seed regression uses old `b9c663d` inputs and the current
`3b51e16` scorer/normalization; its original `upstream_commit` names the evaluation checkout.
Absolute paths affect cache IDs. Runtimes vary by host.

The committed per-card scores reproduce the reported aggregates and uncertainty without
reading any answers or making another forecast:

```sh
PYTHONPATH=. .venv-current/bin/python - <<'PYCODE'
import gzip
from pathlib import Path
from t2eval.final_alignment import summarize
for name in ['development', 'confirmation', 'old-reference', 'old-regression']:
    output = Path('.context/recomputed-statistics')/name
    output.mkdir(parents=True, exist_ok=True)
    source = Path('reports/final_alignment/evidence')/(name+'-cards.csv.gz')
    (output/'cards.csv').write_bytes(gzip.decompress(source.read_bytes()))
    summarize(output)
PYCODE
```

## Published audit and opt-in compatibility image

```sh
.venv-current/bin/python -m t2eval.mock_final \
  --image ghcr.io/hhwolf/agenthon-numeric-v1@sha256:400fe71078d8f9e3e7859da3402ec7866a531760c14b1c0bc795e8e71db0d674 \
  --units-root vendor/current/units --units practice --network none --no-proxy-scores \
  --out .eval/final_alignment/published-current
.venv-current/bin/python -m t2eval.alignment_audit --units-root vendor/current/units \
  --published .eval/final_alignment/published-current/a --out .eval/final_alignment/audit-final

docker buildx build --platform linux/amd64 --load \
  --build-arg DEFAULT_FORECASTER=numeric_alignment \
  -t agenthon-final-alignment:compatibility-v2 .
mkdir -p .context/empty-replay
.venv-current/bin/python -m t2eval.mock_final \
  --image agenthon-final-alignment:compatibility-v2 --allow-local-image \
  --units-root vendor/current/units --units practice --network none --no-proxy-scores --seed 1111 \
  --out .eval/final_alignment/final-compat-offline
for mode in canned chaos replay; do
  .venv-current/bin/python -m t2eval.mock_final \
    --image agenthon-final-alignment:compatibility-v2 --allow-local-image \
    --units-root vendor/current/units --units practice --network restricted --house-mode "$mode" \
    --replay-dir .context/empty-replay --no-proxy-scores --seed 1111 \
    --out ".eval/final_alignment/final-compat-$mode"
done
```

All answer files remain outside mounted unit directories. The compatibility CLI uses only the
strict-ratio repair. A/B/C are explicitly named research arguments and are not CLI defaults.
The image build uses the unchanged allowlist; only runtime files enter `/app`.
The replay directory is intentionally empty: with House disabled, the expected request count is
zero in every mode. These checks demonstrate no dependence on House, not a successful LLM replay.

For a cold pull without deleting any existing image/cache, the helper below creates a privileged,
resource-limited Docker-in-Docker daemon with an empty tmpfs store, pulls anonymously, records
elapsed time, and removes only its own container. It does not expose a TCP daemon port.

```sh
.venv-current/bin/python scripts/alignment_cold_pull.py \
  --image ghcr.io/hhwolf/agenthon-numeric-v1@sha256:400fe71078d8f9e3e7859da3402ec7866a531760c14b1c0bc795e8e71db0d674 \
  --out .context/selected-cold-pull.json
```

The first local cold-pull attempt used a 768 MiB/vfs daemon and exited 137 while unpacking;
the successful attempt used 2 GiB/overlay2. Both disposable containers were cleaned up.
The published image itself was not changed. The final compatibility image is local only;
anonymous registry verification of that candidate is therefore **not applicable**, not passed.

## Evidence export

```sh
# The export also includes the final 88-card guard-hardening recheck.
.venv-release/bin/python -m t2eval.final_alignment old \
  --old-root "$alignment_old_root" --units-root "$alignment_old_root/vendor/track2/units" \
  --out .eval/final_alignment/old-reference-final --arms release --crc32 --normalization release
PYTHONPATH=. .venv-current/bin/python scripts/export_alignment_evidence.py
```

The export includes card/seed scores, components, horizon losses/coverage, summaries, paired
intervals, full cache identities, input inventories, omissions, selection/unblinding metadata
and mock reports. Gzip headers have fixed timestamps. Raw numeric panels, realized values and
forecast draws remain local. `evidence/SHA256SUMS.json` validates exported bytes.
