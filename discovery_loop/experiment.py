"""Stage 3 — Experiment verifier: the judge of branch 1 (accuracy).

Everything here is deterministic and cheap: a candidate is a *feature design* (a small
Python module produced by the evolution engine), the engine fits a ridge model per basin
on the train period only, and scores NSE/KGE on val/test periods only.

Why this is a legitimate "experiment" and not a toy:
  - data are real USGS observations + reanalysis forcing (see data/hydro.py);
  - splits are temporal, coefficients and scalers are fit on train only;
  - the metric is the standard one used by the CAMELS literature (NSE, KGE);
  - every evaluation is hashed and archived, so any number is reproducible.

Candidate API (what the evolution engine edits):
    SPEC = [("p_ewm", 0.06), ("p_lag", 1), ("harm", 1)]
    -> rendered to a real .py file with build_features(ctx) returning (X, names)
Candidates never see Q; the engine owns y and the fit.
"""
from __future__ import annotations

import hashlib
import json
import textwrap
import time
from pathlib import Path

import numpy as np
import pandas as pd

COMPONENTS = {
    # name: (params_doc, default params)
    "p_lag": ({"k": [1, 2, 3, 5, 7]}, {"k": 1}),
    "p_roll": ({"w": [3, 7, 15, 30]}, {"w": 7}),
    "p_ewm": ({"alpha": [0.02, 0.05, 0.1, 0.2, 0.4]}, {"alpha": 0.1}),
    "pet_ewm": ({"alpha": [0.02, 0.05, 0.1, 0.2]}, {"alpha": 0.1}),
    "pet_roll": ({"w": [7, 30, 90]}, {"w": 30}),
    "t_ewm": ({"alpha": [0.05, 0.1, 0.2]}, {"alpha": 0.1}),
    "snow_ewm": ({"alpha": [0.02, 0.05, 0.1]}, {"alpha": 0.05}),
    "melt": ({"scale": [0.5, 1.0, 2.0]}, {"scale": 1.0}),
    "deficit": ({"alpha": [0.02, 0.05, 0.1]}, {"alpha": 0.05}),
    "harm": ({"k": [1, 2, 3]}, {"k": 1}),
    "p_over_pet": ({}, {}),
    "log_p_ewm": ({"alpha": [0.05, 0.1]}, {"alpha": 0.1}),
}

SPEC_TEMPLATE = '''"""Candidate feature design (auto-generated, auditable)."""
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


SPEC = {spec!r}


def build_features(ctx):
    P, T, PET, SNOW, doy = ctx["P"], ctx["T"], ctx["PET"], ctx["SNOW"], ctx["doy"]
    P = np.maximum(P, 0.0)
    PET = np.maximum(PET, 0.0)
    cols, names = [], []

    def add(v, name):
        cols.append(np.asarray(v, dtype=float))
        names.append(name)

{body}

    X = np.column_stack(cols) if cols else np.zeros((len(P), 0))
    return X, names
'''

BODY = {
    "p_lag": "    add(_lag(P, {k}), 'p_lag{k}')",
    "p_roll": "    add(_roll(P, {w}), 'p_roll{w}')",
    "p_ewm": "    add(_ewm(P, {alpha}), 'p_ewm{alpha}')",
    "pet_ewm": "    add(_ewm(PET, {alpha}), 'pet_ewm{alpha}')",
    "pet_roll": "    add(_roll(PET, {w}), 'pet_roll{w}')",
    "t_ewm": "    add(_ewm(T, {alpha}), 't_ewm{alpha}')",
    "snow_ewm": "    add(_ewm(SNOW, {alpha}), 'snow_ewm{alpha}')",
    "melt": "    add(_ewm(np.where(T > 0, SNOW * np.clip(T / 8.0, 0, 1) * {scale}, 0.0), 0.2), 'melt{scale}')",
    "deficit": "    add(_ewm(P - PET, {alpha}), 'deficit{alpha}')",
    "harm": "    add(np.sin(2 * np.pi * doy / 365.25 * {k}), 'sin{k}')\n    add(np.cos(2 * np.pi * doy / 365.25 * {k}), 'cos{k}')",
    "p_over_pet": "    add(_ewm(P, 0.1) / np.maximum(_ewm(PET, 0.1), 0.1), 'p_over_pet')",
    "log_p_ewm": "    add(np.log1p(_ewm(P, {alpha})), 'log_p_ewm{alpha}')",
}


def render(spec: list[tuple[str, dict]]) -> str:
    lines = []
    for name, params in spec:
        lines.append(BODY[name].format(**params))
    return SPEC_TEMPLATE.format(spec=spec, body="\n".join(lines))


def compile_candidate(code: str) -> callable:
    ns: dict = {}
    exec(compile(code, "<candidate>", "exec"), ns)  # noqa: S102 - sandboxed by design of this prototype
    return ns["build_features"]


