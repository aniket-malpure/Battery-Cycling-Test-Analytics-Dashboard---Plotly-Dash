"""Parser for the NASA PCoE battery aging dataset (.mat files such as B0005.mat).

Each file holds one struct named after the cell with a `cycle` array. Every
entry has a `type` (charge / discharge / impedance), an `ambient_temperature`,
a MATLAB date vector `time`, and a `data` struct with the measured signals.
Impedance entries are skipped.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from scipy.io import loadmat

from .. import config
from ..models import RawStep, RawTest


def _start_time(datevec) -> datetime:
    vec = np.atleast_1d(np.asarray(datevec, dtype=float))
    y, mo, d, h, mi = (int(x) for x in vec[:5])
    seconds = float(vec[5]) if vec.size > 5 else 0.0
    return datetime(y, mo, d, h, mi) + timedelta(seconds=seconds)


def _arr(value) -> np.ndarray:
    return np.atleast_1d(np.asarray(value, dtype=float))


def read_nasa_mat(path: str | Path) -> RawTest:
    path = Path(path)
    mat = loadmat(path, squeeze_me=True, struct_as_record=False)
    keys = [k for k in mat if not k.startswith("__")]
    if not keys:
        raise ValueError(f"{path.name}: no data struct found")
    root = mat[path.stem] if path.stem in mat else mat[keys[0]]

    steps: list[RawStep] = []
    ambient: list[float] = []
    for entry in np.atleast_1d(root.cycle):
        step = str(entry.type).strip().lower()
        if step not in ("charge", "discharge"):
            continue
        data = entry.data
        t = _arr(data.Time)
        if t.size < 3:  # a few NASA records are empty placeholders
            continue
        capacity = None
        if step == "discharge" and hasattr(data, "Capacity"):
            cap = _arr(data.Capacity)
            if cap.size and np.isfinite(cap[0]) and cap[0] > 0:
                capacity = float(cap[0])
        ambient.append(float(entry.ambient_temperature))
        steps.append(
            RawStep(
                step=step,
                start_time=_start_time(entry.time),
                t_s=t - t[0],
                voltage=_arr(data.Voltage_measured),
                current=_arr(data.Current_measured),
                temperature=_arr(data.Temperature_measured),
                reported_capacity_ah=capacity,
            )
        )

    if not steps:
        raise ValueError(f"{path.name}: no charge or discharge records")

    # Optional sidecar (B0005.meta.json) can override any metadata field.
    meta = {}
    sidecar = path.with_suffix(".meta.json")
    if sidecar.exists():
        meta = json.loads(sidecar.read_text())

    return RawTest(
        test_id=meta.get("test_id", f"NASA-{path.stem}"),
        cell_id=meta.get("cell_id", path.stem),
        test_name=meta.get("test_name", f"NASA aging test {path.stem}"),
        protocol=meta.get(
            "protocol", "CC 1.5A to 4.2V, CV to 20mA; CC 2A discharge to cutoff"
        ),
        ambient_temp_c=meta.get("ambient_temp_c", float(np.median(ambient))),
        status=meta.get("status", "complete"),
        source_file=str(path),
        chemistry=meta.get("chemistry", dict(config.NASA_CHEMISTRY)),
        cell=meta.get("cell", {"form_factor": "18650", "source": "NASA PCoE"}),
        materials=meta.get("materials", []),
        steps=steps,
    )
