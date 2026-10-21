"""Run with PYTHONPATH=. under each isolated environment; outputs must match."""
import json
import numpy as np
from t2eval.final_alignment import metric
from t2eval.scales import expected_errors
from t2agent.m0 import Distribution
from qfbench2_track_forecasting import scoring
from importlib.metadata import version
rows=[]
for cells in [1,2,8]:
    rng=np.random.default_rng(981+cells)
    x=rng.normal(size=(2000,cells))*np.linspace(.01,1,cells)+np.arange(cells)*50
    mean=x.mean(axis=0);cov=np.atleast_2d(np.cov(x,rowvar=False));sd=np.sqrt(np.diag(cov));y=mean+sd*np.linspace(-2,2,cells)
    model=Distribution(mean,cov,np.linalg.cholesky(cov),np.ones(cells),{},np.array([]),np.array([]),0,False)
    rows.append(dict(cells=cells,divisors=expected_errors(model),result=metric(x,y,expected_errors(model))))
print(json.dumps(dict(common=version('qfbench2-common'),rows=rows),indent=2))