def splits(index: pd.DatetimeIndex, frac: tuple[float, float, float] = (0.6, 0.2, 0.2)) -> dict[str, np.ndarray]:
    n = len(index)
    a, b = int(n * frac[0]), int(n * (frac[0] + frac[1]))
    m = np.zeros(n, dtype=bool)
    out = {}
    for name, sl in (("train", slice(0, a)), ("val", slice(a, b)), ("test", slice(b, n))):
        mask = m.copy()
        mask[sl] = True
        out[name] = mask
    return out


def _ridge_fit(X: np.ndarray, y: np.ndarray, alpha: float = 1.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mu, sd = X.mean(0), X.std(0)
    sd[sd < 1e-8] = 1.0
    Xs = (X - mu) / sd
    Xs = np.column_stack([np.ones(len(Xs)), Xs])
    A = Xs.T @ Xs + alpha * np.eye(Xs.shape[1])
    A[0, 0] -= alpha * 0.999  # do not penalize intercept
    w = np.linalg.solve(A, Xs.T @ y)
    return w, mu, sd


def _ridge_predict(X: np.ndarray, w: np.ndarray, mu: np.ndarray, sd: np.ndarray) -> np.ndarray:
    Xs = (X - mu) / sd
    return np.column_stack([np.ones(len(Xs)), Xs]) @ w


def nse(obs: np.ndarray, sim: np.ndarray) -> float:
    m = np.isfinite(obs) & np.isfinite(sim)
    if m.sum() < 30:
        return float("nan")
    o, s = obs[m], sim[m]
    denom = np.sum((o - o.mean()) ** 2)
    return float(1 - np.sum((o - s) ** 2) / denom) if denom > 0 else float("nan")


def kge(obs: np.ndarray, sim: np.ndarray) -> float:
    m = np.isfinite(obs) & np.isfinite(sim)
    if m.sum() < 30:
        return float("nan")
    o, s = obs[m], sim[m]
    if o.std() < 1e-9 or s.std() < 1e-9 or o.mean() == 0:
        return float("nan")
    r = np.corrcoef(o, s)[0, 1]
    beta = s.mean() / o.mean()
    gamma = (s.std() / s.mean()) / (o.std() / o.mean())
    return float(1 - np.sqrt((r - 1) ** 2 + (beta - 1) ** 2 + (gamma - 1) ** 2))


def evaluate_code(
    code: str,
    frames: dict[str, pd.DataFrame],
    alpha: float = 3.0,
    metric_split: str = "val",
    basins: list[str] | None = None,
    detail: bool = False,
) -> dict:
    """Fit on train, score on val (selection) and test (report)."""
    t0 = time.time()
    build = compile_candidate(code)
    names = basins or list(frames)
    rows = []
    failures = []
    for name in names:
        df = frames[name]
        try:
            ctx = {
                "P": df["P"].to_numpy(float),
                "T": df["T"].to_numpy(float),
                "PET": df["PET"].to_numpy(float),
                "SNOW": df.get("SNOW", pd.Series(0.0, index=df.index)).to_numpy(float),
                "doy": df.index.dayofyear.to_numpy(float),
            }
            X, fnames = build(ctx)
            if X.size == 0 or not np.isfinite(X).all():
                raise ValueError("non-finite or empty feature matrix")
            y = np.log1p(np.maximum(df["Q"].to_numpy(float), 0.0))
            sp = splits(df.index)
            w, mu, sd = _ridge_fit(X[sp["train"]], y[sp["train"]], alpha)
            row = {"basin": name}
            for part in ("val", "test"):
                pred = np.expm1(_ridge_predict(X[sp[part]], w, mu, sd))
                obs = df["Q"].to_numpy(float)[sp[part]]
                row[f"nse_{part}"] = nse(obs, pred)
                row[f"kge_{part}"] = kge(obs, pred)
            row["n_features"] = X.shape[1]
            rows.append(row)
        except Exception as e:
            failures.append({"basin": name, "error": str(e)[:200]})
    if not rows:
        return {"ok": False, "error": "all basins failed", "failures": failures,
                "code_sha": hashlib.sha256(code.encode()).hexdigest()[:12]}
    tab = pd.DataFrame(rows)
    val = tab[f"nse_{metric_split}"].to_numpy(float)
    res = {
        "ok": True,
        "metric_split": metric_split,
        "score_median": float(np.nanmedian(val)),
        "score_mean": float(np.nanmean(val)),
        "test_median": float(np.nanmedian(tab["nse_test"])),
        "kge_test_median": float(np.nanmedian(tab["kge_test"])),
        "n_basins": int(len(tab)),
        "n_features": int(tab["n_features"].max()),
        "neg_basins": int(np.nansum(val < 0)),
        "seconds": round(time.time() - t0, 2),
        "code_sha": hashlib.sha256(code.encode()).hexdigest()[:12],
        "failures": failures,
    }
    if detail:
        res["per_basin"] = tab.round(4).to_dict(orient="records")
    return res


def archive(path: Path, code: str, result: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_suffix(".py").write_text(code, encoding="utf-8")
    path.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
