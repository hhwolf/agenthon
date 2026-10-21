"""Phase 2.5 numeric rules; the Phase 2 engine and frozen config stay intact."""
from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import m0, numeric_v1 as v1
from .io import sample_frame


@dataclass(frozen=True)
class Config(v1.Config):
    drift: float = .25
    monthly: bool = True
    joint: bool = True
    term_tau: float = 0.
    vol_floor: float = 0.
    monthly_damping: float = 1.
    monthly_window: int = 12
    momentum: float = 0.
    components: tuple = ()


def config_from_dict(data):
    data = dict(data)
    data['components'] = tuple(config_from_dict(c) for c in data.get('components', ()))
    return Config(**data)


def selected_config():
    return config_from_dict(json.loads(Path(__file__).with_name('numeric_v1_1_config.json').read_text()))


def _joint(p, cov):
    assets = sorted(p.histories)
    grid = [(a, h) for a in p.card['targets']['asset_ids'] for h in p.card['targets']['horizons']]
    indexes = np.array([assets.index(a) for a, _ in grid])
    aligned = p.increments.tail(1260).dropna()
    corr = aligned.corr().to_numpy() if len(aligned) >= 20 else np.eye(len(assets))
    corr = np.nan_to_num(corr, nan=0.)
    np.fill_diagonal(corr, 1.)
    corr = .8*corr + .2*np.eye(len(assets))
    times = np.unique(p.baseline.steps)
    cumulative = np.zeros((len(times), len(assets)))
    for j, a in enumerate(assets):
        ks = sorted([k for k, (ga, _) in enumerate(grid) if ga == a], key=lambda k: p.baseline.steps[k])
        cumulative[:, j] = np.interp(times, np.r_[0., p.baseline.steps[ks]],
                                     np.r_[0., np.maximum.accumulate(np.diag(cov)[ks])])
    previous = np.zeros(len(assets)); covs = []
    result = np.zeros_like(cov)
    for t, values in zip(times, cumulative):
        sd = np.sqrt(np.maximum(values-previous, 0.))
        segment = corr*np.outer(sd, sd)
        covs.append(segment); previous = values
        mask = p.baseline.steps >= t
        result += segment[np.ix_(indexes, indexes)]*np.outer(mask, mask)
    result += np.eye(len(result))*1e-12
    return result, (times, covs, indexes)


def moments(p, config):
    changed = (config.term_tau or config.vol_floor or config.monthly_damping != 1.
               or config.monthly_window != 12 or config.momentum)
    if not changed:
        return v1.moments(p, config)
    mean, cov, logs, _ = v1.moments(p, replace(config, joint=False))
    grid = [(a, h) for a in p.card['targets']['asset_ids'] for h in p.card['targets']['horizons']]
    scale = np.ones(len(grid))
    for k, (a, _) in enumerate(grid):
        h = p.baseline.steps[k]
        series = p.histories[a]
        changes = p.increments[a]
        if logs[k]:
            _, good = m0.intervals(series)
            changes = np.log(series).diff().iloc[1:].where(good)
            mean[k] = np.log(series.iloc[-1]) + h*config.monthly_damping*changes.dropna().tail(config.monthly_window).mean()
        recent = max(float(cov[k, k])/h/config.width**2, 1e-15)
        long = max(float(changes.dropna().var(ddof=1)), 1e-15)
        weight = np.exp(-h/config.term_tau) if config.term_tau else 1.
        variance = max(weight*recent + (1-weight)*long, config.vol_floor*long)
        scale[k] = np.sqrt(variance/recent)
    cov *= np.outer(scale, scale)
    if config.joint:
        cov, segments = _joint(p, cov)
    else:
        segments = None
    if config.momentum:
        for k, (a, _) in enumerate(grid):
            if not p.monthly[a]:
                anchor = p.histories[a].iloc[-1] if p.card['targets']['target_type'] == 'level' else 0.
                direction = np.sign(p.increments[a].dropna().tail(126).sum())
                mean[k] = anchor + direction*config.momentum*np.sqrt(cov[k, k])
    return mean, cov, logs, segments


def tail_scale(rng, count, kind):
    if kind == 'student_unit':
        return np.sqrt(3./rng.chisquare(5., count))
    if kind == 'mixture_unit':
        return np.where(rng.random(count) < .05, 3., 1.)/np.sqrt(1.4)
    return v1._tail_scale(rng, count, kind)


def _factor(cov, inverse=False):
    eig, vectors = np.linalg.eigh(np.atleast_2d(cov))
    floor = max(float(eig.max()), 1e-15)*1e-10
    values = np.where(eig > floor, 1./np.sqrt(np.maximum(eig, floor)), 0.) if inverse else np.sqrt(np.maximum(eig, 0.))
    return vectors*values


def filtered_residuals(p, config):
    result = {}
    for a in sorted(p.histories):
        s = p.increments[a]
        if config.monthly and p.monthly[a] and a != 'UNRATE' and (p.histories[a] > 0).all():
            _, good = m0.intervals(p.histories[a])
            s = np.log(p.histories[a]).diff().iloc[1:].where(good)
        # The filter at a change uses only earlier changes, never the change itself.
        prior = s.ewm(halflife=60, min_periods=20).var().shift(1)
        result[a] = s / np.sqrt(prior.clip(lower=1e-15))
    residuals = pd.DataFrame(result).replace([np.inf, -np.inf], np.nan).dropna()
    return residuals.to_numpy() - residuals.mean().to_numpy()


