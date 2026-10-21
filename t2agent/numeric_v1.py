"""Text-free numeric engine. Evaluation configurations contain rules, never answers."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

import numpy as np
import pandas as pd

from . import m0
from .io import sample_frame


@dataclass(frozen=True)
class Config:
    drift: float = 1.0
    volatility: str = 'recent'
    variance_ratio: bool = False
    tails: str = 'normal'
    rates_reversion: bool = False
    monthly: bool = False
    joint: bool = False
    width: float = 1.0


@dataclass
class Prepared:
    card: dict
    baseline: m0.Distribution
    histories: dict[str, pd.Series]
    increments: pd.DataFrame
    panels: dict[str, str]
    monthly: dict[str, bool]


def prepare(card, panels, asof, *, strict_ratio=False):
    baseline = m0.distribution(card, panels, asof, strict_ratio=strict_ratio)
    histories, steps, names, monthly = {}, {}, {}, {}
    for asset in sorted(baseline.histories):
        for name in sorted(panels):
            frame = panels[name]
            column = 'asset' if 'asset' in frame else 'asset_id'
            rows = frame.loc[frame[column].astype(str) == asset, ['date', 'value']].copy()
            if rows.empty:
                continue
            rows['date'] = pd.to_datetime(rows.date, errors='raise')
            rows = rows.loc[rows.date <= pd.Timestamp(asof)].sort_values('date')
            if rows.date.duplicated().any() or not np.isfinite(rows.value).all():
                raise ValueError(f'Invalid full history: {asset}')
            s = rows.set_index('date').value.astype(float)
            histories[asset] = s
            gaps, good = m0.intervals(s)
            monthly[asset] = bool(len(gaps) and np.median(gaps) > 20)
            changes = s.diff() if card['targets']['target_type'] == 'level' else s
            steps[asset] = changes.iloc[1:].where(good)
            names[asset] = name
            break
    return Prepared(card, baseline, histories, pd.concat(steps, axis=1), names, monthly)


def _variance_ratio(series, horizon):
    h = max(1, int(round(horizon)))
    daily = series.dropna().var(ddof=1)
    rolling = series.rolling(h, min_periods=h).sum().dropna()
    if len(rolling) < max(30, 2*h) or not daily > 0:
        return 1.0
    # Shrink a noisy overlapping estimate, with one rule for all panels.
    return float(np.clip(.5 + .5*rolling.var(ddof=1)/(h*daily), .25, 4.0))


def moments(p: Prepared, config: Config):
    b, card = p.baseline, p.card
    assets = sorted(p.histories)
    grid = [(a, h) for a in card['targets']['asset_ids'] for h in card['targets']['horizons']]
    indexes = np.array([assets.index(a) for a, h in grid])
    anchor = np.array([p.histories[a].iloc[-1] if card['targets']['target_type'] == 'level' else 0. for a, h in grid])
    mean = anchor + config.drift*(b.mean-anchor)
    recent = np.maximum(np.diag(b.step_covariance), 1e-15)
    variances = recent.copy()
    for j, a in enumerate(assets):
        s = p.increments[a].dropna()
        if config.volatility == 'ewma':
            weights = np.exp2(-np.arange(len(s)-1, -1, -1)/60.)
            weights /= weights.sum()
            mu = np.sum(weights*s.to_numpy())
            variances[j] = np.sum(weights*(s.to_numpy()-mu)**2)/max(1.-np.sum(weights**2), .01)
        elif config.volatility == 'blend':
            variances[j] = .5*recent[j] + .5*max(float(s.var(ddof=1)), 1e-15)
        elif config.volatility == 'short_blend20':
            prior = p.increments[a].ewm(halflife=20, min_periods=20).var().shift(1).iloc[-1]
            if not np.isfinite(prior) or prior < 0:
                raise ValueError('Insufficient lagged EWMA history')
            variances[j] = .5*recent[j] + .5*max(float(prior), 1e-15)
        elif config.volatility != 'recent':
            raise ValueError('Unknown volatility rule')
    scale = np.sqrt(variances[indexes]/recent[indexes])
    if config.variance_ratio:
        scale *= np.array([np.sqrt(_variance_ratio(p.increments[a], h)) for (a, _), h in zip(grid, b.steps)])
    if config.rates_reversion:
        for k, (a, _) in enumerate(grid):
            if 'rates' in p.panels[a] and b.steps[k] > 63:
                equilibrium = p.histories[a].tail(1260).mean()
                weight = 1.-np.exp2(-b.steps[k]/756.)
                mean[k] = (1-weight)*mean[k] + weight*equilibrium
    # Index series are modeled in log space; unemployment keeps its last level.
    log_cells = np.zeros(len(grid), dtype=bool)
    if config.monthly:
        for k, (a, _) in enumerate(grid):
            if not p.monthly[a]:
                continue
            s = p.histories[a]
            if a == 'UNRATE':
                mean[k] = anchor[k]
            elif (s > 0).all():
                _, good = m0.intervals(s)
                log_steps = np.log(s).diff().iloc[1:].where(good).dropna()
                trend = log_steps.tail(12).mean()
                mean[k] = np.log(anchor[k]) + b.steps[k]*trend
                # Convert level-scale innovation to local log scale; empirical
                # log volatility handles growing index units over long history.
                lv = log_steps.tail(299).var(ddof=1)
                if config.volatility == 'blend':
                    lv = .5*lv + .5*log_steps.var(ddof=1)
                elif config.volatility == 'ewma':
                    lv = log_steps.ewm(halflife=60).var().iloc[-1]
                scale[k] = np.sqrt(max(lv, 1e-15)/recent[indexes[k]])
                if config.variance_ratio:
                    scale[k] *= np.sqrt(_variance_ratio(log_steps, b.steps[k]))
                log_cells[k] = True
    cov = b.covariance * np.outer(scale, scale) * config.width**2
    if not config.joint:
        return mean, cov, log_cells, None
    aligned = p.increments.tail(1260).dropna()
    corr = aligned.corr().to_numpy() if len(aligned) >= 20 else np.eye(len(assets))
    corr = np.nan_to_num(corr, nan=0.)
    np.fill_diagonal(corr, 1.)
    corr = .8*corr + .2*np.eye(len(assets))
    # Piecewise cumulative variance, monotone per asset. Each segment has one
    # shared multivariate shock and is independent of earlier segments.
    times = np.unique(b.steps)
    cumulative = np.zeros((len(times), len(assets)))
    for j, a in enumerate(assets):
        ks = [k for k, (ga, _) in enumerate(grid) if ga == a]
        order = sorted(ks, key=lambda k: b.steps[k])
        hs = b.steps[order]; vs = np.maximum.accumulate(np.diag(cov)[order])
        cumulative[:, j] = np.interp(times, np.r_[0., hs], np.r_[0., vs])
    segment_cov = []
    previous = np.zeros(len(assets))
    for values in cumulative:
        sd = np.sqrt(np.maximum(values-previous, 0.))
        segment_cov.append(corr*np.outer(sd, sd))
        previous = values
    cov = np.zeros_like(cov)
    for t, segment in zip(times, segment_cov):
        mask = b.steps >= t
        cov += segment[np.ix_(indexes,indexes)] * np.outer(mask,mask)
    cov += np.eye(len(cov))*1e-12
    return mean, cov, log_cells, (times, segment_cov, indexes)


def _tail_scale(rng, count, kind):
    if kind == 'normal':
        return np.ones(count)
    if kind == 'student':
        return np.sqrt(5./rng.chisquare(5., count))
    if kind == 'mixture':
        return np.where(rng.random(count) < .05, 3., 1.)
    raise ValueError('Unknown tail rule')


def sample(p: Prepared, config: Config, n_draws=2000, seed=None):
    mean, covariance, log_cells, segments = moments(p, config)
    rng = np.random.default_rng(m0.resolve_seed(p.card, seed))
    if segments is None:
        factor = np.linalg.cholesky(covariance)
        normals = rng.standard_normal((n_draws, len(mean)))
        noise = np.einsum('ij,kj->ik', normals, factor, optimize=False)
        noise *= _tail_scale(rng, n_draws, config.tails)[:, None]
    else:
        times, covs, indexes = segments
        noise = np.zeros((n_draws, len(mean)))
        for t, cov in zip(times, covs):
            eig, vectors = np.linalg.eigh(cov)
            factor = vectors*np.sqrt(np.maximum(eig, 0.))
            z = rng.standard_normal((n_draws, len(cov)))
            shock = np.einsum('ij,kj->ik', z, factor, optimize=False)
            shock *= _tail_scale(rng, n_draws, config.tails)[:, None]
            noise += shock[:, indexes] * (p.baseline.steps >= t)
    samples = mean+noise
    if log_cells.any():
        samples[:,log_cells] = np.exp(np.clip(samples[:,log_cells], -50, 50))
    if not np.isfinite(samples).all():
        raise ValueError('Nonfinite numeric draws')
    return samples


def selected_config():
    path = Path(__file__).with_name('numeric_config.json')
    return Config(**json.loads(path.read_text()))


def _get(obj, name, default=None):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def apply_text_signal(samples, card, signal, seed):
    """Duck-types the teammate's TextSignal/Scenario; neutral is bit-identical."""
    if signal is None:
        return samples
    scenarios = _get(signal, 'scenarios')
    if scenarios is None:
        scenarios = [signal]
    if not 1 <= len(scenarios) <= 4:
        raise ValueError('Text signal needs 1–4 scenarios')
    assets = card['targets']['asset_ids']
    grid_assets = [a for a in assets for _ in card['targets']['horizons']]
    weights = np.array([float(_get(s, 'weight', 1.)) for s in scenarios])
    if not np.isfinite(weights).all() or np.any(weights < .05) or weights.sum() <= 0:
        raise ValueError('Invalid scenario weights')
    weights /= weights.sum()
    drift = np.array([[float(_get(s, 'drift_sd', {}).get(a, 0.)) for a in grid_assets] for s in scenarios])
    vol = np.array([float(_get(s, 'vol_mult', 1.)) for s in scenarios])
    tail = float(_get(signal, 'tail_mult', 1.))
    if not np.isfinite(drift).all() or not np.isfinite(vol).all() or not np.isfinite(tail):
        raise ValueError('Nonfinite text adjustment')
    if not np.any(drift) and np.all(vol == 1.) and tail == 1.:
        return samples
    drift = np.clip(drift, -1.5, 1.5)
    # Preserve relative scenario directions while bounding aggregate drift.
    overall = weights @ drift
    from .text_map import BINARY_MEAN_DRIFT_LIMIT
    binary = (bool(_get(signal, 'branch_mixture', False)) and len(scenarios) == 2
              and np.all(weights >= .2-1e-12) and np.all(weights <= .8+1e-12)
              and np.all(abs(drift) <= 1.))
    mean_limit = BINARY_MEAN_DRIFT_LIMIT if binary else .5
    drift *= np.minimum(1., mean_limit/np.maximum(abs(overall), 1e-12))[None,:]
    established = any(bool(_get(e, 'established', False)) for e in _get(signal, 'evidence', ()))
    vol = np.clip(vol, .8 if established else 1., 2.)
    tail = np.clip(tail, 1., 2.)
    rng = np.random.default_rng(np.random.SeedSequence([seed, 0x7E87]))
    labels = rng.choice(len(scenarios), len(samples), p=weights)
    center = samples.mean(axis=0); sd = samples.std(axis=0, ddof=1)
    residual = samples-center
    # One extreme-path indicator preserves joint shocks. Named sides expand
    # only residuals on that side; the other side and central body are unchanged.
    from .text_map import TAIL_QUANTILE
    signs_by_asset = _get(signal, 'tail_signs', {}) or {}
    if any(v not in (-1, 0, 1) for v in signs_by_asset.values()):
        raise ValueError('Invalid adverse tail sign')
    signs = np.array([signs_by_asset.get(a, 0) for a in grid_assets])
    z = residual/np.maximum(sd, 1e-12)
    risk = np.where(signs, z*signs, abs(z))
    extreme = np.max(risk, axis=1)
    selected = extreme > np.quantile(extreme, TAIL_QUANTILE)
    side = (signs == 0) | (residual*signs > 0)
    tail_scale = np.where(selected[:, None] & side, tail, 1.)
    return center + residual*vol[labels,None]*tail_scale + drift[labels]*sd


