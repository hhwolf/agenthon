"""Independent repeated-outcome check of M0 scales using only official score math.

Usage: .venv/bin/python scripts/calibration_diagnostic.py <backtest-run> --replicates 20
This is a diagnostic, not a replacement for historical outcomes or the CLI gate checks.
"""
import argparse
import json
from pathlib import Path
import warnings

import numpy as np
import pandas as pd
from qfbench2_track_forecasting.scoring import _composite

from t2agent.io import read_card, read_panels
from t2agent.m0 import distribution
from t2eval.scales import expected_errors

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("run",type=Path)
parser.add_argument("--replicates",type=int,default=20)
args=parser.parse_args()
if args.replicates < 2:
    parser.error("At least two independent replicas are needed")
summary=json.loads((args.run/"summary.json").read_text())
if summary["metadata"]["forecaster"] != "m0":
    parser.error("Use an M0 run")
cases=json.loads((args.run/"roster.json").read_text())
scores=np.empty((len(cases),args.replicates))
whitened=[]
for i,case in enumerate(cases):
    unit=Path(case["unit"])
    card=read_card(unit/"card.toml")
    model=distribution(card,read_panels(unit/"panels"),str(card["provenance"]["data_cutoff"]))
    d=len(model.mean)
    forecast=pd.read_parquet(args.run/"outputs"/card["task"]["id"]/"forecast.parquet")
    samples=forecast.value.to_numpy().reshape(-1,d) # M0 writes the declared grid order.
    scales=expected_errors(model)
    for replica in range(args.replicates):
        rng=np.random.default_rng(np.random.SeedSequence([20261014,i,0xCA11B,replica+1]))
        z=rng.standard_normal(d)
        whitened.extend(z)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore",RuntimeWarning)
            y=model.mean+model.factor@z
        result=_composite(samples,y,weights=(5/7,0,2/7) if d==1 else (.5,.3,.2),
                          tail_levels=(.01,.05,.95,.99),joint="variogram",tail_metric="pinball",ref_scale=scales)
        scores[i,replica]=np.clip(result["composite"],0,8)
    if (i+1)%200==0:
        print(f"Diagnostic: {i+1}/{len(cases)} cards",flush=True)
result={"cards":len(cases),"replicates":args.replicates,"mean":float(scores.mean()),
        "replicate_means":scores.mean(axis=0).tolist(),
        "standard_error_across_replicates":float(scores.mean(axis=0).std(ddof=1)/np.sqrt(args.replicates)),
        "whitened_innovation_variance":float(np.var(whitened)),
        "source_run":str(args.run),"method":"Official _composite, independent Gaussian outcomes, fixed M0 forecasts"}
out=args.run/"calibration-diagnostic.json"
out.write_text(json.dumps(result,indent=2)+"\n")
print(json.dumps(result,indent=2),flush=True)
