"""Stage 3 data layer — real CAMELS-compatible daily forcing + streamflow.

Three adapters, one schema:  date, P (mm/d), T (degC), PET (mm/d), SNOW (mm/d), Q (mm/d)

1. usgs_mini  — REAL observations, no login: USGS NWIS daily discharge (00060) for gauges
                with long records + ERA5-Land reanalysis forcing from Open-Meteo archive.
                Basin-average forcing approximated by the gauge pixel (documented bias).
2. camels_local — read official CAMELS / CARAVAN files the user already has (txt/csv),
                PET computed by Hargreaves if absent. This is the production path.
3. synthetic  — documented generator with a *known* injected regime shift, used to
                calibrate the anomaly detector (we can check recovery against truth).

All downloads are cached under data/cache and hashed into the run manifest.
"""
from __future__ import annotations

import io
import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "discovery_loop" / "data" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)
UA = "HydroDiscoveryLoop/0.1 (research prototype; mailto:research@example.org)"
CFS_TO_MMD = 0.0283168 / 2589988.11 * 86400.0 * 1000.0  # per unit area (mi2)


def _get(url: str, timeout: int = 90, retries: int = 3) -> bytes:
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"fetch failed {url}: {last}")


def _rdb_to_df(raw: bytes) -> pd.DataFrame:
    lines = [l for l in raw.decode("utf-8", "ignore").splitlines() if l and not l.startswith("#")]
    if len(lines) < 3:
        return pd.DataFrame()
    header = lines[0].split("\t")
    rows = [l.split("\t") for l in lines[2:]]
    return pd.DataFrame(rows, columns=header)


def list_gauges(state: str, min_area: float = 80, max_area: float = 2500) -> pd.DataFrame:
    url = (
        "https://waterservices.usgs.gov/nwis/site/?format=rdb&stateCd=" + state +
        "&parameterCd=00060&siteType=ST&siteStatus=active&siteOutput=expanded"
    )
    df = _rdb_to_df(_get(url))
    if df.empty:
        return df
    df = df.rename(columns={"site_no": "site", "dec_lat_va": "lat", "dec_long_va": "lon",
                            "drain_area_va": "area_mi2", "station_nm": "name"})
    for c in ("lat", "lon", "area_mi2"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["lat", "lon", "area_mi2"])
    return df[(df.area_mi2 >= min_area) & (df.area_mi2 <= max_area)]


def fetch_discharge(sites: list[str], start: str, end: str) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    for i in range(0, len(sites), 8):
        batch = sites[i : i + 8]
        key = f"{'-'.join(batch)}_{start}_{end}".replace(":", "")
        cp = _cache("discharge") / (str(abs(hash(key)) % (10**12)) + ".json")
        if cp.exists():
            payload = json.loads(cp.read_text(encoding="utf-8"))
        else:
            url = ("https://waterservices.usgs.gov/nwis/dv/?format=json&sites=" + ",".join(batch) +
                   f"&parameterCd=00060&statCd=00003&startDT={start}&endDT={end}")
            try:
                payload = json.loads(_get(url))
                cp.write_text(json.dumps(payload), encoding="utf-8")
            except Exception:
                continue
        for ts in payload.get("value", {}).get("timeSeries", []):
            site = ts["sourceInfo"]["siteCode"][0]["value"]
            vals = (ts.get("values") or [{}])[0].get("value") or []
            if not vals:
                continue
            idx, v = [], []
            for rec in vals:
                try:
                    q = float(rec["value"])
                except (TypeError, ValueError):
                    q = np.nan
                idx.append(pd.Timestamp(rec["dateTime"][:10]))
                v.append(q if q > -1e5 else np.nan)
            out[site] = pd.Series(v, index=pd.DatetimeIndex(idx)).sort_index()
    return out


