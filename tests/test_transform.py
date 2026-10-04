from datetime import datetime, timedelta

import numpy as np

from battery_dash.ingest.transform import (
    assign_cycle_indices,
    build_cycles,
    cycles_to_eol,
    downsample_index,
    incremental_capacity,
    savgol_safe,
    step_metrics,
)
from battery_dash.models import RawStep, RawTest


def _step(kind, ah, start, n=100, v=(3.0, 4.0)):
    hours = 1.0
    t = np.linspace(0, hours * 3600, n)
    current = (ah / hours) * (1 if kind == "charge" else -1)
    return RawStep(kind, start, t, np.linspace(*v, n), np.full(n, current), np.full(n, 25.0))


def _test(pairs):
    steps, t0 = [], datetime(2026, 1, 1)
    for k, (c, d) in enumerate(pairs):
        steps.append(_step("charge", c, t0 + timedelta(hours=3 * k)))
        steps.append(_step("discharge", d, t0 + timedelta(hours=3 * k + 1.5)))
    return RawTest("T1", "C1", "t", "p", 25.0, "running", "x", {"name": "chem"}, steps=steps)


def test_step_metrics_integrates_constant_current():
    m = step_metrics(_step("discharge", 2.0, datetime(2026, 1, 1)))
    assert abs(m["ah"] - 2.0) < 1e-9
    assert abs(m["wh"] - 2.0 * 3.5) < 1e-6  # mean voltage 3.5 V
    assert m["min_v"] == 3.0 and m["max_v"] == 4.0


def test_build_cycles_pairs_charge_with_next_discharge():
    df = build_cycles(_test([(2.0, 1.98), (2.0, 1.96), (2.0, 1.94)]))
    assert list(df["cycle_index"]) == [1, 2, 3]
    assert np.allclose(df["coulombic_eff"], [0.99, 0.98, 0.97])
    assert (df["qc_flag"] == "ok").all()
    assert abs(df["soh_pct"].iloc[0] - 100 * 1.98 / 1.96) < 1e-9  # reference = median of first 3


def test_out_of_range_efficiency_is_flagged_not_plotted():
    df = build_cycles(_test([(1.0, 1.9)]))
    assert df["qc_flag"].iloc[0] == "ce_out_of_range"
    assert np.isnan(df["coulombic_eff"].iloc[0])


def test_trailing_charge_gets_next_cycle_index():
    raw = _test([(2.0, 1.9)])
    raw.steps.append(_step("charge", 2.0, datetime(2026, 1, 2)))
    assert assign_cycle_indices(raw.steps) == [1, 1, 2]


def test_savgol_safe_handles_short_and_nan_input():
    assert np.array_equal(savgol_safe([1.0, 2.0]), np.array([1.0, 2.0]))
    out = savgol_safe([1, np.nan, 3, 4, 5, 6, 7], 5, 2)
    assert np.isfinite(out).all()


def test_downsample_keeps_endpoints():
    idx = downsample_index(10_000, 250)
    assert idx[0] == 0 and idx[-1] == 9_999 and len(idx) <= 250


def test_cycles_to_eol():
    import pandas as pd

    df = pd.DataFrame({"cycle_index": [1, 2, 3, 4], "soh_smooth_pct": [100, 90, 79, 70]})
    assert cycles_to_eol(df, 80) == 3
    assert cycles_to_eol(df, 50) is None


def test_incremental_capacity_peaks_on_plateau():
    v = np.linspace(3.0, 4.0, 400)
    q = 1 / (1 + np.exp(-(v - 3.4) / 0.02))  # plateau centered at 3.4 V
    grid, dqdv = incremental_capacity(q, v)
    assert abs(grid[np.argmax(dqdv)] - 3.4) < 0.03
