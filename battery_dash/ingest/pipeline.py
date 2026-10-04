"""Incremental ingestion: raw drop folder -> parse -> transform -> SQLite.

Designed to run unattended from cron:
  * scans the raw folder for NASA .mat files and cycler CSV exports
  * skips files whose SHA-256 is already loaded, so reruns are cheap
  * re-ingests a test when its file changed (a running test that grew)
  * holds a file lock so two cron runs never overlap
  * records every run in the ingest_runs table

Usage:
    python -m battery_dash.ingest.pipeline [--raw-dir DIR] [--db PATH] [--force]
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import logging
import sqlite3
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .. import config, db
from ..models import RawTest
from .parse_cycler_csv import read_cycler_csv
from .parse_nasa import read_nasa_mat
from .transform import build_cycles, build_timeseries

log = logging.getLogger("battery_dash.ingest")

CYCLE_COLUMNS = [
    "test_id", "cycle_index", "start_time", "charge_ah", "discharge_ah", "charge_wh",
    "discharge_wh", "coulombic_eff", "energy_eff", "discharge_ah_smooth", "soh_pct",
    "soh_smooth_pct", "discharge_duration_s", "min_v", "max_v", "mean_temp_c",
    "max_temp_c", "qc_flag",
]
TS_COLUMNS = [
    "test_id", "cycle_index", "step", "seq", "t_s", "voltage_v", "voltage_smooth_v",
    "current_a", "temp_c", "capacity_ah",
]


# ---------------------------------------------------------------- discovery
def discover(raw_dir: Path) -> list[Path]:
    mats = sorted(raw_dir.rglob("*.mat"))
    csvs = sorted(p for p in raw_dir.rglob("*.csv") if p.with_suffix(".meta.json").exists())
    return mats + csvs


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    # Metadata edits (status change, lot correction) should also trigger a reload.
    sidecar = path.with_suffix(".meta.json")
    if sidecar.exists():
        h.update(sidecar.read_bytes())
    return h.hexdigest()


def parse_file(path: Path) -> RawTest:
    if path.suffix.lower() == ".mat":
        return read_nasa_mat(path)
    if path.suffix.lower() == ".csv":
        return read_cycler_csv(path)
    raise ValueError(f"unsupported file type: {path.name}")


# ---------------------------------------------------------------- loading
def _rows(df: pd.DataFrame, columns: list[str]) -> list[tuple]:
    out = df.reindex(columns=columns).astype(object)
    out = out.where(pd.notna(out), None)
    return [tuple(r) for r in out.itertuples(index=False, name=None)]


def _upsert_chemistry(con: sqlite3.Connection, chem: dict) -> int:
    con.execute("INSERT OR IGNORE INTO chemistries(name) VALUES (?)", (chem["name"],))
    con.execute(
        """UPDATE chemistries SET cathode=?, anode=?, electrolyte=?,
           nominal_capacity_ah=?, nominal_voltage_v=? WHERE name=?""",
        (
            chem.get("cathode"), chem.get("anode"), chem.get("electrolyte"),
            chem.get("nominal_capacity_ah"), chem.get("nominal_voltage_v"), chem["name"],
        ),
    )
    return con.execute("SELECT chemistry_id FROM chemistries WHERE name=?", (chem["name"],)).fetchone()[0]


def _upsert_cell(con: sqlite3.Connection, raw: RawTest, chemistry_id: int) -> None:
    c = raw.cell
    con.execute(
        """INSERT INTO cells(cell_id, chemistry_id, form_factor, build_date, source, notes)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(cell_id) DO UPDATE SET chemistry_id=excluded.chemistry_id,
             form_factor=excluded.form_factor, build_date=excluded.build_date,
             source=excluded.source, notes=excluded.notes""",
        (raw.cell_id, chemistry_id, c.get("form_factor"), c.get("build_date"), c.get("source"), c.get("notes")),
    )
    for m in raw.materials:
        con.execute(
            """INSERT OR IGNORE INTO material_lots(material_type, supplier, lot_code, received_date)
               VALUES (?,?,?,?)""",
            (m["material_type"], m.get("supplier"), m["lot_code"], m.get("received_date")),
        )
        lot_id = con.execute(
            "SELECT lot_id FROM material_lots WHERE material_type=? AND lot_code=?",
            (m["material_type"], m["lot_code"]),
        ).fetchone()[0]
        con.execute(
            "INSERT OR REPLACE INTO build_materials(cell_id, lot_id, role) VALUES (?,?,?)",
            (raw.cell_id, lot_id, m.get("role", m["material_type"])),
        )


def load_test(con: sqlite3.Connection, raw: RawTest, source_hash: str) -> int:
    """Replace one test and everything under it inside a single transaction."""
    cycles = build_cycles(raw)
    ts = build_timeseries(raw)
    last = raw.steps[-1]
    end_time = last.start_time + timedelta(seconds=float(last.t_s[-1]))

    with con:
        chemistry_id = _upsert_chemistry(con, raw.chemistry)
        _upsert_cell(con, raw, chemistry_id)
        con.execute("DELETE FROM tests WHERE test_id=?", (raw.test_id,))  # cascades
        con.execute(
            """INSERT INTO tests(test_id, cell_id, test_name, protocol, ambient_temp_c,
               start_time, end_time, status, source_file, source_hash, ingested_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                raw.test_id, raw.cell_id, raw.test_name, raw.protocol, raw.ambient_temp_c,
                raw.steps[0].start_time.isoformat(timespec="seconds"),
                end_time.isoformat(timespec="seconds"), raw.status, raw.source_file,
                source_hash, datetime.now().isoformat(timespec="seconds"),
            ),
        )
        if not cycles.empty:
            con.executemany(
                f"INSERT INTO cycles({','.join(CYCLE_COLUMNS)}) VALUES ({','.join('?' * len(CYCLE_COLUMNS))})",
                _rows(cycles, CYCLE_COLUMNS),
            )
        if not ts.empty:
            con.executemany(
                f"INSERT INTO timeseries({','.join(TS_COLUMNS)}) VALUES ({','.join('?' * len(TS_COLUMNS))})",
                _rows(ts, TS_COLUMNS),
            )
    return len(cycles)