def _cache(name: str) -> Path:
    p = CACHE / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def fetch_forcing_one(site: str, lat: float, lon: float, start: str, end: str) -> pd.DataFrame | None:
    """One basin at a time, cached to disk. NASA POWER first, Open-Meteo as fallback.

    POWER gives PRECTOTCORR / PRECSNO / T2M / T2M_MAX / T2M_MIN at daily step, no key,
    and stays responsive when the Open-Meteo shared quota is exhausted. PET is computed
    with Hargreaves from T2M and the diurnal range (same formula as the CAMELS adapter),
    so the field is internally consistent across sources.
    """
    cp = _cache("forcing") / f"{site}.csv"
    if cp.exists() and cp.stat().st_size > 5000:
        df = pd.read_csv(cp, parse_dates=[0], index_col=0)
        df.index.name = "date"
        return df

    # ---- primary: NASA POWER ----
    p_url = ("https://power.larc.nasa.gov/api/temporal/daily/point?"
             "parameters=PRECTOTCORR,PRECSNO,T2M,T2M_MAX,T2M_MIN&community=AG"
             f"&longitude={lon:.4f}&latitude={lat:.4f}"
             f"&start={start.replace('-', '')}&end={end.replace('-', '')}&format=JSON")
    try:
        js = json.loads(_get(p_url, timeout=180, retries=3))
        prm = js["properties"]["parameter"]
        dates = pd.to_datetime(list(prm["T2M"].keys()), format="%Y%m%d")
        p = np.array(list(prm["PRECTOTCORR"].values()), float)
        snow = np.array(list(prm["PRECSNO"].values()), float)
        t = np.array(list(prm["T2M"].values()), float)
        tmax = np.array(list(prm["T2M_MAX"].values()), float)
        tmin = np.array(list(prm["T2M_MIN"].values()), float)
        bad = (p <= -900) | (t <= -900)
        p[bad], t[bad] = np.nan, np.nan
        snow[(snow <= -900)] = 0.0
        df = pd.DataFrame({"P": p, "T": t, "PET": hargreaves(t, tmax - tmin, lat),
                           "SNOW": np.minimum(snow, p)}, index=dates)
        df = df.interpolate(limit=5).dropna()
        if len(df) > 365 * 5:
            df.to_csv(cp, index_label="date", float_format="%.4f")
            return df
    except Exception:
        pass

    # ---- fallback: Open-Meteo ERA5-Land ----
    params = {
        "latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}",
        "start_date": start, "end_date": end,
        "daily": "precipitation_sum,temperature_2m_mean,et0_fao_evapotranspiration,snowfall_water_equivalent_sum",
        "timezone": "GMT",
    }
    url = "https://archive-api.open-meteo.com/v1/archive?" + urllib.parse.urlencode(params)
    try:
        data = json.loads(_get(url, timeout=120, retries=1))
        d = data["daily"]
        df = pd.DataFrame({"date": pd.to_datetime(d["time"]), "P": d["precipitation_sum"],
                           "T": d["temperature_2m_mean"], "PET": d["et0_fao_evapotranspiration"],
                           "SNOW": d.get("snowfall_water_equivalent_sum", [0.0] * len(d["time"]))})
        df = df.set_index("date").astype(float)
        df.to_csv(cp, float_format="%.4f")
        return df
    except Exception:
        return None


def fetch_forcing(latlon: list[tuple[str, float, float]], start: str, end: str) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for site, lat, lon in latlon:
        df = fetch_forcing_one(site, lat, lon, start, end)
        if df is not None and len(df) > 365 * 5:
            out[site] = df
        time.sleep(0.8)
    return out


