"""Analytic M0 expected errors (§5), not a replacement for the official scorer."""
import numpy as np
from scipy.integrate import quad
from scipy.special import gamma, hyp1f1, ndtr, ndtri

from t2agent.m0 import Distribution


def expected_errors(model: Distribution, tail_levels=(0.01, 0.05, 0.95, 0.99)) -> dict[str, float]:
    if not len(tail_levels) or any(not 0 < x < 1 for x in tail_levels):
        raise ValueError("Tail levels must lie strictly between zero and one")
    mean, cov = model.mean, model.covariance
    sd = np.sqrt(np.diag(cov))
    marginal = sd.mean() / np.sqrt(np.pi)
    z = ndtri(tail_levels)
    tail = sd.mean() * np.mean(np.exp(-z*z/2) / np.sqrt(2*np.pi))
    joint = 0.0
    for i in range(len(mean)):
        for j in range(i):
            delta = abs(mean[i] - mean[j])
            variance = max(0.0, cov[i,i] + cov[j,j] - 2*cov[i,j])
            if variance == 0:
                continue
            scale = np.sqrt(variance)
            ratio = delta / scale
            # Avoid subtracting two huge almost-equal moments. Integrate the
            # centred random variable; ±12 standard deviations omit <4e-33 mass.
            if ratio > 100:
                def centred(z):
                    # Rationalized sqrt(delta+s*z)-sqrt(delta), stable for tiny s.
                    return scale*z / (np.sqrt(delta+scale*z)+np.sqrt(delta))
                def density(z):
                    return np.exp(-z*z/2)/np.sqrt(2*np.pi)
                first = quad(lambda z: centred(z)*density(z), -12, 12, epsabs=1e-14)[0]
                second = quad(lambda z: centred(z)**2*density(z), -12, 12, epsabs=1e-14)[0]
                v = max(0.0, second-first*first)
            else:
                e_abs = scale*np.sqrt(2/np.pi)*np.exp(-ratio*ratio/2) + delta*(2*ndtr(ratio)-1)
                e_root = np.sqrt(scale)*2**0.25*gamma(0.75)/np.sqrt(np.pi)*hyp1f1(-0.25,0.5,-ratio*ratio/2)
                v = max(0.0, e_abs - e_root**2)
            joint += 2*v  # The official variogram sums ordered pairs.
    result = {"marginal": float(marginal), "joint": float(joint), "tail": float(tail)}
    if not all(np.isfinite(x) and x >= 0 for x in result.values()):
        raise ValueError("Invalid M0 expected-error divisor")
    return {name: value if value != 0 else 1.0 for name, value in result.items()}
