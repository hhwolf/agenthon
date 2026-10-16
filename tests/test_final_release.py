"""Final gates must reject plausible-looking but incomplete release evidence."""
import json
from pathlib import Path

import pytest

from t2eval.final_release import (HOUSE, compare_outputs, make_descriptor,
                                  seed_stability, validate_run)
from t2agent.text_layer.signal import Ledger, rationale_labels
from test_text_layer import make_summary
from scripts.prepare_final import BUILD_INPUTS, release_preflight

IMAGE = 'ghcr.io/hhwolf/agenthon-numeric-v1@sha256:' + 'a'*64


def test_publish_preflight_rejects_pending_incomplete_or_changed_freeze(tmp_path):
    import hashlib
    release_path = tmp_path/'reports/phase5/release.json'
    release_path.parent.mkdir(parents=True)
    (tmp_path/'t2agent').mkdir()
    config = tmp_path/'t2agent/text_config.json'
    config.write_text(json.dumps(dict(mode='labels', **{'lambda':.5})))
    for name in BUILD_INPUTS:
        (tmp_path/name).write_text('build input\n')
    (tmp_path/'LICENSE').write_text('SPDX-License-Identifier: MIT\n')
    obj = dict(status='pending', mode='labels', license='MIT', **{'lambda':.5},
               runtime_sha256={name:hashlib.sha256((tmp_path/name).read_bytes()).hexdigest()
                               for name in BUILD_INPUTS | {'t2agent/text_config.json'}})
    release_path.write_text(json.dumps(obj))
    with pytest.raises(ValueError, match='not frozen'):
        release_preflight(tmp_path)
    obj['status'] = 'frozen'; release_path.write_text(json.dumps(obj))
    assert release_preflight(tmp_path)['mode'] == 'labels'
    (tmp_path/'t2agent/new.py').write_text('# new runtime code\n')
    with pytest.raises(ValueError, match='incomplete runtime'):
        release_preflight(tmp_path)
    (tmp_path/'t2agent/new.py').unlink()
    for path in [config, tmp_path/'Dockerfile', tmp_path/'requirements-runtime.txt']:
        original = path.read_text(); path.write_text(original+'\n')
        with pytest.raises(ValueError, match='runtime changed'):
            release_preflight(tmp_path)
        path.write_text(original)


def test_descriptor_uses_official_parser_and_does_not_invent_team_identity():
    from qfbench2_common.contracts.descriptor import SubmissionDescriptor
    from qfbench2_common.contracts.errors import ContractError
    draft, status = make_descriptor(IMAGE, 'MIT', uses_house=False)
    assert draft['models'] == [] and draft['schema_version'] == '1.1.0'
    assert draft['competition_id'] == 'agenthon2026-forecasting-final'
    assert 'team_id' not in draft and 'descriptor_digest' not in draft
    assert not status['sealed']
    sealed, status = make_descriptor(IMAGE, 'MIT', uses_house=True, team_id='team-'+'a'*32)
    assert status['sealed'] and sealed['models'] == [HOUSE]
    assert SubmissionDescriptor.from_mapping(sealed).image_reference() == IMAGE
    sealed['image']['digest'] = 'sha256:'+'b'*64
    with pytest.raises(ContractError):
        SubmissionDescriptor.from_mapping(sealed)


def fixture_run(root, **updates):
    root.mkdir()
    row = dict(unit_id='a', status='passed', seed=1, wall_seconds=1., requests_used=1,
               pull_seconds=.1, output_tree=dict(valid=True, bytes=100))
    row.update(updates)
    (root/'cards.json').write_text(json.dumps([row]))
    (root/'summary.json').write_text(json.dumps(dict(image=IMAGE, network='restricted',
        house_mode='replay', statuses={'passed':1}, image_cached_before=False)))
    (root/'house-stats.json').write_text(json.dumps(dict(events=[dict(unit_id='a',
        replay_hit=True, behavior='replay')])))
    return root


def check(root):
    return validate_run(root, IMAGE, {'a'}, network='restricted', house_mode='replay', seed=1, uses_house=True)


@pytest.mark.parametrize('update', [dict(wall_seconds=float('nan')), dict(wall_seconds=600),
    dict(wall_seconds=241), dict(requests_used=21), dict(requests_used=0), dict(seed=2),
    dict(output_tree=dict(valid=True, bytes=64*1024**2)), dict(status='schema_invalid')])
def test_release_limits_are_fail_closed(tmp_path, update):
    root = fixture_run(tmp_path/'run', **update)
    with pytest.raises(ValueError):
        check(root)


def test_replay_miss_cannot_pass_as_neutral_fallback(tmp_path):
    root = fixture_run(tmp_path/'run')
    assert check(root)[0]['passed'] == 1
    (root/'house-stats.json').write_text(json.dumps(dict(events=[dict(unit_id='a',
        replay_hit=False, behavior='replay_miss')])))
    with pytest.raises(ValueError, match='cache miss'):
        check(root)