def _wide_random_walk(card, panels, asof, n_draws, seed, *, strict_ratio=False):
    assets = card['targets']['asset_ids']; horizons = card['targets']['horizons']
    histories = {}
    for a in assets:
        try:
            histories[a] = m0.history(panels, a, asof)
        except Exception:
            histories[a] = pd.Series([0.], index=[pd.Timestamp(asof)])
    try:
        steps = m0.horizon_steps(card, histories, strict_ratio=strict_ratio)
    except Exception:
        steps = np.array([max(float(h),1.) for a in assets for h in horizons])
    rng = np.random.default_rng(seed)
    draws = np.empty((n_draws, len(steps)))
    for j, a in enumerate(assets):
        s = histories[a]; level = card['targets'].get('target_type','level') == 'level'
        anchor = float(s.iloc[-1]) if level else 0.
        sd = float((s.diff() if level else s).std())
        floor = max(abs(anchor)*.02, .01)
        sd = max(sd if np.isfinite(sd) else 0., floor)*3.
        cumulative = np.zeros(n_draws); previous = 0.
        for k in sorted(range(len(horizons)), key=lambda k: steps[j*len(horizons)+k]):
            pos = j*len(horizons)+k; h = max(steps[pos],previous)
            cumulative += rng.standard_normal(n_draws)*sd*np.sqrt(h-previous)
            draws[:,pos] = anchor+cumulative; previous=h
    return sample_frame(card, draws)


