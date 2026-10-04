# Battery Cycling Test Analytics Dashboard

An end-to-end pipeline and Plotly Dash app for battery cycle-life testing data.
Raw cycler files land in a drop folder, a cron job ingests anything new, Pandas
and SciPy turn raw voltage/current/temperature traces into cycle-level metrics,
and everything is stored in a SQLite test-tracking database that the dashboard
reads.

It works with the public **NASA PCoE battery aging dataset** (cells B0005,
B0006, B0007, B0018, about 636 discharge cycles) and with **generic cycler CSV
exports**. A synthetic data generator is included so the whole project runs
offline in under a minute.

## What it does

| Area | Details |
|---|---|
| Ingestion | NASA `.mat` parser and a cycler CSV parser with a JSON metadata sidecar. SHA-256 change detection so reruns only load new or changed files; a running test that grows is reloaded automatically. File lock prevents overlapping cron runs. Every run is logged to `ingest_runs`. |
| Processing | Ah and Wh by trapezoidal integration of current and power, coulombic and energy efficiency per cycle, state of health against the first cycles, Savitzky-Golay smoothing of voltage curves and fade trends, cycles to 80% SOH, incremental capacity (dQ/dV) analysis, QC flags for missing charges or impossible efficiencies. |
| Storage | SQLite schema: `chemistries`, `cells`, `material_lots`, `build_materials`, `tests`, `cycles`, `timeseries`, `ingest_runs`, plus a `v_test_summary` view. |
| Dashboard | KPI tiles, chemistry and test filters, cycle range slider, capacity fade (SOH or Ah, raw plus smoothed), coulombic efficiency, voltage curve and dQ/dV overlays for chosen cycles, test tracker with build materials per cell, material lots ranked by state of health, one-click report download. Auto-refreshes every 60 seconds so cron loads appear without a reload. |
| Reports | Self-contained HTML report per test (summary, build materials, four interactive charts), from the app or the CLI. |

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m battery_dash.ingest.synthetic      # 6 synthetic cells, 3 chemistries, ~1,040 cycles
python -m battery_dash.ingest.pipeline       # load into data/battery.db
python -m battery_dash.app                   # open http://127.0.0.1:8050
```

Or with make: `make install demo`.

## Using the NASA dataset

```bash
python -m battery_dash.ingest.download_nasa  # downloads and extracts B0005/6/7/18 into data/raw/nasa
python -m battery_dash.ingest.pipeline
```

If the download URL has moved, get the "Battery Data Set" archive from the
NASA Open Data Portal (PCoE data repository) and run
`python -m battery_dash.ingest.download_nasa --zip path/to/archive.zip`.
You can also drop the `.mat` files straight into `data/raw/`.

Synthetic and NASA data can live side by side. To show only NASA data, delete
`data/raw/synthetic` and `data/battery.db`, then rerun the pipeline.

## Cycler CSV format

`MyCell.csv`, one row per sample:

| column | meaning |
|---|---|
| `cycle_index` | cycle number from the cycler |
| `step_type` | `charge`, `discharge` or `rest` (rest rows are ignored) |
| `test_time_s` | seconds since test start |
| `voltage_v` | cell voltage |
| `current_a` | current, positive on charge |
| `temperature_c` | optional |

`MyCell.meta.json` next to it:

```json
{
  "test_id": "T-CELL-001",
  "cell_id": "CELL-001",
  "test_name": "0.5C cycle life",
  "protocol": "CC-CV charge 0.5C, CC discharge 0.5C",
  "ambient_temp_c": 25,
  "start_time": "2026-06-01T09:00:00",
  "status": "running",
  "chemistry": {"name": "LFP/Graphite", "cathode": "LiFePO4", "anode": "Graphite",
                "electrolyte": "1M LiPF6 in EC/DMC", "nominal_capacity_ah": 2.5, "nominal_voltage_v": 3.2},
  "cell": {"form_factor": "Pouch", "build_date": "2026-05-20"},
  "materials": [
    {"role": "electrolyte", "material_type": "electrolyte", "supplier": "Acme", "lot_code": "EL-2405-A", "received_date": "2026-05-01"}
  ]
}
```

Editing the sidecar (for example changing `status` to `complete`) changes the
file hash, so the next ingest picks it up.

## Scheduling with cron

```bash
crontab -e
# paste the lines from scripts/crontab.example and fix the path
```

`scripts/run_ingest.sh` activates `.venv`, runs one incremental ingest and
appends to `logs/cron.log`. The example schedule runs every 15 minutes, plus a
nightly forced reload that also rebuilds every HTML report.

## Reports

```bash
python -m battery_dash.reports --test-id T-SYN-NMC-02
python -m battery_dash.reports --all          # writes to reports/
```

## Production

```bash
gunicorn "battery_dash.wsgi:server" -b 0.0.0.0:8050 -w 2
# or
docker build -t battery-dash . && docker run -p 8050:8050 -v $(pwd)/data:/data battery-dash
```

SQLite runs in WAL mode, so the dashboard keeps reading while cron writes.

## Configuration

All settings are environment variables (see `battery_dash/config.py`):
`BCD_DATA_DIR`, `BCD_RAW_DIR`, `BCD_DB_PATH`, `BCD_REPORT_DIR`, `BCD_LOG_DIR`,
`BCD_MAX_POINTS` (time-series points kept per step, default 250),
`BCD_EOL_SOH` (default 80), `BCD_HOST`, `BCD_PORT`, `BCD_REFRESH_SECONDS`,
`BCD_NASA_URL`.

## Tests

```bash
pytest -q
```

16 tests cover the integration math, cycle pairing, QC flags, smoothing, dQ/dV
peak location, the NASA parser (against a fixture with the real `.mat`
layout), incremental and forced ingestion, failure isolation, every figure,
report generation, and every Dash callback against a real database.

## Project layout

```
battery_dash/
  config.py              settings and paths
  schema.sql, db.py      SQLite schema and connection helpers
  models.py              format-neutral RawTest / RawStep
  ingest/
    parse_nasa.py        NASA PCoE .mat parser
    parse_cycler_csv.py  generic cycler CSV + sidecar parser
    synthetic.py         offline sample data generator
    download_nasa.py     dataset downloader
    transform.py         metrics, smoothing, dQ/dV
    pipeline.py          incremental, locked, logged ingestion CLI
  queries.py             read queries shared by app and reports
  figures.py             Plotly figure builders
  reports.py             HTML report generator
  app/                   Dash layout, callbacks, styles
  wsgi.py                gunicorn entry point
scripts/                 cron wrapper and example crontab
tests/                   pytest suite
```

## Notes on the synthetic data

Synthetic cells are labeled `(synthetic)` in every chemistry name and carry
`source = synthetic`. The model uses a per-chemistry open-circuit-voltage
curve, ohmic drop with growing resistance, CC-CV charging, linear plus
quadratic capacity fade, formation-stage efficiency and resistive heating. One
electrolyte lot (`EL-2407-B`) is set to fade faster, so the materials table
has a real signal to surface.
