"""Candidate feature design (auto-generated, auditable)."""
import numpy as np


def _lag(x, k):
    out = np.empty_like(x, dtype=float)
    out[:k] = x[:k]
    out[k:] = x[:-k]
    return out


def _roll(x, w):
    return np.convolve(x, np.ones(w) / w, mode="same")


def _ewm(x, alpha):
    out = np.empty_like(x, dtype=float)
    acc = x[0]
    for i, v in enumerate(x):
        acc = alpha * v + (1 - alpha) * acc
        out[i] = acc
    return out


SPEC = [('p_lag', {'k': 1}), (np.str_('log_p_ewm'), {'alpha': 0.1}), ('t_ewm', {'alpha': 0.1}), ('harm', {'k': 2}), (np.str_('pet_roll'), {'w': 90}), (np.str_('deficit'), {'alpha': 0.05})]


def build_features(ctx):
    P, T, PET, SNOW, doy = ctx["P"], ctx["T"], ctx["PET"], ctx["SNOW"], ctx["doy"]
    P = np.maximum(P, 0.0)
    PET = np.maximum(PET, 0.0)
    cols, names = [], []

    def add(v, name):
        cols.append(np.asarray(v, dtype=float))
        names.append(name)

    add(_lag(P, 1), 'p_lag1')
    add(np.log1p(_ewm(P, 0.1)), 'log_p_ewm0.1')
    add(_ewm(T, 0.1), 't_ewm0.1')
    add(np.sin(2 * np.pi * doy / 365.25 * 2), 'sin2')
    add(np.cos(2 * np.pi * doy / 365.25 * 2), 'cos2')
    add(_roll(PET, 90), 'pet_roll90')
    add(_ewm(P - PET, 0.05), 'deficit0.05')

    X = np.column_stack(cols) if cols else np.zeros((len(P), 0))
    return X, names