def test_duplicate_or_wrong_digest_reports_are_rejected(tmp_path):
    root = fixture_run(tmp_path/'run')
    rows = json.loads((root/'cards.json').read_text())
    (root/'cards.json').write_text(json.dumps(rows*2))
    with pytest.raises(ValueError, match='roster'):
        check(root)
    (root/'cards.json').write_text(json.dumps(rows))
    summary = json.loads((root/'summary.json').read_text())
    summary['image'] = IMAGE.replace('a'*64, 'b'*64)
    (root/'summary.json').write_text(json.dumps(summary))
    with pytest.raises(ValueError, match='digest'):
        check(root)


def test_determinism_checks_all_deliverable_bytes(tmp_path):
    for run in ('a','b'):
        out = tmp_path/run/'unit/output'; out.mkdir(parents=True)
        for name in ('forecast.parquet','forecast_meta.json','forecast_rationale.md'):
            (out/name).write_bytes(b'same')
    assert compare_outputs(tmp_path/'a',tmp_path/'b',['unit'],offline=False)['rationales_identical']
    (tmp_path/'b/unit/output/forecast_rationale.md').write_text('different')
    with pytest.raises(ValueError, match='rationales'):
        compare_outputs(tmp_path/'a',tmp_path/'b',['unit'],offline=False)


def test_bootstrap_stability_requires_same_full_proxy_roster():
    rows = [dict(unit_id=str(i), score=1., proxy_available=True) for i in range(88)]
    years = {str(i):2000+i%20 for i in range(88)}
    assert seed_stability(rows, rows, years)['passed']
    changed = [dict(r, score=2.) for r in rows]
    assert not seed_stability(rows, changed, years)['passed']
    with pytest.raises(ValueError, match='paired proxies'):
        seed_stability(rows, rows[:-1], years)


def test_rationale_is_stable_across_timing_and_thread_completion_order():
    calls = [dict(purpose='labels_2', status='ok', attempts=1),
             dict(purpose='labels_1', status='ok', attempts=1)]
    warnings = ['chunk 2 repaired', 'chunk 1 dropped an unsupported claim']
    first = Ledger(calls=calls, requests=2, elapsed_s=10, notes=warnings)
    second = Ledger(calls=list(reversed(calls)), requests=2, elapsed_s=245,
                    notes=list(reversed(warnings))+['wall time 245s exceeded the 240s soft target'])
    assert rationale_labels(make_summary(), {}, [], first) == rationale_labels(make_summary(), {}, [], second)


def test_all_eight_sweeps_forward_modes_seeds_and_replay_cache(tmp_path, monkeypatch):
    import t2eval.final_release as final
    cache = tmp_path/'cache'; cache.mkdir(); (cache/'real.json').write_text('{}')
    release = tmp_path/'release.json'; release.write_text(json.dumps(dict(status='frozen', mode='labels')))
    commands = []
    monkeypatch.setattr(final.subprocess, 'run', lambda cmd, **kw: commands.append(cmd))
    monkeypatch.setattr(final, 'verify', lambda args: {'passed': True})
    assert final.main(['--image', IMAGE, '--replay-dir', str(cache), '--uses-house',
                       '--release', str(release), '--out', str(tmp_path/'runs')]) == 0
    assert len(commands) == 8
    for cmd, (name, (network, mode, fresh)) in zip(commands, final.RUNS.items()):
        assert cmd[cmd.index('--seed')+1] == ('20261017' if fresh else '20261016')
        assert cmd[cmd.index('--network')+1] == network
        assert cmd[cmd.index('--house-mode')+1] == mode
        assert cmd[cmd.index('--out')+1] == str(tmp_path/'runs'/name)
        assert ('--replay-dir' in cmd) == (mode == 'replay')
    with pytest.raises(ValueError, match='must match'):
        final.main(['--image', IMAGE, '--release', str(release), '--verify-only'])


def test_full_verifier_requires_cold_pull_and_both_seed_checks(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import t2eval.final_release as final
    units = [Path('u'+str(i)) for i in range(104)]
    monkeypatch.setattr(final, 'select_units', lambda *_: units)
    monkeypatch.setattr(final, 'read_card', lambda path: dict(task={'id':path.parent.name},
                        provenance={'data_cutoff':'2024-01-01'}))
    validated = []
    cached = False
    def validate(root, *args, **kwargs):
        validated.append(root.parent.name)
        return dict(proxy_units=88, image_cached_before=cached, pull_seconds=1), []
    monkeypatch.setattr(final, 'validate_run', validate)
    compared = []
    monkeypatch.setattr(final, 'compare_outputs', lambda a,b,*args,**kw: compared.append((a,b)) or {'identical':True})
    stable = True
    monkeypatch.setattr(final, 'seed_stability', lambda *args,**kw: {'passed':stable})
    monkeypatch.setattr(final, 'digest_file', lambda p: 'fresh' if '-fresh' in str(p) else 'baseline')
    args = SimpleNamespace(units_root=tmp_path, out=tmp_path/'runs', report=tmp_path/'report.json',
                           image=IMAGE, seed=1, fresh_seed=2, uses_house=True)
    assert final.verify(args)['passed']
    assert validated == list(final.RUNS) and len(compared) == 2
    assert set(json.loads(args.report.read_text())['seed_stability']) == {'offline','replay'}
    cached = True
    with pytest.raises(ValueError, match='cold-image'):
        final.verify(args)
    cached = False; stable = False
    with pytest.raises(ValueError, match='bootstrap'):
        final.verify(args)
    assert not json.loads(args.report.read_text())['passed']