HOUSE_ENV = ('MODEL_ENDPOINT', 'MODEL_TOKEN', 'MODEL_NAME')


def text_settings():
    return json.loads(Path(__file__).with_name('text_config.json').read_text())


def read_forecast_text(card, panels, text_dir, asof, samples, *, text_signal=None,
                       text_mode=None, text_lambda=None):
    """Called only after numeric sampling; failures cannot change those draws."""
    signal = text_signal
    disabled = ''
    if signal is None:
        if text_dir is None:
            return None, 'Text layer disabled; numeric draws unchanged.'
        import os
        from .text_overlay import apply_text_map, lambda_from_env
        settings = text_settings()
        mode = text_mode or os.environ.get('TEXT_LAYER_MODE') or settings['mode']
        lam = (text_lambda if text_lambda is not None else lambda_from_env()
               if 'TEXT_LAYER_LAMBDA' in os.environ else settings['lambda'])
        if mode == 'numeric_only':
            return None, 'Text layer disabled; numeric draws unchanged.'
        if mode not in ('labels', 'notes_only', 'card_notes_only'):
            raise ValueError(f'Unknown text mode: {mode}')
        if not np.isfinite(lam) or not 0 <= lam <= 1:
            raise ValueError('Text lambda must be finite and in [0,1]')
        if lam == 0:
            return None, 'Text lambda is zero; numeric draws unchanged; zero model requests.'
        from .text_layer.summary import numeric_summary_from
        from .contracts import CallBudget
        from .text_layer import read_text
        summary = numeric_summary_from(card, panels, asof, samples=samples)
        env = None
        if settings.get('house_calls') is not True:
            # Release config disables House: offline before any client exists, whatever MODEL_* says.
            env = {k: v for k, v in os.environ.items() if k not in HOUSE_ENV}
            env['QFBENCH_NETWORK'] = 'none'
        signal = read_text(Path(text_dir).parent, summary, CallBudget(), mode=mode, env=env)
        signal = apply_text_map(signal, summary, lam)
        if env is not None and mode == 'labels':
            disabled = ('House calls are disabled by text_config.json (house_calls=false); '
                        'zero network attempts.')
    # Explicit signals retain the established numeric-hook semantics: already mapped.
    note = str(_get(signal, 'rationale_md', '')).rstrip()
    if disabled:
        note = (note + '\n\n' + disabled).strip()
    if _get(signal, 'evidence') is not None:
        from .text_overlay import evidence_ledger
        note += '\n\n' + evidence_ledger(signal)
    return signal, note or 'Text layer disabled; numeric draws unchanged.'