# ---------------------------------------------------------------- run
@contextmanager
def ingest_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("another ingest run is in progress; exiting") from None
        yield


def run(raw_dir: Path, db_path: Path, force: bool = False) -> dict:
    con = db.connect(db_path)
    db.init_db(con)
    started = datetime.now().isoformat(timespec="seconds")
    run_id = con.execute(
        "INSERT INTO ingest_runs(started_at, raw_dir, status) VALUES (?,?, 'running')",
        (started, str(raw_dir)),
    ).lastrowid
    con.commit()

    stats = {"files_seen": 0, "files_ingested": 0, "files_skipped": 0, "files_failed": 0, "cycles_loaded": 0}
    errors: list[str] = []
    files = discover(raw_dir)
    stats["files_seen"] = len(files)
    log.info("found %d raw files in %s", len(files), raw_dir)

    for path in files:
        t0 = time.perf_counter()
        try:
            digest = file_hash(path)
            if not force and con.execute("SELECT 1 FROM tests WHERE source_hash=?", (digest,)).fetchone():
                stats["files_skipped"] += 1
                log.debug("skip unchanged %s", path.name)
                continue
            raw = parse_file(path)
            n = load_test(con, raw, digest)
            stats["files_ingested"] += 1
            stats["cycles_loaded"] += n
            log.info("loaded %-22s %4d cycles in %.1fs", raw.test_id, n, time.perf_counter() - t0)
        except Exception as exc:  # keep going; one bad file must not block the rest
            stats["files_failed"] += 1
            errors.append(f"{path.name}: {exc}")
            log.exception("failed %s", path.name)

    status = "failed" if stats["files_failed"] and not stats["files_ingested"] and not stats["files_skipped"] else (
        "partial" if stats["files_failed"] else "success"
    )
    con.execute(
        """UPDATE ingest_runs SET finished_at=?, files_seen=?, files_ingested=?, files_skipped=?,
           files_failed=?, cycles_loaded=?, status=?, message=? WHERE run_id=?""",
        (
            datetime.now().isoformat(timespec="seconds"), stats["files_seen"], stats["files_ingested"],
            stats["files_skipped"], stats["files_failed"], stats["cycles_loaded"], status,
            "; ".join(errors)[:2000] or None, run_id,
        ),
    )
    con.commit()
    con.close()
    stats["status"] = status
    log.info("run %d %s: %s", run_id, status, stats)
    return stats


def setup_logging(verbose: bool = False) -> None:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(config.LOG_DIR / "ingest.log")],
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw-dir", type=Path, default=config.RAW_DIR)
    ap.add_argument("--db", type=Path, default=config.DB_PATH)
    ap.add_argument("--force", action="store_true", help="reload files even if unchanged")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    setup_logging(args.verbose)
    np.seterr(all="ignore")
    with ingest_lock(args.db.parent / ".ingest.lock"):
        stats = run(args.raw_dir, args.db, force=args.force)
    return 1 if stats["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
