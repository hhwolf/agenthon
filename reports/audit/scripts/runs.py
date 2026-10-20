"""Locate audit inputs from any checkout: repo root from this file, runs by their saved metadata.

Run directory names are content hashes whose recipe changed when text mode and House env joined the
identity, so the audit never matches hash prefixes. It selects the single run whose summary.json
metadata has the requested mode, forecaster, draw count and (when recorded) text mode.

CLI for the shell drivers:  python runs.py find WORK MODE FORECASTER N_DRAWS [TEXT_MODE]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def find_run(work, mode, forecaster, n_draws, text_mode=None):
    """Return the one full (unlimited, default-seed) run in WORK/runs matching the metadata."""
    hits = []
    for summary in sorted((Path(work)/'runs').glob('*/summary.json')):
        meta = json.loads(summary.read_text()).get('metadata', {})
        if (meta.get('mode'), meta.get('forecaster'), meta.get('n_draws')) != (mode, forecaster, n_draws):
            continue
        if meta.get('limit') or meta.get('forecast_seed') is not None or meta.get('QFBENCH_SEED') is not None:
            continue
        env = meta.get('output_env')  # absent in runs made before the identity fix
        if env is not None and env.get('TEXT_LAYER_MODE') != text_mode:
            continue
        hits.append(summary.parent)
    if len(hits) != 1:
        raise SystemExit(f'expected exactly one {mode}/{forecaster}/{n_draws}/{text_mode} run in {work}, found {len(hits)}')
    return hits[0]


if __name__ == '__main__':
    if len(sys.argv) not in (6, 7) or sys.argv[1] != 'find':
        raise SystemExit(__doc__)
    print(find_run(sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]), sys.argv[6] if len(sys.argv) == 7 else None))
