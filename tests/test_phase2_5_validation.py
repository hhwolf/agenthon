import numpy as np
import pandas as pd
from t2eval.phase2_5 import gates, bootstrap


def rows():
    result=[]
    for label, years in [('historical',range(2009,2025)),('practice',range(2009,2019))]:
        for year in years:
            for n in range(5):
                result.append(dict(unit_id=f'{label}-{year}-{n}',dataset=label,year=year,
                                   family='F1',panel='rates_daily',horizon_bucket='127+',shape='single',score=1.))
    return pd.DataFrame(result)


def test_c1_mean_cap_tradeoff_and_practice_gate():
    base=rows(); base.loc[0,'score']=8.
    candidate=base.copy(); candidate.loc[0,'score']=7.9
    candidate.loc[(candidate.dataset=='historical') & (candidate.year<=2018),'score']+=.003
    ok,reasons,veto=gates(candidate,base,base)
    assert ok and not any(veto.values())
    candidate.loc[candidate.dataset=='practice','score']+=.001
    assert not gates(candidate,base,base)[0]


def test_heldout_veto_is_separate_from_c1():
    base=rows(); candidate=base.copy()
    candidate.loc[(candidate.dataset=='historical') & (candidate.year<=2018),'score']*=.99
    candidate.loc[(candidate.dataset=='historical') & (candidate.year>=2019),'score']*=1.2
    # Give heldout enough cards for inherited major-group threshold.
    extra=candidate.loc[(candidate.dataset=='historical') & (candidate.year>=2019)].copy()
    extra['unit_id']+='-extra'; candidate=pd.concat([candidate,extra],ignore_index=True)
    b_extra=extra.copy();b_extra['score']=1.;base=pd.concat([base,b_extra],ignore_index=True)
    ok,reasons,veto=gates(candidate,base,base)
    assert ok and not reasons and veto['numeric_v1'] and veto['previous']


def test_bootstrap_resamples_years_with_pairing():
    base=rows(); subset=base.loc[base.dataset=='historical'].copy();candidate=subset.copy()
    candidate['score']-=.25
    answer=bootstrap(candidate.sample(frac=1,random_state=2),subset)
    assert answer['years']==16
    np.testing.assert_allclose(answer['ci95'],[-.25,-.25])