def fetch_usgs_mini(
    states: tuple[str, ...] = ("ME", "NC", "CO", "WA"),
    per_state: int = 8,
    start: str = "1990-01-01",
    end: str = "2022-12-31",
    min_coverage: float = 0.85,
) -> tuple[dict[str, pd.DataFrame], dict]:
    """Assemble a real, CAMELS-style dataset for tens of real USGS gauges."""
    meta: dict = {"source": "USGS NWIS dv 00060 (mean daily cfs) + ERA5-Land via Open-Meteo",
                  "period": [start, end], "states": list(states), "basins": {}, "urls": []}
    frames: dict[str, pd.DataFrame] = {}
    for st in states:
        try:
            g = list_gauges(st).sort_values("area_mi2", ascending=False).head(12)
        except Exception as e:
            meta["basins"][st] = {"error": str(e)}
            continue
        if g.empty:
            continue
        sites = g.site.tolist()
        q = fetch_discharge(sites, start, end)
        keep = []
        for site in sites:
            if site not in q:
                continue
            s = q[site]
            if len(s) < 365 * 10:
                continue
            cov = s.notna().mean()
            if cov >= min_coverage:
                keep.append((site, cov, len(s)))
            if len(keep) >= per_state:
                break
        if not keep:
            continue
        coords = [(r.site, float(r.lat), float(r.lon)) for r in g.itertuples() if r.site in dict((k[0], 1) for k in keep)]
        f = fetch_forcing(coords, start, end)
        for site, cov, n in keep:
            if site not in f or site not in q:
                continue
            area = float(g.loc[g.site == site, "area_mi2"].iloc[0])
            df = f[site].copy()
            df["Q"] = (q[site] * CFS_TO_MMD / area).reindex(df.index)
            df = df.dropna(subset=["Q"])
            if len(df) < 365 * 10:
                continue
            frames[f"usgs-{site}"] = df
            meta["basins"][f"usgs-{site}"] = {
                "state": st, "area_mi2": round(area, 1),
                "lat": round(float(g.loc[g.site == site, "lat"].iloc[0]), 4),
                "lon": round(float(g.loc[g.site == site, "lon"].iloc[0]), 4),
                "days": int(len(df)), "coverage": round(float(cov), 3),
                "name": str(g.loc[g.site == site, "name"].iloc[0])[:70],
            }
        meta["urls"].append(f"https://waterservices.usgs.gov/nwis/dv/?sites={len(sites)}_sites&state={st}")
    return frames, meta


def load_camels_local(path: str | Path) -> tuple[dict[str, pd.DataFrame], dict]:
    """Read official CAMELS/CARAVAN files (csv or whitespace txt) with flexible headers."""
    p = Path(path).expanduser()
    files = sorted(p.glob("*.csv")) + sorted(p.glob("*.txt")) if p.is_dir() else [p]
    frames, meta = {}, {"source": f"local CAMELS/CARAVAN: {p}", "basins": {}}
    alias = {
        "date": ["date", "day", "time", "Date"],
        "P": ["precip", "prcp", "precipitation", "p"],
        "T": ["tmean", "temp", "temperature", "tavg"],
        "Tmax": ["tmax"], "Tmin": ["tmin"],
        "PET": ["pet", "et0", "pot_evap"],
        "Q": ["streamflow", "flow", "q", "discharge", "runoff"],
        "SNOW": ["snow", "swe", "snowfall"],
    }
    for f in files:
        try:
            df = pd.read_csv(f, sep=None, engine="python")
        except Exception:
            continue
        cols = {c.lower(): c for c in df.columns}
        pick = {}
        for key, names in alias.items():
            for n in names:
                if n in cols:
                    pick[key] = cols[n]
                    break
        if not {"date", "P", "Q"} <= pick.keys():
            continue
        out = pd.DataFrame({"date": pd.to_datetime(df[pick["date"]], errors="coerce")})
        out["P"] = pd.to_numeric(df[pick["P"]], errors="coerce")
        out["Q"] = pd.to_numeric(df[pick["Q"]], errors="coerce")
        if "T" in pick:
            out["T"] = pd.to_numeric(df[pick["T"]], errors="coerce")
        elif {"Tmax", "Tmin"} <= pick.keys():
            out["T"] = (pd.to_numeric(df[pick["Tmax"]], errors="coerce") +
                        pd.to_numeric(df[pick["Tmin"]], errors="coerce")) / 2
        else:
            out["T"] = np.nan
        if "PET" in pick:
            out["PET"] = pd.to_numeric(df[pick["PET"]], errors="coerce")
        else:
            lat = 45.0
            out["PET"] = hargreaves(out["T"].values, out["T"].values, lat)
        out["SNOW"] = pd.to_numeric(df[pick["SNOW"]], errors="coerce") if "SNOW" in pick else 0.0
        out = out.dropna(subset=["date"]).set_index("date").sort_index()
        if len(out) < 365 * 5:
            continue
        name = f.name.replace(".csv", "").replace(".txt", "")[:24]
        frames[name] = out
        meta["basins"][name] = {"file": str(f), "days": int(len(out))}
    return frames, meta


