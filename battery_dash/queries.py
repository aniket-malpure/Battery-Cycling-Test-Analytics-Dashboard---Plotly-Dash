"""Read-side queries shared by the Dash app and the report generator."""

from __future__ import annotations

import sqlite3

import pandas as pd

from . import config


def _ph(values) -> str:
    return ",".join("?" * len(values))


def test_summary(con: sqlite3.Connection, chemistries: list[str] | None = None) -> pd.DataFrame:
    sql = "SELECT * FROM v_test_summary"
    params: list = []
    if chemistries:
        sql += f" WHERE chemistry IN ({_ph(chemistries)})"
        params = list(chemistries)
    df = pd.read_sql_query(sql + " ORDER BY test_id", con, params=params)
    eol = pd.read_sql_query(
        "SELECT test_id, MIN(cycle_index) AS cycles_to_eol FROM cycles WHERE soh_smooth_pct < ? GROUP BY test_id",
        con,
        params=[config.EOL_SOH_PCT],
    )
    return df.merge(eol, on="test_id", how="left")


def chemistries(con: sqlite3.Connection) -> list[str]:
    return [r[0] for r in con.execute("SELECT name FROM chemistries ORDER BY name")]


def cycles(con, test_ids: list[str], cycle_min: int | None = None, cycle_max: int | None = None) -> pd.DataFrame:
    if not test_ids:
        return pd.DataFrame()
    sql = f"SELECT * FROM cycles WHERE test_id IN ({_ph(test_ids)})"
    params: list = list(test_ids)
    if cycle_min is not None:
        sql += " AND cycle_index >= ?"
        params.append(int(cycle_min))
    if cycle_max is not None:
        sql += " AND cycle_index <= ?"
        params.append(int(cycle_max))
    return pd.read_sql_query(sql + " ORDER BY test_id, cycle_index", con, params=params)


def cycle_indices(con, test_id: str) -> list[int]:
    return [r[0] for r in con.execute("SELECT cycle_index FROM cycles WHERE test_id=? ORDER BY cycle_index", (test_id,))]


def timeseries(con, test_id: str, cycle_list: list[int], step: str = "discharge") -> pd.DataFrame:
    if not cycle_list:
        return pd.DataFrame()
    return pd.read_sql_query(
        f"""SELECT * FROM timeseries WHERE test_id=? AND step=? AND cycle_index IN ({_ph(cycle_list)})
            ORDER BY cycle_index, seq""",
        con,
        params=[test_id, step, *[int(c) for c in cycle_list]],
    )


def materials(con, cell_id: str) -> pd.DataFrame:
    return pd.read_sql_query(
        """SELECT bm.role, ml.lot_code, ml.supplier, ml.received_date,
                  (SELECT COUNT(*) FROM build_materials b2 WHERE b2.lot_id = ml.lot_id) AS cells_using_lot
           FROM build_materials bm JOIN material_lots ml ON ml.lot_id = bm.lot_id
           WHERE bm.cell_id = ? ORDER BY bm.role""",
        con,
        params=[cell_id],
    )


def lot_performance(con) -> pd.DataFrame:
    """Average end-of-test state of health grouped by material lot."""
    return pd.read_sql_query(
        """WITH last AS (
               SELECT t.cell_id, c.soh_smooth_pct
               FROM cycles c JOIN tests t ON t.test_id = c.test_id
               WHERE c.cycle_index = (SELECT MAX(cycle_index) FROM cycles x WHERE x.test_id = c.test_id)
           )
           SELECT ml.material_type AS material, ml.lot_code,
                  COUNT(*) AS cells, ROUND(AVG(last.soh_smooth_pct), 1) AS avg_last_soh_pct
           FROM build_materials bm
           JOIN material_lots ml ON ml.lot_id = bm.lot_id
           JOIN last ON last.cell_id = bm.cell_id
           GROUP BY ml.lot_id ORDER BY avg_last_soh_pct""",
        con,
    )


def test_info(con, test_id: str) -> dict | None:
    row = con.execute(
        """SELECT t.*, ch.name AS chemistry, ch.cathode, ch.anode, ch.electrolyte,
                  ch.nominal_capacity_ah, ch.nominal_voltage_v, cl.form_factor, cl.build_date
           FROM tests t JOIN cells cl ON cl.cell_id = t.cell_id
           JOIN chemistries ch ON ch.chemistry_id = cl.chemistry_id WHERE t.test_id = ?""",
        (test_id,),
    ).fetchone()
    return dict(row) if row else None


def kpis(con) -> dict:
    one = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
    last_run = con.execute(
        "SELECT finished_at, status, files_ingested FROM ingest_runs WHERE finished_at IS NOT NULL ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    return {
        "cells": one("SELECT COUNT(*) FROM cells"),
        "tests": one("SELECT COUNT(*) FROM tests"),
        "running": one("SELECT COUNT(*) FROM tests WHERE status = 'running'"),
        "cycles": one("SELECT COUNT(*) FROM cycles"),
        "last_run": dict(last_run) if last_run else None,
    }
