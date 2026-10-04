"""Format-neutral containers that every raw-file parser produces."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np


@dataclass
class RawStep:
    """One charge or discharge step exactly as the cycler recorded it."""

    step: str  # "charge" or "discharge"
    start_time: datetime
    t_s: np.ndarray  # seconds since the start of this step
    voltage: np.ndarray
    current: np.ndarray
    temperature: np.ndarray
    reported_capacity_ah: float | None = None  # some cyclers report capacity directly


@dataclass
class RawTest:
    """A full cycling test for one cell plus its build metadata."""

    test_id: str
    cell_id: str
    test_name: str
    protocol: str
    ambient_temp_c: float | None
    status: str
    source_file: str
    chemistry: dict
    cell: dict = field(default_factory=dict)
    materials: list[dict] = field(default_factory=list)
    steps: list[RawStep] = field(default_factory=list)