def hargreaves(tmean: np.ndarray, trange: np.ndarray, lat: float) -> np.ndarray:
    doy = np.arange(len(tmean)) % 365 + 1
    lat_r = math.radians(lat)
    decl = 0.409 * np.sin(2 * math.pi * doy / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(lat_r) * np.tan(decl), -1, 1))
    ra = (24 * 60 / math.pi) * 0.082 * (ws * np.sin(lat_r) * np.sin(decl) +
                                       np.cos(lat_r) * np.cos(decl) * np.sin(ws))
    ra_mm = np.maximum(ra, 0) * 0.408
    return np.maximum(0.0023 * (np.asarray(tmean) + 17.8) * np.sqrt(np.maximum(np.asarray(trange), 0.5)) * ra_mm, 0)


def synthetic(n_basins: int = 6, years: int = 30, seed: int = 7, shift_basins: int = 2) -> tuple[dict, dict]:
    """Documented generator with a KNOWN regime shift (for detector calibration only)."""
    rng = np.random.default_rng(seed)
    frames, meta = {}, {"source": "synthetic (calibration only)", "basins": {}, "truth": {}}
    n = years * 365
    t = np.arange(n)
    doy = t % 365
    for b in range(n_basins):
        aridity = rng.uniform(0.4, 1.2)
        snowiness = rng.uniform(0.0, 0.8)
        phase = rng.uniform(0, 2 * np.pi)
        P = np.maximum(0, rng.gamma(1.6, 2.2, n) * (1 + 0.5 * np.sin(2 * np.pi * doy / 365 + phase)))
        T = 9 + 12 * np.sin(2 * np.pi * (doy - 105) / 365) + rng.normal(0, 2.5, n)
        PET = np.maximum(0, 1.6 * (T + 5) * (0.6 + 0.4 * np.sin(2 * np.pi * (doy - 100) / 365)))
        snow = np.where(T < 0, P * snowiness, 0.0)
        rain = P - snow
        melt = np.where(T > 0, snowiness * P * 0.25 * np.clip(T / 8, 0, 1), 0)
        wet = pd.Series(rain + melt).ewm(alpha=0.06).mean().values
        elasticity = 1.9 if b >= n_basins - shift_basins else 1.3
        late = t > n * 0.55
        gain = np.where(late, elasticity / 1.3, 1.0) if b >= n_basins - shift_basins else 1.0
        Q = 0.02 + 0.42 * wet ** (1.1 * gain) / (1 + aridity * PET.mean() / 3)
        Q = np.maximum(Q * (1 + rng.normal(0, 0.08, n)), 1e-4)
        dates = pd.date_range("1990-01-01", periods=n, freq="D")
        frames[f"syn-{b}"] = pd.DataFrame(
            {"P": P, "T": T, "PET": PET, "SNOW": snow, "Q": Q}, index=dates)
        meta["basins"][f"syn-{b}"] = {"aridity": round(aridity, 2), "snowiness": round(snowiness, 2)}
        if b >= n_basins - shift_basins:
            meta["truth"][f"syn-{b}"] = {"regime_shift_at": "55% of record", "elasticity_after": elasticity}
    return frames, meta


def save(frames: dict[str, pd.DataFrame], meta: dict, out_dir: str | Path) -> tuple[Path, str]:
    import hashlib

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("*.csv"):   # a rebuild must not inherit basins from a previous selection
        stale.unlink()
    h = hashlib.sha256()
    for name, df in frames.items():
        p = out / f"{name}.csv"
        df.to_csv(p, index_label="date", float_format="%.4f")
        h.update(p.read_bytes())
    (out / "manifest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return out, h.hexdigest()


def load(data_dir: str | Path) -> tuple[dict[str, pd.DataFrame], dict]:
    d = Path(data_dir)
    meta = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    frames = {}
    for f in sorted(d.glob("*.csv")):
        df = pd.read_csv(f, parse_dates=[0], index_col=0)
        df.index.name = "date"
        frames[f.stem] = df
    return frames, meta
