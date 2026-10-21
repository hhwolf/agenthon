"""Evaluation-only F4 tail candidates pre-registered in reports/f4_tails/PLAN.md.

Only cards whose [metadata].category is T2-F4 change: their FHS shocks are replaced by a Gaussian factor draw
times a unit-variance per-draw scale (numeric_v1_1's existing tail_scale path). Every other card calls the
unchanged numeric_v1_1.forecast. The runtime package is not modified.
"""
from dataclasses import replace

import numpy as np

from t2agent import numeric_v1_1 as nv

SCALES = {
    't5': lambda rng, n: np.sqrt(3./rng.chisquare(5., n)),                       # t5 * sqrt(3/5)
    't4': lambda rng, n: np.sqrt(2./rng.chisquare(4., n)),                       # t4 * sqrt(1/2)
    'mix10': lambda rng, n: np.where(rng.random(n) < .10, 2.5, 1.)/np.sqrt(1.525),  # .9 + .1*6.25
}


def make_forecaster(kind):
    def forecast(card, panels, text_dir, asof, n_draws=2000, seed=None):
        if card.get('metadata', {}).get('category') != 'T2-F4':
            return nv.forecast(card, panels, text_dir, asof, n_draws, seed)
        config, scale = nv.selected_config, nv.tail_scale

        def tail_scale(rng, count, name):
            return SCALES[kind](rng, count) if name == 'f4_' + kind else scale(rng, count, name)
        nv.selected_config = lambda: replace(config(), tails='f4_' + kind)
        nv.tail_scale = tail_scale
        try:
            return nv.forecast(card, panels, text_dir, asof, n_draws, seed)
        finally:
            nv.selected_config, nv.tail_scale = config, scale
    return forecast


forecast_t5 = make_forecaster('t5')
forecast_t4 = make_forecaster('t4')
forecast_mix10 = make_forecaster('mix10')
