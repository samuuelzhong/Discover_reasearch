"""Stage 4 — Analysis: hydrological signatures, regime-shift tests, anomaly channel.

Branch 2 (interpretable discovery) needs statistics, not vibes:
  * signatures per basin (runoff ratio, P-Q elasticity, flow centroid, snow fraction,
    aridity, flashiness);
  * trend tests: Theil-Sen slope + Mann-Kendall p, with bootstrap CI on the slope;
  * regime shift: elasticity in the early vs late half of the record, with a bootstrap
    CI on the difference;
  * anomaly channel: cross-basin robust z (median/MAD) on the *change* metrics. Basins
    that move differently from their peers become questions, not conclusions — they
    bypass the hypothesis pool and re-enter stage 1 as observations.

The channel is calibratable: `calibrate()` runs the same detector on synthetic data
whose injected shifts are known, so we can report recall / false-positive rate.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


def _annual(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["year"] = d.index.year
    # keep only water years with >= 300 days of both P and Q
    g = d.groupby("year")
    tab = pd.DataFrame({
        "P": g["P"].sum(min_count=300),
        "Q": g["Q"].sum(min_count=300),
        "PET": g["PET"].sum(min_count=300),
        "SNOW": g["SNOW"].sum(min_count=300) if "SNOW" in d else 0.0,
        "n": g["Q"].count(),
    })
    return tab[tab["n"] >= 300]


def _flow_centroid(df: pd.DataFrame) -> float:
    q = np.maximum(df["Q"].to_numpy(float), 0)
    if q.sum() <= 0:
        return float("nan")
    ang = 2 * np.pi * (df.index.dayofyear.to_numpy(float) - 1) / 365.25
    s, c = np.sum(q * np.sin(ang)), np.sum(q * np.cos(ang))
    return float(((math.atan2(s, c) % (2 * np.pi)) * 365.25 / (2 * np.pi)) + 1)


def _theil_sen(x: np.ndarray, y: np.ndarray) -> float:
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 8:
        return float("nan")
    return float(stats.theilslopes(y[m], x[m]).slope)


def _mk(x: np.ndarray, y: np.ndarray) -> float:
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 8:
        return float("nan")
    return float(stats.kendalltau(x[m], y[m]).pvalue)


def _boot_ci(x: np.ndarray, y: np.ndarray, fn, n: int = 800, seed: int = 0) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    if len(x) < 10:
        return (float("nan"), float("nan"))
    vals = []
    for _ in range(n):
        idx = rng.integers(0, len(x), len(x))
        try:
            v = fn(x[idx], y[idx])
            if np.isfinite(v):
                vals.append(v)
        except Exception:
            continue
    if len(vals) < 30:
        return (float("nan"), float("nan"))
    return (float(np.percentile(vals, 5)), float(np.percentile(vals, 95)))


def _elasticity(x: np.ndarray, y: np.ndarray) -> float:
    """Slope of log Q on log P (only positive values)."""
    m = np.isfinite(x) & np.isfinite(y) & (x > 0) & (y > 0)
    if m.sum() < 8:
        return float("nan")
    return float(np.polyfit(np.log(x[m]), np.log(y[m]), 1)[0])


def signature_table(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for name, df in frames.items():
        a = _annual(df)
        if len(a) < 12:
            continue
        years = a.index.to_numpy(float)
        P, Q = a["P"].to_numpy(float), a["Q"].to_numpy(float)
        half = len(a) // 2
        x1, y1 = years[:half], Q[:half]
        p1, q1 = P[:half], Q[:half]
        p2, q2 = P[half:], Q[half:]
        e_all = _elasticity(P, Q)
        e_early = _elasticity(p1, q1)
        e_late = _elasticity(p2, q2)
        rr = Q / np.maximum(P, 1e-6)
        row = {
            "basin": name,
            "years": int(len(a)),
            "runoff_ratio": float(np.nanmean(rr)),
            "elasticity": e_all,
            "elasticity_early": e_early,
            "elasticity_late": e_late,
            "delta_elasticity": (e_late - e_early) if np.isfinite(e_early) and np.isfinite(e_late) else np.nan,
            "snow_fraction": float(np.nansum(a["SNOW"].to_numpy(float)) / max(np.nansum(P), 1e-6)),
            "aridity": float(np.nansum(a["PET"].to_numpy(float)) / max(np.nansum(P), 1e-6)),
            "flow_centroid_doy": _flow_centroid(df),
            "q95_q50": float(np.nanpercentile(df["Q"], 95) / max(np.nanpercentile(df["Q"], 50), 1e-6)),
            "rr_trend": _theil_sen(years, rr),
            "rr_trend_p": _mk(years, rr),
            "centroid_trend": _theil_sen(years, np.array(
                [ _flow_centroid(df[df.index.year == y]) for y in a.index ], dtype=float)),
        }
        lo, hi = _boot_ci(years, rr, _theil_sen)
        row["rr_trend_ci"] = [round(lo, 5), round(hi, 5)]
        # bootstrap CI on delta elasticity via resampling years
        rng = np.random.default_rng(3)
        deltas = []
        for _ in range(300):
            idx = np.sort(rng.integers(0, len(a), len(a)))
            h = len(idx) // 2
            ee = _elasticity(P[idx][:h], Q[idx][:h])
            el = _elasticity(P[idx][h:], Q[idx][h:])
            if np.isfinite(ee) and np.isfinite(el):
                deltas.append(el - ee)
        row["delta_elast_ci"] = [round(float(np.percentile(deltas, 5)), 3),
                                 round(float(np.percentile(deltas, 95)), 3)] if len(deltas) > 30 else [np.nan, np.nan]
        row["regime"] = ("snow" if row["snow_fraction"] > 0.15 else
                         ("rain" if row["aridity"] < 0.9 else "dry"))
        # two orthogonal, documented classifications (regime above collapsed non-snow
        # humid basins into a single group, which left n=1 — fixed here)
        row["snow_class"] = "snow" if row["snow_fraction"] >= 0.15 else "non_snow"
        row["aridity_class"] = "arid" if row["aridity"] >= 1.0 else "humid"
        # derived, sign-normalized metrics so criteria can always be written as ">"
        row["centroid_advance"] = -row["centroid_trend"]      # positive = earlier centroid
        row["neg_delta_elast"] = -row["delta_elasticity"] if np.isfinite(row["delta_elasticity"]) else np.nan
        rows.append(row)
    return pd.DataFrame(rows).set_index("basin")


def _robust_z(v: np.ndarray) -> np.ndarray:
    med = np.nanmedian(v)
    mad = np.nanmedian(np.abs(v - med))
    scale = 1.4826 * mad if mad > 1e-9 else (np.nanstd(v) or 1.0)
    return (v - med) / scale


def anomaly_channel(table: pd.DataFrame, z_thresh: float = 2.5) -> list[dict]:
    """Turn cross-basin outliers in *change* metrics into questions."""
    out = []
    for metric, q in (("delta_elasticity", "弹性变化是否被某类流域的地下水/融雪补偿掩盖？"),
                      ("rr_trend", "径流比趋势异常是否来自观测序列的站点迁移或取用水变化？"),
                      ("centroid_trend", "季节性重心移动异常是否对应融雪期提前或水库调度？")):
        if metric not in table:
            continue
        v = table[metric].to_numpy(float)
        z = _robust_z(v)
        for basin, zi, val in zip(table.index, z, v):
            if np.isfinite(zi) and abs(zi) >= z_thresh:
                peers = table.loc[table["regime"] == table.loc[basin, "regime"], metric]
                out.append({
                    "basin": basin,
                    "metric": metric,
                    "value": round(float(val), 4),
                    "z": round(float(zi), 2),
                    "regime": table.loc[basin, "regime"],
                    "peer_median": round(float(np.nanmedian(peers)), 4) if len(peers) else None,
                    "aridity": round(float(table.loc[basin, "aridity"]), 3),
                    "snow_fraction": round(float(table.loc[basin, "snow_fraction"]), 3),
                    "question": (f"{basin}（{table.loc[basin,'regime']} 型）的 {metric}={val:.3f}，"
                                 f"同类流域中位数 {np.nanmedian(peers):.3f}（z={zi:+.1f}）。{q}"),
                })
    return sorted(out, key=lambda d: -abs(d["z"]))


def calibrate(frames: dict[str, pd.DataFrame], truth: dict, z_thresh: float = 2.0) -> dict:
    """Run the detector on data with known injected shifts and report recovery."""
    table = signature_table(frames)
    flags = anomaly_channel(table, z_thresh)
    flagged = {f["basin"] for f in flags}
    truth_set = set(truth)
    hit = flagged & truth_set
    return {
        "n_truth": len(truth_set),
        "n_flagged": len(flagged),
        "recall": round(len(hit) / max(len(truth_set), 1), 3),
        "precision": round(len(hit) / max(len(flagged), 1), 3),
        "flagged": sorted(flagged),
        "missed": sorted(truth_set - flagged),
    }


def hypothesis_test(table: pd.DataFrame, criterias: list[dict]) -> dict:
    """Evaluate branch-2 decision criteria against the signature table.

    Supported directions:
      >, <        fraction of basins above / below threshold  (needs min_frac)
      abs>        fraction with |value| above threshold
      median>     median of the metric vs threshold
      group>      median(group_a) - median(group_b) vs threshold (needs group_by/group_a/group_b)
      corr<       Pearson r between metric and metric_b vs threshold
    """
    results = []
    for c in criterias:
        metric, direction = c.get("metric"), c.get("direction")
        thr = float(c.get("threshold"))
        mf = c.get("min_frac", 0.5)
        if metric not in table:
            results.append({**c, "value": None, "verdict": "no_data"})
            continue
        v = table[metric].to_numpy(float)
        ok = np.isfinite(v)
        if direction in (">", "<"):
            frac = float(np.mean(v[ok] > thr) if direction == ">" else np.mean(v[ok] < thr))
            results.append({**c, "value": round(frac, 3), "n": int(ok.sum()),
                            "verdict": "supports" if frac >= mf else
                                       ("weakens" if frac <= 1 - mf else "inconclusive")})
        elif direction == "abs>":
            frac = float(np.mean(np.abs(v[ok]) > thr))
            results.append({**c, "value": round(frac, 3), "n": int(ok.sum()),
                            "verdict": "supports" if frac >= mf else "inconclusive"})
        elif direction == "median>":
            med = float(np.nanmedian(v[ok]))
            results.append({**c, "value": round(med, 3), "n": int(ok.sum()),
                            "verdict": "supports" if med > thr else "weakens"})
        elif direction == "group>":
            gb, ga, gb2 = c.get("group_by", "regime"), c.get("group_a"), c.get("group_b")
            a = table.loc[table[gb] == ga, metric].to_numpy(float)
            b = table.loc[table[gb] == gb2, metric].to_numpy(float)
            a, b = a[np.isfinite(a)], b[np.isfinite(b)]
            if len(a) < 3 or len(b) < 3:
                results.append({**c, "value": None, "verdict": "no_data",
                                "n_a": int(len(a)), "n_b": int(len(b))})
                continue
            diff = float(np.nanmedian(a) - np.nanmedian(b))
            results.append({**c, "value": round(diff, 3), "n_a": int(len(a)), "n_b": int(len(b)),
                            "median_a": round(float(np.nanmedian(a)), 3),
                            "median_b": round(float(np.nanmedian(b)), 3),
                            "verdict": "supports" if diff > thr else "weakens"})
        elif direction == "corr<":
            mb = c.get("metric_b")
            if mb not in table:
                results.append({**c, "value": None, "verdict": "no_data"})
                continue
            x, y = table[metric].to_numpy(float), table[mb].to_numpy(float)
            ok2 = np.isfinite(x) & np.isfinite(y)
            if ok2.sum() < 6:
                results.append({**c, "value": None, "verdict": "no_data"})
                continue
            r = float(np.corrcoef(x[ok2], y[ok2])[0, 1])
            results.append({**c, "value": round(r, 3), "n": int(ok2.sum()),
                            "verdict": "supports" if r < thr else "weakens"})
        else:
            results.append({**c, "value": round(float(np.nanmedian(v[ok])), 4),
                            "n": int(ok.sum()), "verdict": "inconclusive"})
    return {"criteria": results,
            "overall": ("supports" if all(r["verdict"] == "supports" for r in results) else
                        ("weakens" if any(r["verdict"] == "weakens" for r in results) else "inconclusive"))}


def ablate(frames: dict, specs: list[list], alpha: float = 3.0) -> pd.DataFrame:
    """Evaluate several feature designs side by side, per basin (branch-1 ablation).

    Returns a basin x design table of val NSE — the raw material for differential
    hypotheses ("this feature only helps in snow-dominated basins").
    """
    from . import experiment as exp

    out = {}
    for i, spec in enumerate(specs):
        code = exp.render([tuple(s) for s in spec])
        res = exp.evaluate_code(code, frames, alpha=alpha, detail=True)
        if not res.get("ok"):
            continue
        name = f"spec{i}:" + "+".join(s[0] for s in spec)
        out[name] = {r["basin"]: r["nse_val"] for r in res["per_basin"]}
    return pd.DataFrame(out)


def judge_group_delta(df: pd.DataFrame, regimes: pd.Series, a: str, b: str,
                      group_a: str = "snow", group_b: str = "rain", min_delta: float = 0.0) -> dict:
    """Does design a beat design b more in group_a than in group_b? (differential test)"""
    if a not in df.columns or b not in df.columns:
        return {"verdict": "no_data", "available": list(df.columns)}
    delta = (df[a] - df[b]).dropna()
    idx = [i for i in delta.index if i in regimes.index]
    delta = delta.loc[idx]
    reg = regimes.loc[idx]
    da = delta[reg == group_a]
    db = delta[reg == group_b]
    if len(da) < 3 or len(db) < 3:
        return {"verdict": "no_data", "n_a": int(len(da)), "n_b": int(len(db))}
    ma, mb = float(np.nanmedian(da)), float(np.nanmedian(db))
    verdict = "supports" if (ma - mb) > min_delta and ma > 0 else (
        "weakens" if ma - mb <= min_delta else "inconclusive")
    return {"verdict": verdict, "median_delta_a": round(ma, 4), "median_delta_b": round(mb, 4),
            "diff": round(ma - mb, 4), "n_a": int(len(da)), "n_b": int(len(db)),
            "group_a": group_a, "group_b": group_b, "design_a": a, "design_b": b}


def save_report(run, table: pd.DataFrame, anomalies: list[dict], extra: dict | None = None) -> Path:
    out = run.dir / "analysis"
    table.round(4).to_csv(out / "signatures.csv", encoding="utf-8")
    (out / "anomalies.json").write_text(json.dumps(anomalies, ensure_ascii=False, indent=2), encoding="utf-8")
    for a in anomalies:
        # Idempotent: re-running `analyze` must not duplicate rows. promoted is preserved.
        run.db.execute(
            """INSERT INTO anomalies(basin,metric,value,z,baseline,question,created_at,promoted)
            VALUES(?,?,?,?,?,?,datetime('now'),0)
            ON CONFLICT(basin,metric) DO UPDATE SET
                value=excluded.value, z=excluded.z, baseline=excluded.baseline,
                question=excluded.question, created_at=excluded.created_at""",
            (a["basin"], a["metric"], a["value"], a["z"], json.dumps(
                {"peer_median": a["peer_median"], "regime": a["regime"]}, ensure_ascii=False), a["question"]),
        )
    run.db.commit()
    if extra:
        (out / "summary.json").write_text(json.dumps(extra, ensure_ascii=False, indent=2), encoding="utf-8")
    run.event("analysis", "signatures", {"n_basins": int(len(table)), "n_anomalies": len(anomalies)})
    return out