def forecast(card, panels, text_dir, asof, n_draws=2000, seed=None, *, text_signal=None,
             text_mode=None, text_lambda=None):
    """Numeric → optional text overlay; numeric failures → M0 → wide random walk."""
    seed = m0.resolve_seed(card, seed)
    n_draws = max(200, int(n_draws), card.get('scoring', {}).get('params', {}).get('n_draws_min', 200))
    reasons = []
    text_note = 'No text overlay applied.'
    signal = None
    try:
        config = selected_config()
        prepared = prepare(card, panels, asof)
        samples = sample(prepared, config, n_draws, seed)
        try:
            signal, text_note = read_forecast_text(card, panels, text_dir, asof, samples,
                text_signal=text_signal, text_mode=text_mode, text_lambda=text_lambda)
            adjusted = apply_text_signal(samples, card, signal, seed)
            if not np.isfinite(adjusted).all():
                raise ValueError('Nonfinite text result')
            samples = adjusted
        except Exception as exc:
            signal = None
            text_note = 'Text overlay failed; completed numeric draws preserved.'
            reasons.append(f'Text hook ignored: {type(exc).__name__}: {exc}')
        frame = sample_frame(card, samples)
        method = f'numeric_v1; rules={config}'
    except Exception as exc:
        reasons.append(f'Numeric fallback: {type(exc).__name__}: {exc}')
        try:
            frame = m0.forecast(card, panels, None, asof, n_draws, seed)
            if not np.isfinite(frame.value).all():
                raise ValueError('Nonfinite M0 fallback draws')
            method = 'M0 fallback'
        except Exception as exc:
            reasons.append(f'M0 fallback: {type(exc).__name__}: {exc}')
            frame = _wide_random_walk(card, panels, asof, n_draws, seed)
            method = 'last-resort wide random walk'
    frame.attrs['rationale'] = (
        f"# Numeric forecast: {card['task']['id']}\n\n"
        f"Method: {method}. Cutoff: {asof}. Seed: {seed}. Draws: {n_draws}.\n\n"
        'History is clipped at cutoff; level changes and published return rows are '
        'aligned by date. Monthly steps use the supplied observation-period mapping '
        'from the last released observation. Numeric inference reads no text. '
        'Any supplied text signal adjusts completed numeric draws; neutral is identical.\n\n'
        + ('\n'.join(reasons) if reasons else 'No fallback was required.'))
    frame.attrs['rationale'] += '\n\n' + text_note + '\n'
    frame.attrs['text_signal'] = signal
    frame.attrs['fallback'] = method if method.endswith('fallback') or method.startswith('last-resort') else None
    return frame
