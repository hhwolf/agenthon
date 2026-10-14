"""Predeclared year-blocked ablations; official scoring, isolated final holdout."""
from __future__ import annotations
from dataclasses import asdict, replace
import argparse
import hashlib
import json
from pathlib import Path
import warnings

import numpy as np
import pandas as pd
from qfbench2_track_forecasting.scoring import _composite

from t2agent.io import read_card, read_panels
from t2agent.numeric_v1 import Config, prepare, sample
from t2agent import numeric_v1
from t2eval.data import target_labels
from t2eval.scales import expected_errors

RUN = Path('.eval/runs/backtest-m0-a9a5d3fc5371')
OUT = Path('reports/phase2')
CACHE = Path('.eval/phase2')
GROUPS = ['family', 'panel', 'horizon_bucket', 'shape']


def metrics(df):
    return {'cards':len(df), 'mean':float(df.score.mean()), 'median':float(df.score.median()),
            'capped':int((df.score >= 8).sum())}


def groups(df):
    return {key:[{'group':str(name), **metrics(g)} for name,g in df.groupby(key)] for key in GROUPS+['year']}


def accepted(candidate, previous):
    reasons = []
    a,b = metrics(candidate),metrics(previous)
    if a['mean'] >= b['mean']: reasons.append('mean did not improve')
    if a['capped'] > b['capped']: reasons.append('cap count increased')
    for key in GROUPS:
        for name,g in candidate.groupby(key):
            threshold=20 if key=='panel' and name=='macro_monthly' else 40
            if len(g) < threshold: continue
            old = previous.loc[previous[key]==name,'score'].mean()
            if g.score.mean() > 1.10*old:
                reasons.append(f'{key}={name} worsened >10%')
    return not reasons, reasons


class Evaluation:
    def __init__(self, holdout=False):
        self.rows=pd.read_csv(RUN/'cards.csv')
        self.rows['year']=pd.to_datetime(self.rows['asof']).dt.year
        self.rows=self.rows.loc[self.rows.year>=2019 if holdout else self.rows.year<=2018].reset_index(drop=True)
        self.roster={Path(r['unit']).name:r for r in json.loads((RUN/'roster.json').read_text())}
        self.prepared={}
        self.signature=hashlib.sha256(Path(numeric_v1.__file__).read_bytes()+Path(__file__).read_bytes()).hexdigest()[:12]
        self.partition='holdout' if holdout else 'development'
        CACHE.mkdir(parents=True,exist_ok=True)
        self.load()

    def load(self):
        for index,(idx,row) in enumerate(self.rows.iterrows()):
            case=self.roster[row.unit_id]; unit=Path(case['unit'])
            card=read_card(unit/'card.toml')
            with warnings.catch_warnings():
                warnings.simplefilter('ignore',RuntimeWarning)
                p=prepare(card,read_panels(unit/'panels'),row['asof'])
            grid=[(a,h) for a in card['targets']['asset_ids'] for h in card['targets']['horizons']]
            y=pd.read_parquet(case['realized']).set_index(['asset','horizon']).loc[grid,'value'].to_numpy()
            labels,_=target_labels(card)
            endpoints=[x.end_time if isinstance(x,pd.Period) else x for x in labels.values()]
            self.rows.loc[idx,'target_end']=str(max(endpoints).date())
            self.prepared[row.unit_id]=(p,y,expected_errors(p.baseline))
            if (index+1)%200==0:print(f'Prepared {self.partition}: {index+1}/{len(self.rows)}',flush=True)

    def evaluate(self, config):
        identity=hashlib.sha256(json.dumps(asdict(config),sort_keys=True).encode()).hexdigest()[:12]
        path=CACHE/f'{self.signature}-{self.partition}-{identity}.csv'
        if path.exists():return pd.read_csv(path)
        df=self.rows[['unit_id','asof','year','target_end',*GROUPS]].copy()
        scores=[]
        for index,uid in enumerate(df.unit_id):
            p,y,scales=self.prepared[uid]
            draws=sample(p,config,2000)
            raw=_composite(draws,y,weights=(5/7,0,2/7) if len(y)==1 else (.5,.3,.2),
                           tail_levels=(.01,.05,.95,.99),joint='variogram',tail_metric='pinball',ref_scale=scales)
            scores.append(float(np.clip(raw['composite'],0,8)))
        df['score']=scores
        df.to_csv(path,index=False)
        return df


