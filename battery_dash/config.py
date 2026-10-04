"""Central configuration. Every path can be overridden with an environment variable."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.getenv("BCD_DATA_DIR", PROJECT_ROOT / "data"))
RAW_DIR = Path(os.getenv("BCD_RAW_DIR", DATA_DIR / "raw"))
DB_PATH = Path(os.getenv("BCD_DB_PATH", DATA_DIR / "battery.db"))
REPORT_DIR = Path(os.getenv("BCD_REPORT_DIR", PROJECT_ROOT / "reports"))
LOG_DIR = Path(os.getenv("BCD_LOG_DIR", PROJECT_ROOT / "logs"))
LOCK_FILE = DATA_DIR / ".ingest.lock"

# Time-series rows kept per charge/discharge step after downsampling.
MAX_POINTS_PER_STEP = int(os.getenv("BCD_MAX_POINTS", "250"))

# State of health threshold used to flag end of life.
EOL_SOH_PCT = float(os.getenv("BCD_EOL_SOH", "80"))

# Coulombic efficiency outside this window is flagged as a data quality issue.
CE_VALID_RANGE = (0.5, 1.2)

# Dash server settings.
APP_HOST = os.getenv("BCD_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("BCD_PORT", "8050"))
REFRESH_SECONDS = int(os.getenv("BCD_REFRESH_SECONDS", "60"))

# NASA Prognostics Center of Excellence battery aging dataset.
NASA_URL = os.getenv(
    "BCD_NASA_URL",
    "https://phm-datasets.s3.amazonaws.com/NASA/5.+Battery+Data+Set.zip",
)
NASA_CELLS = ("B0005", "B0006", "B0007", "B0018")
NASA_CHEMISTRY = {
    "name": "Li-ion 18650 (NASA PCoE)",
    "cathode": "Not disclosed",
    "anode": "Not disclosed",
    "electrolyte": "Not disclosed",
    "nominal_capacity_ah": 2.0,
    "nominal_voltage_v": 3.7,
}
