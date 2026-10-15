from t2agent.contracts import MAX_ADMITTED_REQUESTS, CallBudget, TextSignal


def test_neutral_signal_is_one_zero_drift_scenario():
    s=TextSignal.neutral(("GBP","EUR"),reason="offline")
    assert len(s.scenarios) == 1
    assert s.scenarios[0].weight == 1.0
    assert s.scenarios[0].drift_sd == {"GBP":0.0,"EUR":0.0}
    assert s.scenarios[0].vol_mult == 1.0 and s.tail_mult == 1.0
    assert s.fallback_reason == "offline"


def test_budget_refuses_past_limit_and_leaves_house_margin():
    b=CallBudget(limit=2)
    assert [b.spend(),b.spend(),b.spend()] == [True,True,False]
    assert b.used == 2
    assert MAX_ADMITTED_REQUESTS < 25
