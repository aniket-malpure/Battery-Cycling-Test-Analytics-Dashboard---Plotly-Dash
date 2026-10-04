"""Parser for generic battery cycler CSV exports.

Expected CSV columns (one row per sample):
    cycle_index, step_type, test_time_s, voltage_v, current_a[, temperature_c]

`step_type` is charge, discharge or rest (rest rows are ignored). A sidecar
file with the same stem and a `.meta.json` suffix carries test, cell,
chemistry and build-material metadata. See README for the full format.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ..models import RawStep, RawTest

REQUIRED_COLUMNS = {"cycle_index", "step_type", "test_time_s", "voltage_v", "current_a"}


def meta_path_for(csv_path: Path) -> Path:
    return csv_path.with_suffix(".meta.json")


def read_cycler_csv(path: str | Path) -> RawTest:
    path = Path(path)
    meta_file = meta_path_for(path)
    if not meta_file.exists():
        raise FileNotFoundError(f"{path.name}: missing sidecar {meta_file.name}")
    meta = json.loads(meta_file.read_text())

    df = pd.read_csv(path)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"{path.name}: missing columns {sorted(missing)}")
    if "temperature_c" not in df.columns:
        df["temperature_c"] = np.nan

    df["step_type"] = df["step_type"].astype(str).str.strip().str.lower()
    df = df[df["step_type"].isin(["charge", "discharge"])]
    df = df.dropna(subset=["test_time_s", "voltage_v", "current_a"])

    test_start = datetime.fromisoformat(meta["start_time"])
    steps: list[RawStep] = []
    for (_, step), g in df.groupby(["cycle_index", "step_type"], sort=False):
        g = g.sort_values("test_time_s")
        if len(g) < 3:
            continue
        t = g["test_time_s"].to_numpy(float)
        steps.append(
            RawStep(
                step=step,
                start_time=test_start + timedelta(seconds=float(t[0])),
                t_s=t - t[0],
                voltage=g["voltage_v"].to_numpy(float),
                current=g["current_a"].to_numpy(float),
                temperature=g["temperature_c"].to_numpy(float),
            )
        )
    # Chronological order guarantees each charge precedes its discharge.
    steps.sort(key=lambda s: s.start_time)

    if not steps:
        raise ValueError(f"{path.name}: no charge or discharge rows")

    return RawTest(
        test_id=meta["test_id"],
        cell_id=meta["cell_id"],
        test_name=meta.get("test_name", meta["test_id"]),
        protocol=meta.get("protocol", ""),
        ambient_temp_c=meta.get("ambient_temp_c"),
        status=meta.get("status", "running"),
        source_file=str(path),
        chemistry=meta["chemistry"],
        cell=meta.get("cell", {}),
        materials=meta.get("materials", []),
        steps=steps,
    )
