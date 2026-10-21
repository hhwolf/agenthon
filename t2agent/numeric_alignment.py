"""Explicit opt-in Final compatibility profile and three frozen research arms.

The published numeric_v1_1 default and its config are unchanged. No answer or
unit-ID logic belongs here. Research arms are not selectable through the CLI.
"""
from dataclasses import replace

import numpy as np

from . import m0, numeric_v1, numeric_v1_1

PANELS = {'rates_daily.parquet', 'g10_fx_daily.parquet', 'em_fx_ecb_daily.parquet',
          'em_transfer_early.parquet'}


def eligible(card, panels, asof):
    targets = card['targets']
    if targets['target_type'] != 'level' or not all(1 <= h <= 4 for h in targets['horizons']):
        return False
    p = numeric_v1.prepare(card, panels, asof)
    return all(not p.monthly[a] and p.panels[a] in PANELS for a in p.histories)


def forecast(card, panels, text_dir, asof, n_draws=2000, seed=None, *, arm='compatibility',
             text_mode=None, text_lambda=None):
    if arm not in {'release', 'compatibility', 'A', 'B', 'C'}:
        raise ValueError('Unknown alignment arm')
    config = None
    active = False
    strict_ratio = arm == 'compatibility'
    if strict_ratio:
        try:
            p = numeric_v1.prepare(card, panels, asof)
            active = not np.array_equal(p.baseline.steps,
                m0.horizon_steps(card, p.baseline.histories, strict_ratio=True))
        except Exception:
            pass  # Strict mapping still propagates through both numeric fallbacks.
    if arm in {'A', 'B', 'C'}:
        try:
            active = eligible(card, panels, asof)
        except Exception:
            pass  # Delegate malformed input to the existing never-fail wrapper.
    if active and arm in {'A', 'B'}:
        try:
            config = numeric_v1_1.selected_config()
            config = replace(config, drift=0.) if arm == 'A' else replace(config, volatility='short_blend20')
        except Exception:
            config = None  # Existing wrapper handles config-load failure and reports its reason.
    if active and arm == 'C':
        text_mode = 'numeric_only'
    result = numeric_v1_1.forecast(card, panels, text_dir, asof, n_draws, seed,
        config=config, strict_ratio=strict_ratio, text_mode=text_mode,
        text_lambda=text_lambda)
    result.attrs['alignment_arm'] = arm
    result.attrs['alignment_active'] = active
    # Leave unaffected/default triplets byte-identical; changed profiles identify themselves.
    if active:
        result.attrs['rationale'] += f'\nOpt-in Final alignment profile: {arm}.\n'
    return result
