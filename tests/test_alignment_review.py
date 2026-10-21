"""Independent shipping audit of the bounded Final-alignment changes."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import tomli_w

from t2agent import cli, m0, numeric_alignment as alignment, numeric_v1_1 as nv
from t2agent.io import read_card, read_panels
from t2eval import alignment_selection as selection, final_alignment as research
from t2eval import mock_final as runner


def numeric_fixture(periods=500, frequency='D', panel='rates_daily.parquet'):
    dates = pd.date_range('2019-01-01', periods=periods, freq=frequency)
    values = 2 + np.cumsum(np.random.default_rng(14).normal(.002, .01, periods))
    card = {'task': {'id': 'review-alignment'},
            'provenance': {'data_cutoff': str(dates[-1].date())},
            'targets': {'asset_ids': ['UST_2Y'], 'horizons': [1, 4], 'target_type': 'level'}}
    panels = {panel: pd.DataFrame({'date': dates, 'asset': 'UST_2Y', 'value': values})}
    return card, panels


def test_compatibility_is_opt_in_and_changes_only_exact_ratio_boundary():
    card, panels = numeric_fixture()
    cutoff = card['provenance']['data_cutoff']
    card['targets'].update(horizons=[2], target_dates=[str((pd.Timestamp(cutoff)+pd.Timedelta(days=4)).date())])
    original = nv.forecast(card, panels, None, cutoff, 2000, 1111)
    corrected = alignment.forecast(card, panels, None, cutoff, 2000, 1111)
    unchanged = alignment.forecast(card, panels, None, cutoff, 2000, 1111, arm='release')
    pd.testing.assert_frame_equal(original, unchanged)
    assert original.attrs['rationale'] == unchanged.attrs['rationale']
    assert corrected.attrs['alignment_active'] and corrected.attrs['fallback'] is None
    assert not np.array_equal(original.value, corrected.value)
    assert corrected.value.std() / original.value.std() == pytest.approx(np.sqrt(.5), rel=.08)
    card['targets']['target_dates'] = [str((pd.Timestamp(cutoff)+pd.Timedelta(days=5)).date())]
    untouched = alignment.forecast(card, panels, None, cutoff, 2000, 1111)
    release = nv.forecast(card, panels, None, cutoff, 2000, 1111)
    assert not untouched.attrs['alignment_active']
    pd.testing.assert_frame_equal(untouched, release)


def test_research_eligibility_rejects_monthly_return_unknown_and_mixed_horizons():
    card, panels = numeric_fixture()
    assert alignment.eligible(card, panels, card['provenance']['data_cutoff'])
    for horizons, target_type in [([0, 1], 'level'), ([1, 5], 'level'), ([1, 4], 'log_return')]:
        altered = deepcopy(card)
        altered['targets'].update(horizons=horizons, target_type=target_type)
        assert not alignment.eligible(altered, panels, altered['provenance']['data_cutoff'])
    unknown = {'unrecognized_daily.parquet': next(iter(panels.values()))}
    assert not alignment.eligible(card, unknown, card['provenance']['data_cutoff'])
    monthly, monthly_panels = numeric_fixture(40, 'MS')
    assert not alignment.eligible(monthly, monthly_panels, monthly['provenance']['data_cutoff'])


def test_arm_a_changes_center_without_changing_common_seed_innovations():
    card, panels = numeric_fixture()
    cutoff = card['provenance']['data_cutoff']
    original = alignment.forecast(card, panels, None, cutoff, 2000, 1111, arm='release')
    zero = alignment.forecast(card, panels, None, cutoff, 2000, 1111, arm='A')
    baseline = m0.distribution(card, panels, cutoff)
    anchor = next(iter(panels.values())).value.iloc[-1]
    expected = -.25*(baseline.mean-anchor)
    for index, horizon in enumerate(card['targets']['horizons']):
        delta = zero.loc[zero.horizon == horizon, 'value'].to_numpy() - original.loc[original.horizon == horizon, 'value'].to_numpy()
        np.testing.assert_allclose(delta, expected[index], rtol=1e-9, atol=1e-14)


def test_arm_c_turns_off_overlay_only_on_eligible_cards(monkeypatch):
    card, panels = numeric_fixture()
    calls = []
    def observe(*args, **kwargs):
        calls.append(kwargs['text_mode'])
        return None, 'test signal observer'
    monkeypatch.setattr(alignment.numeric_v1, 'read_forecast_text', observe)
    cutoff = card['provenance']['data_cutoff']
    alignment.forecast(card, panels, None, cutoff, 200, 1111, arm='C', text_mode='card_notes_only')
    card['targets']['horizons'] = [21]
    alignment.forecast(card, panels, None, cutoff, 200, 1111, arm='C', text_mode='card_notes_only')
    assert calls == ['numeric_only', 'card_notes_only']


def test_insufficient_ewma_history_uses_existing_m0_fallback():
    card, panels = numeric_fixture(periods=15)
    result = alignment.forecast(card, panels, None, card['provenance']['data_cutoff'], 200, 1111, arm='B')
    expected = m0.forecast(card, panels, None, card['provenance']['data_cutoff'], 200, 1111)
    pd.testing.assert_frame_equal(result, expected)
    assert result.attrs['fallback'] == 'M0 fallback'
    assert 'Insufficient lagged EWMA history' in result.attrs['rationale']


def test_opt_in_cli_corrupt_panels_preserves_three_file_last_resort(tmp_path):
    card, _ = numeric_fixture()
    (tmp_path/'card.toml').write_text(tomli_w.dumps(card))
    panels = tmp_path/'panels'
    panels.mkdir()
    (panels/'rates_daily.parquet').write_bytes(b'corrupt fixture')
    out = tmp_path/'out/forecast.parquet'
    cli.main(['--forecaster', 'numeric_alignment', '--panels', str(panels),
              '--asof', card['provenance']['data_cutoff'], '--out', str(out), '--seed', '1111'])
    frame = pd.read_parquet(out)
    assert np.isfinite(frame.value).all() and frame.draw.nunique() == 2000
    assert {p.name for p in out.parent.iterdir()} == {'forecast.parquet', 'forecast_meta.json', 'forecast_rationale.md'}
    rationale = out.with_name('forecast_rationale.md').read_text()
    assert 'last-resort wide random walk' in rationale and 'Panel load failed:' in rationale
    with pytest.raises(ValueError, match='Unknown alignment arm'):
        alignment.forecast(card, {}, None, card['provenance']['data_cutoff'], arm='unplanned')


def test_config_load_failure_still_uses_inherited_never_fail_wrapper(monkeypatch):
    card, panels = numeric_fixture()
    def broken_config():
        raise ValueError('broken config fixture')
    monkeypatch.setattr(nv, 'selected_config', broken_config)
    result = alignment.forecast(card, panels, None, card['provenance']['data_cutoff'], 200, 1111)
    assert result.attrs['fallback'] == 'M0 fallback'
    assert np.isfinite(result.value).all()
    assert 'broken config fixture' in result.attrs['rationale']


def selection_data():
    return pd.DataFrame([
        dict(id=f'card-{index}', arm=arm, seed=seed, score=mean, split='development',
             group='UST_bills', week=f'2015-W{index//4+1:02d}', failed=False, fallback='')
        for index in range(48) for arm, mean in [('release', 1.), ('A', .8), ('B', .9), ('C', 1.)]
        for seed in research.SEEDS])


def freeze(tmp_path, rows):
    directory = tmp_path/'comparison'
    directory.mkdir(parents=True)
    rows.to_csv(directory/'cards.csv', index=False)
    (directory/'identity.json').write_text('{"identity":"review-fixture"}')
    output = tmp_path/'frozen.json'
    selection.select(directory, output)
    return json.loads(output.read_text())


def test_selection_checks_exact_declared_seed_set_and_complete_card_arms(tmp_path):
    rows = selection_data()
    rows.loc[1, 'seed'] = rows.loc[0, 'seed']
    with pytest.raises(ValueError, match='Incomplete|duplicated'):
        freeze(tmp_path/'duplicate', rows)
    rows = selection_data()
    rows = rows.loc[~((rows.id == 'card-0') & (rows.arm == 'B'))]
    with pytest.raises(ValueError, match='Incomplete|duplicated'):
        freeze(tmp_path/'missing', rows)


def test_selection_rejects_new_failed_cards_even_with_same_failure_count(tmp_path):
    rows = selection_data()
    rows.loc[(rows.id == 'card-0') & (rows.arm == 'release'), 'failed'] = True
    rows.loc[(rows.id == 'card-1') & (rows.arm == 'A'), 'failed'] = True
    record = freeze(tmp_path, rows)
    assert record['winner'] == 'A'
    assert not record['comparisons']['A']['gates']['no_new_failures']
    assert not record['development_pass']


def test_selection_rejects_new_fallback_cards_even_with_same_fallback_count(tmp_path):
    rows = selection_data()
    rows.loc[(rows.id == 'card-0') & (rows.arm == 'release'), 'fallback'] = 'M0 fallback'
    rows.loc[(rows.id == 'card-1') & (rows.arm == 'A'), 'fallback'] = 'M0 fallback'
    record = freeze(tmp_path, rows)
    assert not record['comparisons']['A']['gates']['no_new_fallbacks']
    assert not record['development_pass']


def test_selection_major_group_veto_and_report_only_isolation(tmp_path):
    rows = selection_data()
    other = rows.copy()
    other['id'] = 'other-'+other.id
    other['group'] = 'EM_ECB'
    rows.loc[rows.arm == 'A', 'score'] = 1.051
    other.loc[other.arm == 'A', 'score'] = .5
    report = rows.copy()
    report['id'] = 'report-'+report.id
    report['split'] = 'report_only'
    report.loc[report.arm == 'A', 'score'] = 0
    record = freeze(tmp_path, pd.concat([rows, other, report], ignore_index=True))
    a = record['comparisons']['A']
    assert a['mean'] == pytest.approx((1.051+.5)/2)
    assert not a['gates']['no_major_group_5pct_harm'] and not record['development_pass']


def test_selection_exact_five_percent_group_boundary_is_permitted(tmp_path):
    rows = selection_data()
    other = rows.copy()
    other['id'] = 'other-'+other.id
    other['group'] = 'EM_ECB'
    rows.loc[rows.arm == 'A', 'score'] = 1.05
    other.loc[other.arm == 'A', 'score'] = .5
    record = freeze(tmp_path, pd.concat([rows, other], ignore_index=True))
    assert record['comparisons']['A']['gates']['no_major_group_5pct_harm']
    assert record['development_pass']


def test_selection_caps_and_bad_seed_block_average_improvement(tmp_path):
    rows = selection_data()
    rows.loc[(rows.arm == 'A') & (rows.seed == 3333), 'score'] = 1.01
    rows.loc[(rows.arm == 'A') & (rows.id == 'card-0') & (rows.seed == 1111), 'score'] = 8
    record = freeze(tmp_path, rows)
    gates = record['comparisons']['A']['gates']
    assert gates['improvement_1pct']
    assert not gates['improvement_each_seed'] and not gates['caps_nonincreasing_each_seed']


def test_selection_tie_prefers_fewer_knobs_and_cannot_overwrite(tmp_path):
    rows = selection_data()
    rows.loc[rows.arm == 'B', 'score'] = .7996
    record = freeze(tmp_path, rows)
    assert record['winner'] == 'A' and record['development_pass']
    output = tmp_path/'frozen.json'
    before = output.read_bytes()
    with pytest.raises(FileExistsError, match='frozen'):
        selection.select(tmp_path/'comparison', output)
    assert output.read_bytes() == before


def test_selection_keeps_release_when_no_candidate_improves(tmp_path):
    rows = selection_data()
    rows.loc[rows.arm != 'release', 'score'] = 1.01
    record = freeze(tmp_path, rows)
    assert record['winner'] == 'release' and not record['development_pass']


def test_paired_bootstrap_keeps_shared_weeks_and_detects_one_event_dependency():
    rows = selection_data()
    rows.loc[rows.arm == 'A', 'score'] = 1.01
    rows.loc[(rows.arm == 'A') & (rows.week == '2015-W01'), 'score'] = 0
    result = research.paired_ci(rows, 'A')
    repeated = pd.concat([rows, rows.assign(id='duplicate-'+rows.id)], ignore_index=True)
    assert research.paired_ci(repeated, 'A') == result
    assert result['delta'] < 0 and result['delta_without_best_week'] > 0
    assert result['weeks'] == 12 and result['most_helpful_week'] == '2015-W01'


def test_historical_builder_excludes_confirmation_windows_and_never_substitutes_fx(tmp_path, monkeypatch):
    root = tmp_path/'upstream/units'
    ps1 = root/'t2-F1-curve-ust1y-001-ps1'
    ps1.mkdir(parents=True)
    template = {'task': {'id': ps1.name}, 'metadata': {},
                'provenance': {'data_cutoff': '2011-02-07'},
                'targets': {'asset_ids': ['BRL'], 'horizons': [1, 4], 'target_type': 'level'}}
    (ps1/'card.toml').write_text(tomli_w.dumps(template))
    (ps1/'forecast_spec.json').write_text('{}')
    dates = pd.bdate_range('2009-01-01', '2011-12-30')
    # Deliberately conflicting same-asset source; missing ECB target must never
    # be filled from another panel, and ECB values must retain their own units.
    donors = pd.concat([pd.DataFrame({'date': dates, 'asset': 'BRL', 'value': value, 'panel': name})
                        for name, value in [('em_fx_ecb_daily', 123.), ('g10_fx_daily', -456.)]], ignore_index=True)
    donors = donors.loc[~((donors.panel == 'em_fx_ecb_daily') & (donors.date == pd.Timestamp('2011-05-03')))]
    monkeypatch.setattr(research, 'GROUPS', {'EM_ECB': ('em_fx_ecb_daily.parquet', ['BRL'])})
    monkeypatch.setattr(research, 'build_union', lambda *args: (donors, {'fixture': True}))
    out = tmp_path/'built'
    research.build(root, out)
    roster = json.loads((out/'roster.json').read_text())
    omissions = json.loads((out/'omissions.json').read_text())
    assert roster and all(row['group'] == 'EM_ECB' for row in roster)
    assert not any(row['asof'] in {'2011-02-07', '2011-05-02'} for row in roster)
    assert any(row['asof'] == '2011-02-07' and row['reason'] == 'reserved_confirmation_window' for row in omissions)
    assert any(row['asof'] == '2011-05-02' and row['reason'] == 'missing_exact_target' for row in omissions)
    for row in roster:
        panels = read_panels(Path(row['unit'])/'panels')
        assert set(panels) == {'em_fx_ecb_daily.parquet'}
        frame = panels['em_fx_ecb_daily.parquet']
        assert frame.value.eq(123.).all() and frame.date.le(pd.Timestamp(row['asof'])).all()
        assert pd.read_parquet(row['realized']).value.eq(123.).all()


def test_identity_includes_prose_panels_answers_code_config_and_seeds(tmp_path, monkeypatch):
    root = tmp_path/'repo'
    (root/'t2agent').mkdir(parents=True)
    (root/'t2eval').mkdir()
    code = root/'t2agent/fixture.py'
    code.write_text('fixture = 1\n')
    config = root/'t2agent/numeric_v1_1_config.json'
    config.write_text('{"drift":0.25}')
    (root/'t2agent/text_config.json').write_text('{"house_calls":false}')
    unit = tmp_path/'unit'
    unit.mkdir()
    prose = unit/'forecast_card.md'
    prose.write_text('original prose')
    panel = unit/'fixture.parquet'
    panel.write_bytes(b'original panel')
    answer = tmp_path/'synthetic-answer.parquet'
    answer.write_bytes(b'original synthetic answer')
    cases = [dict(id='fixture', unit=str(unit), realized=str(answer))]
    monkeypatch.setattr(research, 'ROOT', root)
    monkeypatch.setattr(research, 'git', lambda *args: 'fixture-sha')
    signatures = []
    def signature(seeds=research.SEEDS):
        return research.identity(cases, seeds, ['release'], tmp_path/'upstream/units')['identity_sha256']
    signatures.append(signature())
    for path, contents in [(prose, 'changed prose'), (panel, 'changed panel'),
                           (answer, 'changed synthetic answer'), (code, 'fixture = 2\n'),
                           (config, '{"drift":0.0}')]:
        path.write_text(contents)
        signatures.append(signature())
    signatures.append(signature([1111]))
    assert len(set(signatures)) == len(signatures)


def test_mock_final_dynamic_roster_provenance_and_clock_projection(tmp_path, monkeypatch):
    root = tmp_path/'current/units'
    for number in range(126):
        unit = root/f'unit-{number:03d}'
        unit.mkdir(parents=True)
        (unit/'card.toml').write_text('[task]\nid="fixture"\n')
    calls = []
    def git_output(command, **kwargs):
        calls.append(command)
        return 'current-checkout-sha\n' if command[2] == str(root.resolve()) else 'release-checkout-sha\n'
    monkeypatch.setattr(runner.subprocess, 'check_output', git_output)
    monkeypatch.setattr(runner, 'image_info', lambda *args: None)
    monkeypatch.setattr(runner, 'docker', lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(
        {'NCPU': 2, 'MemTotal': 8*1024**3, 'Architecture': 'amd64', 'ServerVersion': 'fixture'})))
    monkeypatch.setattr(runner, 'run_unit', lambda unit, *args, **kwargs: dict(
        unit_id=unit.name, status='passed', score=None, requests_used=0, pull_seconds=0,
        wall_seconds=180., image_id='sha256:fixture'))
    monkeypatch.setattr(runner, 'score_rows', lambda *args: None)
    args = runner.parser().parse_args(['--image', 'fixture', '--units-root', str(root), '--no-proxy-scores'])
    summary, rows = runner.run_image('fixture', args, tmp_path/'run', {})
    assert len(rows) == summary['projection_units'] == 126
    assert summary['vendor_commit'] == 'current-checkout-sha'
    assert summary['projection_seconds'] == 126*180
    assert summary['projection_104_seconds'] == 104*180
    assert summary['over_half_platform_clock']  # 126-unit result exceeds 21,600 s; 104 would not.
    def not_a_checkout(*args, **kwargs):
        raise subprocess.CalledProcessError(128, 'git rev-parse')
    monkeypatch.setattr(runner.subprocess, 'check_output', not_a_checkout)
    assert runner.unit_source_revision(root) is None
    monkeypatch.setattr(runner.subprocess, 'check_output', lambda *args, **kwargs: '')
    assert runner.unit_source_revision(root) is None  # Untracked tree inside a parent repository.
    def git_missing(*args, **kwargs):
        raise FileNotFoundError('git')
    monkeypatch.setattr(runner.subprocess, 'check_output', git_missing)
    assert runner.unit_source_revision(root) is None


def test_confirmation_is_one_shot_and_logs_before_reading_answers(tmp_path, monkeypatch):
    root = tmp_path/'units'
    root.mkdir()
    cards = []
    for index in range(22):
        unit = root/f'fixture-{index:02d}-ps1'
        unit.mkdir()
        cards.append(unit)
        answer = tmp_path/'practice-answers'/f'{unit.name}.parquet'
        answer.parent.mkdir(exist_ok=True)
        answer.write_bytes(b'not read by this test')
    card = {'provenance': {'data_cutoff': '2011-02-07'}, 'targets': {'asset_ids': ['BRL']}}
    monkeypatch.setattr(selection, 'units', lambda *args: cards)
    monkeypatch.setattr(selection, 'read_card', lambda *args: card)
    monkeypatch.setattr(selection, 'read_panels', lambda *args: {'em_fx_ecb_daily.parquet': pd.DataFrame()})
    frozen = tmp_path/'frozen.json'
    development=tmp_path/'development';development.mkdir()
    (development/'identity.json').write_text('{}');(development/'cards.csv').write_text('fixture')
    frozen.write_text(json.dumps(dict(winner='B',confirmation_unopened=True,seeds=research.SEEDS,
        plan_sha256=research.sha(Path('reports/final_alignment/PLAN.md')),
        development_identity_sha256=research.sha(development/'identity.json'),
        development_scores_sha256=research.sha(development/'cards.csv'))))
    out = tmp_path/'confirmation'
    valid_selection = frozen.read_text()
    altered = json.loads(valid_selection)
    altered['plan_sha256'] = 'wrong'
    frozen.write_text(json.dumps(altered))
    with pytest.raises(ValueError, match='plan hash mismatch'):
        selection.confirm(root, frozen, out, development)
    frozen.write_text(valid_selection)
    (development/'cards.csv').write_text('modified evidence')
    with pytest.raises(ValueError, match='development evidence hash mismatch'):
        selection.confirm(root, frozen, out, development)
    (development/'cards.csv').write_text('fixture')
    assert not out.with_name(out.name+'-unblinding.json').exists()
    def fake_run(cases, destination, units_root, arms):
        log = json.loads((tmp_path/'confirmation-unblinding.json').read_text())
        assert log['frozen_selection_sha256'] == research.sha(frozen)
        assert log['winner'] == 'B' and log['cards'] == 22
        assert arms == ['M0', 'release', 'B']
        assert all(Path(row['realized']).name.endswith('-ps1.parquet') for row in cases)
        destination.mkdir()
    monkeypatch.setattr(selection, 'run', fake_run)
    selection.confirm(root, frozen, out, development)
    with pytest.raises(FileExistsError, match='Confirmation already started'):
        selection.confirm(root, frozen, out, development)
    def fail_before_output_directory(*args, **kwargs):
        raise RuntimeError('identity failed after first answer access')
    monkeypatch.setattr(selection, 'run', fail_before_output_directory)
    failed = tmp_path/'failed-confirmation'
    with pytest.raises(RuntimeError, match='identity failed'):
        selection.confirm(root, frozen, failed, development)
    log = tmp_path/'failed-confirmation-unblinding.json'
    first_access = log.read_bytes()
    assert not failed.exists()
    with pytest.raises(FileExistsError, match='Confirmation already started'):
        selection.confirm(root, frozen, failed, development)
    assert log.read_bytes() == first_access
