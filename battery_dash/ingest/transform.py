"""Cycle metrics, smoothing and incremental capacity analysis (Pandas + SciPy)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.integrate import cumulative_trapezoid, trapezoid
from scipy.signal import savgol_filter

from .. import config
from ..models import RawStep, RawTest


# ---------------------------------------------------------------- helpers
def savgol_safe(y, window: int = 11, poly: int = 2) -> np.ndarray:
    """Savitzky-Golay filter that tolerates short arrays and NaNs."""
    y = np.asarray(y, dtype=float)
    n = y.size
    if n < poly + 3:
        return y.copy()
    if np.isnan(y).any():
        s = pd.Series(y).interpolate(limit_direction="both")
        if s.isna().all():
            return y.copy()
        y = s.to_numpy()
    w = min(window, n if n % 2 else n - 1)
    if w <= poly:
        return y.copy()
    return savgol_filter(y, w, poly)


def downsample_index(n: int, max_points: int) -> np.ndarray:
    """Evenly spaced indices that always keep the first and last sample."""
    if n <= max_points:
        return np.arange(n)
    return np.unique(np.linspace(0, n - 1, max_points).round().astype(int))


def _nan_stat(fn, arr) -> float:
    arr = np.asarray(arr, dtype=float)
    return float(fn(arr)) if np.isfinite(arr).any() else float("nan")


# ---------------------------------------------------------------- per step
def step_metrics(step: RawStep) -> dict:
    """Integrate current and power over time to get Ah and Wh for one step."""
    t, v, i = step.t_s, step.voltage, step.current
    ah = float(trapezoid(np.abs(i), t) / 3600.0)
    wh = float(trapezoid(np.abs(v * i), t) / 3600.0)
    return {
        "ah": ah,
        "wh": wh,
        "duration_s": float(t[-1] - t[0]),
        "min_v": _nan_stat(np.nanmin, v),
        "max_v": _nan_stat(np.nanmax, v),
        "mean_temp_c": _nan_stat(np.nanmean, step.temperature),
        "max_temp_c": _nan_stat(np.nanmax, step.temperature),
    }


def assign_cycle_indices(steps: list[RawStep]) -> list[int]:
    """A cycle is a discharge plus the charge(s) right before it.

    Charges that are not followed by a discharge (a running test that is
    mid-charge) get the next index so the time series is still stored.
    """
    indices, idx = [], 0
    for s in steps:
        indices.append(idx + 1)
        if s.step == "discharge":
            idx += 1
    return indices


# ---------------------------------------------------------------- per cycle
def build_cycles(raw: RawTest) -> pd.DataFrame:
    """One row per completed cycle with capacity, efficiency and QC flag."""
    rows: list[dict] = []
    pending_charge: tuple[RawStep, dict] | None = None
    idx = 0
    lo, hi = config.CE_VALID_RANGE

    for step in raw.steps:
        if step.step == "charge":
            pending_charge = (step, step_metrics(step))
            continue

        idx += 1
        m = step_metrics(step)
        cap = step.reported_capacity_ah
        discharge_ah = cap if cap and np.isfinite(cap) and cap > 0 else m["ah"]

        charge_ah = charge_wh = float("nan")
        start = step.start_time
        if pending_charge is not None:
            charge_ah = pending_charge[1]["ah"]
            charge_wh = pending_charge[1]["wh"]
            start = pending_charge[0].start_time

        ce = discharge_ah / charge_ah if charge_ah and charge_ah > 0 else float("nan")
        ee = m["wh"] / charge_wh if charge_wh and charge_wh > 0 else float("nan")

        if np.isnan(charge_ah):
            qc = "no_charge"
        elif not (lo <= ce <= hi):
            qc = "ce_out_of_range"
            ce = ee = float("nan")
        else:
            qc = "ok"

        rows.append(
            {
                "test_id": raw.test_id,
                "cycle_index": idx,
                "start_time": start.isoformat(timespec="seconds"),
                "charge_ah": charge_ah,
                "discharge_ah": discharge_ah,
                "charge_wh": charge_wh,
                "discharge_wh": m["wh"],
                "coulombic_eff": ce,
                "energy_eff": ee,
                "discharge_duration_s": m["duration_s"],
                "min_v": m["min_v"],
                "max_v": m["max_v"],
                "mean_temp_c": m["mean_temp_c"],
                "max_temp_c": m["max_temp_c"],
                "qc_flag": qc,
            }
        )
        pending_charge = None

    df = pd.DataFrame(rows)
    return add_trends(df) if not df.empty else df


def add_trends(df: pd.DataFrame) -> pd.DataFrame:
    """State of health relative to the first cycles, plus smoothed fade curves."""
    df = df.sort_values("cycle_index").reset_index(drop=True)
    reference = float(df["discharge_ah"].head(3).median())
    df["discharge_ah_smooth"] = savgol_safe(df["discharge_ah"].to_numpy(), 21, 2)
    df["soh_pct"] = 100.0 * df["discharge_ah"] / reference
    df["soh_smooth_pct"] = 100.0 * df["discharge_ah_smooth"] / reference
    return df


def cycles_to_eol(df: pd.DataFrame, threshold: float = config.EOL_SOH_PCT) -> int | None:
    """First cycle where smoothed state of health drops below the threshold."""
    below = df.loc[df["soh_smooth_pct"] < threshold, "cycle_index"]
    return int(below.iloc[0]) if not below.empty else None


# ---------------------------------------------------------------- time series
def build_timeseries(raw: RawTest, max_points: int = config.MAX_POINTS_PER_STEP) -> pd.DataFrame:
    """Downsampled V/I/T curves per step with smoothed voltage and running Ah."""
    frames = []
    for cycle_index, step in zip(assign_cycle_indices(raw.steps), raw.steps):
        t, v, i = step.t_s, step.voltage, step.current
        n = t.size
        q = cumulative_trapezoid(np.abs(i), t, initial=0.0) / 3600.0
        window = int(np.clip(n // 40 * 2 + 1, 5, 51))
        v_smooth = savgol_safe(v, window, 2)
        keep = downsample_index(n, max_points)
        frames.append(
            pd.DataFrame(
                {
                    "test_id": raw.test_id,
                    "cycle_index": cycle_index,
                    "step": step.step,
                    "seq": np.arange(keep.size),
                    "t_s": t[keep],
                    "voltage_v": v[keep],
                    "voltage_smooth_v": v_smooth[keep],
                    "current_a": i[keep],
                    "temp_c": step.temperature[keep],
                    "capacity_ah": q[keep],
                }
            )
        )
    if not frames:
        return pd.DataFrame()
    ts = pd.concat(frames, ignore_index=True)
    # A charge recorded twice for the same cycle would collide on the key; keep the last.
    ts = ts.drop_duplicates(["test_id", "cycle_index", "step", "seq"], keep="last")
    return ts


# ---------------------------------------------------------------- dQ/dV
def incremental_capacity(q, v, n_grid: int = 200) -> tuple[np.ndarray, np.ndarray]:
    """dQ/dV curve from a capacity-voltage trace.

    Voltage is resampled onto a uniform grid so the derivative is not
    dominated by sampling noise, then both stages are Savitzky-Golay smoothed.
    """
    q = np.asarray(q, dtype=float)
    v = np.asarray(v, dtype=float)
    ok = np.isfinite(q) & np.isfinite(v)
    q, v = q[ok], v[ok]
    if q.size < 10:
        return np.array([]), np.array([])

    order = np.argsort(v)
    v, q = v[order], q[order]
    v_unique, first = np.unique(v, return_index=True)
    q = q[first]
    if v_unique.size < 10 or np.ptp(v_unique) <= 0:
        return np.array([]), np.array([])

    grid = np.linspace(v_unique[0], v_unique[-1], n_grid)
    q_grid = savgol_safe(np.interp(grid, v_unique, q), 15, 3)
    dqdv = np.abs(np.gradient(q_grid, grid))
    return grid, savgol_safe(dqdv, 11, 2)
