"""Frozen-M0 calibration and counterfactual loss diagnostics; never used in inference."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import warnings
import numpy as np
import pandas as pd
from scipy.special import ndtr
from qfbench2_track_forecasting.scoring import _composite
from t2agent.io import read_card, read_panels
from t2agent.m0 import distribution
from t2eval.scales import expected_errors
from t2eval.data import target_labels


def composite(samples, y, scales):
    d = len(y)
    raw = _composite(samples, y, weights=(5/7, 0, 2/7) if d == 1 else (.5, .3, .2),
                     tail_levels=(.01, .05, .95, .99), joint='variogram',
                     tail_metric='pinball', ref_scale=scales)
    return float(np.clip(raw['composite'], 0, 8))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, default=Path('.eval/runs/backtest-m0-a9a5d3fc5371'))
    parser.add_argument('--out', type=Path, default=Path('reports/phase2'))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    roster = json.loads((args.run/'roster.json').read_text())
    original = pd.read_csv(args.run/'cards.csv').set_index('unit_id')
    cells, losses, caps = [], [], []
    union = pd.read_parquet('.eval/union/union.parquet')
    for index, case in enumerate(roster):
        unit = Path(case['unit'])
        card = read_card(unit/'card.toml')
        uid = card['task']['id']
        old = original.loc[uid]
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            model = distribution(card, read_panels(unit/'panels'), str(card['provenance']['data_cutoff']))
        grid = [(a,h) for a in card['targets']['asset_ids'] for h in card['targets']['horizons']]
        realized = pd.read_parquet(case['realized']).set_index(['asset','horizon'])
        y = realized.loc[grid,'value'].to_numpy()
        frame = pd.read_parquet(args.run/'outputs'/uid/'forecast.parquet')
        samples = frame.pivot(index='draw', columns=['asset','horizon'], values='value').loc[:,grid].to_numpy()
        sd = np.sqrt(model.covariance.diagonal())
        z = (y-model.mean)/sd
        anchor = np.array([model.histories[a].iloc[-1] if card['targets']['target_type']=='level' else 0 for a,h in grid])
        scales = expected_errors(model)
        baseline = composite(samples,y,scales)
        assert abs(baseline-float(old.score)) < 1e-9, (uid,baseline,old.score)
        residuals = samples-model.mean
        center_oracle = composite(residuals+y,y,scales)
        width_scores = {w:composite(model.mean+w*residuals,y,scales) for w in (.5,1.,2.,4.)}
        both = min(composite(y+w*residuals,y,scales) for w in (.5,1.,2.,4.))
        width_oracle = min(width_scores.values())
        losses.append({'unit_id':uid,'panel':old.panel,'horizon_bucket':old.horizon_bucket,
                       'family':old.family,'shape':old['shape'],'asof':old['asof'],'m0':baseline,
                       'zero_drift':composite(anchor+residuals,y,scales),
                       'width_2':width_scores[2.], 'center_oracle':center_oracle,'width_oracle':width_oracle,
                       'oracle_width':min(width_scores,key=width_scores.get),
                       'center_shapley':.5*((baseline-center_oracle)+(width_oracle-both)),
                       'width_shapley':.5*((baseline-width_oracle)+(center_oracle-both)),
                       'oracle_residual':both})
        for k,(asset,horizon) in enumerate(grid):
            cells.append({'unit_id':uid,'panel':old.panel,'horizon_bucket':old.horizon_bucket,
                          'asof':old['asof'],'asset':asset,'horizon':horizon,'steps':model.steps[k],
                          'outcome':y[k],'center':model.mean[k],'sd':sd[k],'anchor':anchor[k],
                          'z':z[k],'pit':ndtr(z[k]),'empirical_pit':float(np.mean(samples[:,k]<=y[k])),
                          'coverage90':abs(z[k])<=1.6448536269514722,
                          'coverage98':abs(z[k])<=2.3263478740408408,
                          'sample_coverage90':np.quantile(samples[:,k],.05)<=y[k]<=np.quantile(samples[:,k],.95),
                          'sample_coverage98':np.quantile(samples[:,k],.01)<=y[k]<=np.quantile(samples[:,k],.99)})
        if float(old.unclipped)>=8:
            k=int(np.argmax(abs(z))); asset,horizon=grid[k]
            improvement=abs(z[k])-abs((y[k]-anchor[k])/sd[k])
            target,_=target_labels(card)
            endpoint=target[asset,horizon]
            endpoint=endpoint.end_time if isinstance(endpoint,pd.Period) else endpoint
            hist=model.histories[asset]
            future=union.loc[(union.asset==asset)&(union.date>hist.index[-1])&(union.date<=endpoint)].sort_values('date').value.to_numpy()
            increments=np.diff(np.r_[hist.iloc[-1],future]) if card['targets']['target_type']=='level' else future
            pre_sd=np.sqrt(model.step_covariance[sorted(model.histories).index(asset),sorted(model.histories).index(asset)])
            vol_ratio=float(np.std(increments,ddof=1)/pre_sd) if len(increments)>1 else 1.
            directional_t=float(abs(np.mean(increments))/(np.std(increments,ddof=1)/np.sqrt(len(increments)))) if len(increments)>1 and np.std(increments)>0 else 0.
            label=('monthly/vintage issue' if case['monthly'] else 'drift extrapolation' if improvement>.5*abs(z[k])
                   else 'vol spike' if vol_ratio>=2 and directional_t<2 else 'regime break')
            caps.append({'unit_id':uid,'panel':old.panel,'assets':','.join(card['targets']['asset_ids']),
                         'asof':old['asof'],'horizons':old.horizons,'worst_asset':asset,'worst_horizon':horizon,
                         'z':z[k],'zero_drift_z':(y[k]-anchor[k])/sd[k], 'anchor':anchor[k],
                         'center':model.mean[k],'outcome':y[k],'sd':sd[k],
                         'score_unclipped':float(old.unclipped),'class':label,'future_vol_ratio':vol_ratio,'future_direction_t':directional_t})
        if (index+1)%200==0: print(f'Diagnosed {index+1}/{len(roster)}',flush=True)
    c=pd.DataFrame(cells); l=pd.DataFrame(losses); cap=pd.DataFrame(caps)
    c.to_csv(args.out/'m0-calibration-cells.csv',index=False)
    l.to_csv(args.out/'m0-loss-counterfactuals.csv',index=False)
    cap.to_csv(args.out/'m0-capped-cards.csv',index=False)
    groups=[]
    for (panel,bucket),g in c.groupby(['panel','horizon_bucket']):
        counts=np.histogram(g.pit,bins=np.linspace(0,1,11))[0]
        groups.append({'panel':panel,'horizon_bucket':bucket,'cards':g.unit_id.nunique(),'cells':len(g),
                       'coverage90':g.coverage90.mean(),'coverage98':g.coverage98.mean(),
                       'sample_coverage90':g.sample_coverage90.mean(),'sample_coverage98':g.sample_coverage98.mean(),
                       'mean_z':g.z.mean(),'median_z':g.z.median(),'rms_z':np.sqrt(np.mean(g.z**2)),
                       **{f'pit_{i}':int(v) for i,v in enumerate(counts)}})
    grouped=pd.DataFrame(groups)
    grouped.to_csv(args.out/'m0-calibration-groups.csv',index=False)
    l.groupby(['panel','horizon_bucket']).mean(numeric_only=True).reset_index().to_csv(args.out/'m0-loss-groups.csv',index=False)
    summary={'cards':len(l),'cells':len(c),'capped':len(cap),'coverage90':c.coverage90.mean(),
             'coverage98':c.coverage98.mean(),'mean_z':c.z.mean(),'median_z':c.z.median(),
             'rms_z':float(np.sqrt(np.mean(c.z**2))),
             'counterfactual_means':l.mean(numeric_only=True).to_dict(),
             'capped_classes':cap['class'].value_counts().to_dict()}
    (args.out/'m0-diagnosis.json').write_text(json.dumps(summary,indent=2)+'\n')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    panels=sorted(c.panel.unique()); buckets=['1–21','22–63','64–126','127+']
    fig,axes=plt.subplots(len(panels),4,figsize=(14,3*len(panels)),squeeze=False)
    for i,panel in enumerate(panels):
        for j,bucket in enumerate(buckets):
            ax=axes[i,j]; g=c[(c.panel==panel)&(c.horizon_bucket==bucket)]
            if not len(g): ax.axis('off');continue
            ax.hist(g.pit,bins=np.linspace(0,1,11),weights=np.ones(len(g))/len(g),color='#246782')
            ax.axhline(.1,color='#b7472a',linestyle='--',linewidth=1)
            ax.set_title(f'{panel}\n{bucket}; {g.unit_id.nunique()} cards / {len(g)} cells',fontsize=9)
            ax.set_xlim(0,1); ax.set_ylim(0,.7)
            ax.text(.5,.92,f'90%: {g.coverage90.mean():.1%}; 98%: {g.coverage98.mean():.1%}',transform=ax.transAxes,ha='center',fontsize=8)
    fig.suptitle('Frozen M0: analytic marginal PIT by panel × maximum card horizon\nCells on a card and overlapping cards are dependent; dashed line is uniform probability.',fontsize=12)
    fig.tight_layout(rect=[0,0,1,.95]);fig.savefig(args.out/'m0-pit-histograms.png',dpi=150);plt.close(fig)
    print(json.dumps(summary,indent=2))

if __name__=='__main__': main()
