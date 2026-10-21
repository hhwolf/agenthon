"""Input-only compatibility diagnostics, kept outside the inference image."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from t2agent import m0, numeric_alignment, numeric_v1, numeric_v1_1
from t2agent.io import read_card, read_panels, write_forecast
from t2eval.data import units
from t2eval.final_alignment import dump, sha, git
from t2eval.official import score


def audit(root, published, out):
    out.mkdir(parents=True,exist_ok=False)
    published_rows={r['unit_id']:r for r in json.loads((published/'cards.json').read_text())}
    rows=[];assets=[]
    for unit in units(root,exemplar=True):
        c=read_card(unit/'card.toml');panels=read_panels(unit/'panels');cutoff=str(c['provenance']['data_cutoff']);uid=c['task']['id']
        r=published_rows[uid]
        frame=pd.read_parquet(published/uid/'output/forecast.parquet')
        rationale=(published/uid/'output/forecast_rationale.md').read_text()
        p=numeric_v1.prepare(c,panels,cutoff);cfg=numeric_v1_1.selected_config()
        mean,cov,logs,segments=numeric_v1_1.moments(p,cfg)
        residuals=numeric_v1_1.filtered_residuals(p,cfg)
        strict=m0.horizon_steps(c,p.baseline.histories,strict_ratio=True)
        old=numeric_v1_1.forecast(c,panels,unit/'text',cutoff,2000,r['seed'])
        new=numeric_alignment.forecast(c,panels,unit/'text',cutoff,2000,r['seed'])
        new2=numeric_alignment.forecast(c,panels,unit/'text',cutoff,2000,r['seed'])
        pd.testing.assert_frame_equal(new,new2)
        destination=out/'outputs'/uid/'forecast.parquet';write_forecast(c,new,destination)
        validation=score(unit/'card.toml',destination)
        changed=not np.array_equal(p.baseline.steps,strict)
        equal=np.array_equal(old.value.to_numpy(),new.value.to_numpy())
        if not changed and (not equal or old.attrs['rationale']!=new.attrs['rationale']):
            raise AssertionError('Unexplained compatibility collateral change')
        # Same platform output should be exact; report max error without concealing architecture differences.
        sameorder=frame[['draw','asset','horizon']].equals(old[['draw','asset','horizon']])
        published_diff=float(np.max(np.abs(frame.value.to_numpy()-old.value.to_numpy()))) if sameorder else None
        rows.append(dict(id=uid, published_status=r['status'], wall_seconds=r['wall_seconds'], requests=r['requests_used'],
            bytes=r['output_tree']['bytes'], finite=bool(np.isfinite(frame.value).all()),
            model_path=rationale.split('Method: ',1)[1].split('; rules=')[0] if 'Method: ' in rationale else 'unknown',
            numeric_fallback='Numeric fallback:' in rationale, text_hook_failed='Text hook ignored:' in rationale,
            fhs_rows=len(residuals), fhs_path='fhs5' if len(residuals)>=20 else 'unit_variance_t5_fallback',
            covariance_min_eigenvalue=float(np.linalg.eigvalsh(cov).min()),
            baseline_diagonal_fallback=p.baseline.diagonal_fallback,
            joint_identity_correlation=len(p.increments.tail(1260).dropna())<20,
            steps=p.baseline.steps.tolist(), strict_steps=strict.tolist(), compatibility_changed=changed,
            host_compat_admissible=validation['admissible'],host_compat_fallback=new.attrs.get('fallback') or '',
            host_release_equal=equal,published_host_max_abs_diff=published_diff))
        for a,s in p.histories.items():
            spec=c.get('forecast_spec',{})
            assets.append(dict(id=uid,asset=a,panel=p.panels[a],observations=len(s),first=str(s.index[0].date()),
                last=str(s.index[-1].date()),asof=cutoff,stale_calendar_days=(pd.Timestamp(cutoff)-s.index[-1]).days,
                monthly=p.monthly[a],value_unit=c['targets'].get('value_unit',''),
                observation_periods=m0.cell_metadata(c,'observation_periods','observation_period'),
                raw_duplicates=bool(panels[p.panels[a]].duplicated(['date','asset' if 'asset' in panels[p.panels[a]] else 'asset_id']).any())))
    # Dict cell keys are represented as strings in CSV; JSON row data stays simple.
    pd.DataFrame(rows).to_csv(out/'cards.csv',index=False)
    pd.DataFrame(assets).to_csv(out/'assets.csv',index=False)
    dump(out/'summary.json',dict(units=len(rows),upstream=git(root),published_image=json.loads((published/'summary.json').read_text())['image'],
        published_pass=sum(r['published_status']=='passed' for r in rows),requests=sum(r['requests'] for r in rows),
        numeric_fallbacks=sum(r['numeric_fallback'] for r in rows),fhs_internal_fallbacks=sum(r['fhs_path']!='fhs5' for r in rows),
        changed=[r['id'] for r in rows if r['compatibility_changed']],
        host_admissible=sum(r['host_compat_admissible'] for r in rows),deterministic=True,
        published_run_sha256=sha(published/'cards.json'),
        audit_source_sha256=sha(Path(__file__)),
        runtime_sha256={str(p):sha(p) for p in sorted(Path('t2agent').rglob('*')) if p.suffix in ('.py','.json')},
        published_summary_provenance_note='Initial harness reports old vendor commit/projection104; actual mounted input tree is pinned current checkout. Per-unit input hashes retained. New harness derives provenance and projection from selected roster.'))
    print((out/'summary.json').read_text())


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--units-root',type=Path,required=True);p.add_argument('--published',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();audit(a.units_root,a.published,a.out)
