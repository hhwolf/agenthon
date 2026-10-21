"""Phase 5 release gates over the mock Final's official-scored artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys

import numpy as np

from .mock_final import REQUIRED, LIMIT, select_units
from t2agent.io import read_card

RUNS = {
    'offline': ('none', 'canned', False),
    'canned': ('restricted', 'canned', False),
    'chaos': ('restricted', 'chaos', False),
    'replay': ('restricted', 'replay', False),
    'offline-repeat': ('none', 'canned', False),
    'offline-fresh': ('none', 'canned', True),
    'replay-repeat': ('restricted', 'replay', False),
    'replay-fresh': ('restricted', 'replay', True),
}
HOUSE = dict(name='nvidia/nemotron-3-super-120b-a12b', version='rl-030326-fp8',
             revision='rl-030326-fp8', training_cutoff='unpublished', access='api')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(Path(path).read_text())


def digest_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_run(root, image, expected, *, network, house_mode, seed, uses_house):
    summary = read_json(root / 'summary.json')
    rows = read_json(root / 'cards.json')
    require(summary['image'] == image, 'wrong image digest')
    require(summary['network'] == network and summary['house_mode'] == house_mode,
            'wrong network/House mode')
    require(len(rows) == len(expected) and {r['unit_id'] for r in rows} == set(expected),
            'incomplete or duplicate unit roster')
    require(summary['statuses'] == {'passed': len(expected)}, 'admissibility failed')
    for row in rows:
        require(row['status'] == 'passed' and row['seed'] == seed, 'failed unit or wrong seed')
        require(math.isfinite(row['wall_seconds']) and 0 <= row['wall_seconds'] < 600,
                'unit wall time must be finite and <600 s')
        require(type(row['requests_used']) is int and 0 <= row['requests_used'] <= 20,
                'request budget exceeded or invalid')
        require(row['output_tree']['valid'] and 0 < row['output_tree']['bytes'] < LIMIT,
                'output must be valid and strictly below 64 MiB')
        if network == 'none' or not uses_house:
            require(row['requests_used'] == 0, 'unexpected House request')
    mean = sum(r['wall_seconds'] for r in rows) / len(rows)
    require(mean <= 240, 'mean wall time exceeds 240 s')
    proxies = [r['score'] for r in rows if r.get('proxy_available')]
    require(all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 8 for v in proxies),
            'invalid proxy score')
    if network == 'restricted' and house_mode == 'replay' and uses_house:
        stats = read_json(root / 'house-stats.json')
        events = stats['events']
        require(len(events) == sum(r['requests_used'] for r in rows), 'incomplete replay ledger')
        for row in rows:
            require(row['requests_used'] > 0, 'replay sent no request for a unit')
            unit_events = [e for e in events if e['unit_id'] == row['unit_id']]
            require(len(unit_events) == row['requests_used'], 'unit replay count mismatch')
        require(all(e.get('replay_hit') is True and e.get('behavior') == 'replay'
                    for e in events), 'replay cache miss; fallback is not replay evidence')
    return dict(units=len(rows), passed=len(rows), mean_wall_seconds=mean,
                max_wall_seconds=max(r['wall_seconds'] for r in rows),
                max_requests=max(r['requests_used'] for r in rows),
                requests=sum(r['requests_used'] for r in rows),
                proxy_units=len(proxies), proxy_mean=sum(proxies)/len(proxies) if proxies else None,
                proxy_caps=sum(v >= 8 for v in proxies),
                max_output_bytes=max(r['output_tree']['bytes'] for r in rows),
                pull_seconds=sum(r['pull_seconds'] for r in rows),
                image_cached_before=summary['image_cached_before'],
                projection_104_seconds=104*mean, over_half_platform_clock=104*mean > 21600), rows


def compare_outputs(left, right, units, *, offline):
    differences = {name: [] for name in REQUIRED}
    for unit in units:
        for name in REQUIRED:
            if digest_file(left / unit / 'output' / name) != digest_file(right / unit / 'output' / name):
                differences[name].append(unit)
    require(not differences['forecast.parquet'] and not differences['forecast_meta.json'],
            'same-seed forecasts or metadata differ')
    require(not differences['forecast_rationale.md'], 'same-seed rationales differ')
    return dict(forecasts_identical=True, metadata_identical=True,
                rationales_identical=not differences['forecast_rationale.md'],
                rationale_differences=differences['forecast_rationale.md'])


def seed_stability(left, right, years, *, expected_proxies=88):
    a = {r['unit_id']: r['score'] for r in left if r.get('proxy_available')}
    b = {r['unit_id']: r['score'] for r in right if r.get('proxy_available')}
    require(set(a) == set(b) and len(a) == expected_proxies, 'seed check needs all paired proxies')
    ids = sorted(a)
    av, bv = np.array([a[u] for u in ids]), np.array([b[u] for u in ids])
    require(np.isfinite(av).all() and np.isfinite(bv).all()
            and ((0 <= av) & (av <= 8)).all() and ((0 <= bv) & (bv <= 8)).all(),
            'invalid proxy scores')
    blocks = [[i for i, u in enumerate(ids) if years[u] == y] for y in sorted({years[u] for u in ids})]
    sizes = np.array([len(b) for b in blocks])
    picks = np.random.default_rng(20261016).integers(len(blocks), size=(10000, len(blocks)))
    def interval(values):
        sums = np.array([values[b].sum() for b in blocks])
        return np.quantile(sums[picks].sum(axis=1) / sizes[picks].sum(axis=1), [.025, .975]).tolist()
    aci, bci = interval(av), interval(bv)
    passed = aci[0] <= bv.mean() <= aci[1] and bci[0] <= av.mean() <= bci[1]
    return dict(passed=bool(passed), proxies=len(ids), baseline_mean=float(av.mean()),
                fresh_mean=float(bv.mean()), baseline_ci=aci, fresh_ci=bci,
                paired_delta=float((bv-av).mean()), paired_delta_ci=interval(bv-av),
                bootstrap='10000 paired whole-year resamples; seed 20261016')


def make_descriptor(image, license_id, *, uses_house, team_id=None):
    """Use the official fixture/parser/sealer, never pack or ask for a Team Key."""
    import jsonschema
    import qfbench2_common
    from qfbench2_common.contracts.descriptor import SubmissionDescriptor, seal_descriptor_digest
    match = re.fullmatch(r'([^/]+)/(.+)@(sha256:[0-9a-f]{64})', image)
    require(match is not None, 'immutable registry/repository@sha256 required')
    package = Path(qfbench2_common.__file__).parent
    obj = read_json(package / 'contracts/fixtures/c5/forecasting_final.json')
    obj.update(schema_version='1.1.0', license=license_id, models=[HOUSE] if uses_house else [],
               image=dict(zip(('registry', 'repository', 'digest'), match.groups())), image_access='public')
    obj.pop('descriptor_digest')
    obj['team_id'] = team_id or 'team-validation-only-not-for-submission'
    validated = seal_descriptor_digest(obj)
    jsonschema.validate(validated, read_json(package / 'schemas/submission.schema.json'))
    SubmissionDescriptor.from_mapping(validated)
    if team_id:
        return validated, dict(sealed=True, toolkit_parser='passed', json_schema='passed')
    # pack accepts an absent team_id and derives it. A placeholder would be rejected.
    obj.pop('team_id')
    return obj, dict(sealed=False, toolkit_parser='passed on in-memory validation alias only',
                     json_schema='passed on in-memory validation alias only',
                     pending='Human pack must derive team_id and seal; on-disk input is not a complete C5 descriptor')


def verify(args):
    units = select_units(args.units_root, 'practice')
    require(len(units) == 104, 'expected all 104 public units')
    years = {read_card(u/'card.toml')['task']['id']:
             int(str(read_card(u/'card.toml')['provenance']['data_cutoff'])[:4]) for u in units}
    report = dict(image=args.image, seed=args.seed, fresh_seed=args.fresh_seed, runs={})
    all_rows = {}
    for name, (network, mode, fresh) in RUNS.items():
        report['runs'][name], all_rows[name] = validate_run(args.out/name/'a', args.image, years,
            network=network, house_mode=mode, seed=args.fresh_seed if fresh else args.seed,
            uses_house=args.uses_house)
        require(report['runs'][name]['proxy_units'] == 88, 'each sweep must score all 88 proxies')
    require(not report['runs']['offline']['image_cached_before']
            and report['runs']['offline']['pull_seconds'] > 0, 'first sweep needs a cold-image pull')
    report['cold_pull_scope'] = 'Final image absent; shared base layers may already be cached.'
    report['determinism'] = {}
    report['seed_stability'] = {}
    for name in ('offline', 'replay'):
        report['determinism'][name] = compare_outputs(args.out/name/'a', args.out/(name+'-repeat')/'a',
                                                     [u.name for u in units], offline=name=='offline')
        report['seed_stability'][name] = seed_stability(all_rows[name], all_rows[name+'-fresh'], years)
        changed = sum(digest_file(args.out/name/'a'/u.name/'output/forecast.parquet') !=
                      digest_file(args.out/(name+'-fresh')/'a'/u.name/'output/forecast.parquet') for u in units)
        require(changed > 0, 'fresh QFBENCH_SEED did not change any forecast')
        report['seed_stability'][name]['changed_forecasts'] = changed
    report['passed'] = all(r['passed'] for r in report['seed_stability'].values())
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    require(report['passed'], 'fresh-seed mean falls outside bootstrap interval')
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image', required=True)
    p.add_argument('--out', type=Path, default=Path('.eval/mock-final/phase5'))
    p.add_argument('--report', type=Path, default=Path('reports/phase5/verification.json'))
    p.add_argument('--units-root', type=Path, default=Path('vendor/track2/units'))
    p.add_argument('--replay-dir', type=Path)
    p.add_argument('--uses-house', action='store_true')
    p.add_argument('--release', type=Path, default=Path('reports/phase5/release.json'))
    p.add_argument('--seed', type=int, default=20261016)
    p.add_argument('--fresh-seed', type=int, default=20261017)
    p.add_argument('--verify-only', action='store_true')
    args = p.parse_args(argv)
    require(re.fullmatch(r'[^\s]+@sha256:[0-9a-f]{64}', args.image), 'published immutable digest required')
    require(args.seed != args.fresh_seed, 'fresh seed must differ')
    release = read_json(args.release)
    require(release.get('status') == 'frozen', 'final selection is not frozen')
    require((release['mode'] == 'labels') == args.uses_house,
            '--uses-house must match the frozen release configuration')
    if not args.verify_only:
        require(args.replay_dir and args.replay_dir.is_dir(), 'replay directory required')
        if args.uses_house:
            require(any(args.replay_dir.rglob('*.json')), 'House replay requires cached responses')
        args.out.mkdir(parents=True, exist_ok=True)
        for name, (network, mode, fresh) in RUNS.items():
            # No shell interpolation; each run records its own exact source/image provenance.
            command = [sys.executable, '-m', 't2eval.mock_final', '--image', args.image,
                       '--units', 'practice', '--units-root', str(args.units_root), '--network', network,
                       '--house-mode', mode, '--seed', str(args.fresh_seed if fresh else args.seed),
                       '--out', str(args.out/name)]
            if mode == 'replay':
                command += ['--replay-dir', str(args.replay_dir)]
            subprocess.run(command, check=True)
    print(json.dumps(verify(args), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
