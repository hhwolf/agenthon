"""Explicit text variants over the frozen numeric_v1.1 engine.

The numeric engine reads labels after sampling and appends their evidence ledger.
The CLI's normal numeric_v1_1 route uses the committed text_config ship decision.
"""
import os

from . import numeric_v1_1
from .text_overlay import lambda_from_env


def make_forecaster(mode=None, lam=None):
    def _forecast(card, panels, text_dir, asof, n_draws=2000, seed=None):
        return numeric_v1_1.forecast(card, panels, text_dir, asof, n_draws, seed,
            text_mode=mode or os.environ.get('TEXT_LAYER_MODE') or 'labels', text_lambda=lambda_from_env() if lam is None else lam)
    return _forecast


forecast = make_forecaster()
forecast_notes_only_l05 = make_forecaster('notes_only', .5)
forecast_notes_only_l10 = make_forecaster('notes_only', 1.)
forecast_card_notes_only = make_forecaster('card_notes_only', .5)
forecast_labels_l05 = make_forecaster('labels', .5)
forecast_labels_l10 = make_forecaster('labels', 1.)