def block_shock(rng, residuals, steps, covariance, count):
    """Independent fixed-length block sums with exact population-covariance scaling."""
    if len(residuals) < 20:
        z = rng.standard_normal((count, len(covariance)))
        return np.einsum('ij,kj->ik', z, _factor(covariance))*tail_scale(rng, count, 'student_unit')[:, None]
    length = max(1, int(round(steps)))
    blocks, rest = divmod(length, 5)
    noise = np.zeros((count, residuals.shape[1]))
    theoretical = np.zeros_like(covariance)
    for size, repetitions in ((5, blocks), (rest, int(rest > 0))):
        if not repetitions:
            continue
        sums = np.lib.stride_tricks.sliding_window_view(residuals, size, axis=0).sum(axis=-1)
        sums = sums-sums.mean(axis=0)
        theoretical += repetitions*np.atleast_2d(np.cov(sums, rowvar=False, ddof=0))
        picks = rng.integers(len(sums), size=(count, repetitions))
        noise += sums[picks].sum(axis=1)
    # Symmetric whitening preserves orientation of cross-asset tail events.
    eigen, vectors = np.linalg.eigh(theoretical)
    floor = max(float(eigen.max()), 1e-15)*1e-10
    rank = eigen > floor
    if not rank.all():
        # Supply missing independent dimensions for collinear histories.
        missing = vectors[:, ~rank]
        noise += np.einsum('ij,kj->ik', rng.standard_normal((count, missing.shape[1])), missing)
        theoretical += np.einsum('ij,kj->ik', missing, missing)
    inv = _factor(theoretical, inverse=True)
    whitening = np.einsum('ij,kj->ik', inv, np.linalg.eigh(theoretical)[1])
    root = _factor(covariance)
    target = np.einsum('ij,kj->ik', root, np.linalg.eigh(covariance)[1])
    normalized = np.einsum('ij,jk->ik', noise, whitening, optimize=False)
    return np.einsum('ij,jk->ik', normalized, target, optimize=False)


def sample(p, config, n_draws=2000, seed=None):
    seed = m0.resolve_seed(p.card, seed)
    if config.components:
        children = np.random.SeedSequence([seed, 0x2511]).generate_state(2)
        n = n_draws//2
        return np.concatenate([sample(p, config.components[0], n, int(children[0])),
                               sample(p, config.components[1], n_draws-n, int(children[1]))])
    mean, cov, logs, segments = moments(p, config)
    rng = np.random.default_rng(seed)
    if segments is None:
        noise = np.einsum('ij,kj->ik', rng.standard_normal((n_draws, len(mean))), np.linalg.cholesky(cov), optimize=False)
        noise *= tail_scale(rng, n_draws, config.tails)[:, None]
    else:
        times, covs, indexes = segments
        noise = np.zeros((n_draws, len(mean)))
        residuals = filtered_residuals(p, config) if config.tails == 'fhs5' else None
        previous = 0.
        for t, covariance in zip(times, covs):
            if residuals is not None:
                shock = block_shock(rng, residuals, t-previous, covariance, n_draws)
            else:
                factor = _factor(covariance)
                z = rng.standard_normal((n_draws, len(covariance)))
                shock = np.einsum('ij,kj->ik', z, factor, optimize=False)
                shock *= tail_scale(rng, n_draws, config.tails)[:, None]
            noise += shock[:, indexes]*(p.baseline.steps >= t)
            previous = t
    draws = mean+noise
    if logs.any():
        draws[:, logs] = np.exp(np.clip(draws[:, logs], -50, 50))
    if not np.isfinite(draws).all():
        raise ValueError('Nonfinite numeric_v1.1 draws')
    return draws


def forecast(card, panels, text_dir, asof, n_draws=2000, seed=None, *, text_signal=None,
             text_mode=None, text_lambda=None):
    seed = m0.resolve_seed(card, seed)
    n_draws = max(200, int(n_draws), card.get('scoring', {}).get('params', {}).get('n_draws_min', 200))
    reasons = []
    text_note = 'No text overlay applied.'
    signal = None
    try:
        config = selected_config()
        draws = sample(v1.prepare(card, panels, asof), config, n_draws, seed)
        try:
            signal, text_note = v1.read_forecast_text(card, panels, text_dir, asof, draws,
                text_signal=text_signal, text_mode=text_mode, text_lambda=text_lambda)
            adjusted = v1.apply_text_signal(draws, card, signal, seed)
            if not np.isfinite(adjusted).all():
                raise ValueError('Nonfinite text result')
            draws = adjusted
        except Exception as exc:
            signal = None
            text_note = 'Text overlay failed; completed numeric draws preserved.'
            reasons.append(f'Text hook ignored: {type(exc).__name__}: {exc}')
        frame = sample_frame(card, draws)
        method = f'numeric_v1.1; rules={asdict(config)}'; fallback = None
    except Exception as exc:
        reasons.append(f'Numeric fallback: {type(exc).__name__}: {exc}')
        try:
            frame = m0.forecast(card, panels, None, asof, n_draws, seed)
            if not np.isfinite(frame.value).all():
                raise ValueError('Nonfinite M0 draws')
            method = fallback = 'M0 fallback'
        except Exception as exc:
            reasons.append(f'M0 fallback: {type(exc).__name__}: {exc}')
            frame = v1._wide_random_walk(card, panels, asof, n_draws, seed)
            method = fallback = 'last-resort wide random walk'
    frame.attrs['fallback'] = fallback
    frame.attrs['rationale'] = (f"# Numeric forecast: {card['task']['id']}\n\nMethod: {method}. "
        f"Cutoff: {asof}. Seed: {seed}. Draws: {n_draws}.\n\n"
        'The numeric engine uses only pre-cutoff history. Monthly release/observation mapping is preserved. '
        'Neutral text signals leave numeric draws identical.\n\n'+ ('\n'.join(reasons) or 'No fallback was required.'))
    frame.attrs['rationale'] += '\n\n' + text_note + '\n'
    frame.attrs['text_signal'] = signal
    return frame