def primary(df):return df.loc[df.year.between(2009,2018)].copy()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['develop','holdout'])
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    if args.mode=='holdout':
        frozen=json.loads((OUT/'frozen-selection.json').read_text())
        config=Config(**frozen['config'])
        assert config==numeric_v1.selected_config()
        e=Evaluation(holdout=True)
        baseline=e.evaluate(Config()); winner=e.evaluate(config)
        baseline.to_csv(OUT/'holdout-m0.csv',index=False);winner.to_csv(OUT/'holdout-numeric_v1.csv',index=False)
        development=pd.read_csv(OUT/'development-selected.csv')
        dev_m0=pd.read_csv(OUT/'development-m0.csv')
        # Descriptive all-years score uses the frozen runtime rule throughout;
        # primary CV width is separately retained and need not equal final width.
        dev_final=Evaluation().evaluate(config)
        dev_final.to_csv(OUT/'development-final-runtime.csv',index=False)
        paired=winner.set_index('unit_id').score-baseline.set_index('unit_id').score
        year_delta=winner.assign(delta=paired.reindex(winner.unit_id).to_numpy()).groupby('year').delta.mean()
        summary={'config':asdict(config),'primary_cv':metrics(primary(development)),
                 'primary_m0':metrics(primary(dev_m0)), 'holdout':metrics(winner),'holdout_m0':metrics(baseline),
                 'all_frozen':metrics(pd.concat([dev_final,winner])), 'all_m0':metrics(pd.concat([dev_m0,baseline])),
                 'holdout_year_wins':int((year_delta<0).sum()),'holdout_years':len(year_delta),
                 'holdout_equal_year_delta':float(year_delta.mean()),
                 'holdout_year_cluster_se':float(year_delta.std(ddof=1)/np.sqrt(len(year_delta))),
                 'holdout_breakdowns':groups(winner),'holdout_m0_breakdowns':groups(baseline)}
        (OUT/'final-evaluation.json').write_text(json.dumps(summary,indent=2)+'\n')
        print(json.dumps({k:v for k,v in summary.items() if 'breakdown' not in k},indent=2),flush=True)
        return
    if (OUT/'frozen-selection.json').exists():
        raise SystemExit('Selection already frozen; refusing to overwrite it.')
    e=Evaluation();best=Config();previous=e.evaluate(best);best_name='m0_2000'
    previous.to_csv(OUT/'development-m0.csv',index=False)
    records=[{'name':best_name,'previous':None,'accepted':True,'config':asdict(best),
              **metrics(primary(previous)),'breakdowns':groups(primary(previous))}]
    stages=[('1_drift',[('zero',{'drift':0.}),('shrunk',{'drift':.25})]),
            ('2_volatility',[('ewma',{'volatility':'ewma'}),('blend',{'volatility':'blend'})]),
            ('2_horizon',[('empirical_ratio',{'variance_ratio':True})]),
            ('3_tails',[('student5',{'tails':'student'}),('mixture5pct',{'tails':'mixture'})]),
            ('4_rates',[('mean_reversion',{'rates_reversion':True})]),
            ('5_monthly',[('log_trend_persistence',{'monthly':True})]),
            ('6_joint',[('long_shrinkage_paths',{'joint':True})])]
    for stage, alternatives in stages:
        eligible=[]
        for suffix,changes in alternatives:
            config=replace(best,**changes); name=f'{stage}_{suffix}'
            df=e.evaluate(config); held=primary(df)
            ok,reasons=accepted(held,primary(previous))
            rec={'name':name,'previous':best_name,'eligible':ok,'accepted':False,'reasons':reasons,
                 'config':asdict(config),**metrics(held),'delta':float(held.score.mean()-primary(previous).score.mean()),
                 'breakdowns':groups(held)}
            records.append(rec);df.to_csv(OUT/f'ablation-{name}.csv',index=False)
            print(json.dumps({k:v for k,v in rec.items() if k!='breakdowns'}),flush=True)
            if ok:eligible.append((held.score.mean(),config,df,rec))
        if eligible:
            _,best,previous,record=min(eligible,key=lambda x:x[0]);record['accepted']=True;best_name=record['name']
        (OUT/'ablations.json').write_text(json.dumps(records,indent=2)+'\n')
    # Only outcome-fitted parameter. Expanding folds with label purging.
    options={w:e.evaluate(replace(best,width=w)) for w in (.9,1.,1.1,1.2)}
    fold_values={}; cv=previous.copy()
    for year in range(2009,2019):
        train=(previous.year<year)&(previous.target_end<f'{year}-01-01')
        w=min(options,key=lambda w:options[w].loc[train,'score'].mean())
        test=cv.year==year;cv.loc[test,'score']=options[w].loc[test,'score'];fold_values[str(year)]=w
    ok,reasons=accepted(primary(cv),primary(previous))
    final_train=(previous.target_end<'2019-01-01')
    final_width=min(options,key=lambda w:options[w].loc[final_train,'score'].mean()) if ok else 1.
    records.append({'name':'7_width_fold_fitted','previous':best_name,'accepted':ok,'reasons':reasons,
                    'fold_widths':fold_values,'final_width':final_width,**metrics(primary(cv)),
                    'delta':float(primary(cv).score.mean()-primary(previous).score.mean()),
                    'breakdowns':groups(primary(cv))})
    cv.to_csv(OUT/'ablation-7_width_fold_fitted.csv',index=False)
    if ok:best=replace(best,width=final_width);previous=cv;best_name='7_width_fold_fitted'
    previous.to_csv(OUT/'development-selected.csv',index=False)
    (OUT/'ablations.json').write_text(json.dumps(records,indent=2)+'\n')
    frozen={'config':asdict(best),'winner':best_name,'source_signature':e.signature,'n_draws':2000,
            'protocol_sha256':hashlib.sha256((OUT/'VALIDATION.md').read_bytes()).hexdigest(),
            'primary_cv':metrics(primary(previous)), 'width_options':[.9,1.,1.1,1.2]}
    (OUT/'frozen-selection.json').write_text(json.dumps(frozen,indent=2)+'\n')
    Path('t2agent/numeric_config.json').write_text(json.dumps(asdict(best),indent=2)+'\n')
    print('FROZEN: '+json.dumps(frozen),flush=True)


if __name__=='__main__':main()
