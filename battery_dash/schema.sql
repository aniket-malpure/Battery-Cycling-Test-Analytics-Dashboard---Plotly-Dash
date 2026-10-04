-- Battery cycling test-tracking schema (SQLite).
-- chemistries -> cells -> tests -> cycles -> timeseries
-- material_lots <-> cells through build_materials (build & materials tracking)

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS chemistries (
    chemistry_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL UNIQUE,
    cathode             TEXT,
    anode               TEXT,
    electrolyte         TEXT,
    nominal_capacity_ah REAL,
    nominal_voltage_v   REAL
);

CREATE TABLE IF NOT EXISTS cells (
    cell_id      TEXT PRIMARY KEY,
    chemistry_id INTEGER NOT NULL REFERENCES chemistries(chemistry_id),
    form_factor  TEXT,
    build_date   TEXT,
    source       TEXT,
    notes        TEXT
);

CREATE TABLE IF NOT EXISTS material_lots (
    lot_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    material_type TEXT NOT NULL,
    supplier      TEXT,
    lot_code      TEXT NOT NULL,
    received_date TEXT,
    UNIQUE (material_type, lot_code)
);

CREATE TABLE IF NOT EXISTS build_materials (
    cell_id TEXT    NOT NULL REFERENCES cells(cell_id) ON DELETE CASCADE,
    lot_id  INTEGER NOT NULL REFERENCES material_lots(lot_id),
    role    TEXT    NOT NULL,
    PRIMARY KEY (cell_id, role)
);

CREATE TABLE IF NOT EXISTS tests (
    test_id        TEXT PRIMARY KEY,
    cell_id        TEXT NOT NULL REFERENCES cells(cell_id),
    test_name      TEXT,
    protocol       TEXT,
    ambient_temp_c REAL,
    start_time     TEXT,
    end_time       TEXT,
    status         TEXT NOT NULL DEFAULT 'running',
    source_file    TEXT,
    source_hash    TEXT,
    ingested_at    TEXT
);

CREATE TABLE IF NOT EXISTS cycles (
    test_id              TEXT    NOT NULL REFERENCES tests(test_id) ON DELETE CASCADE,
    cycle_index          INTEGER NOT NULL,
    start_time           TEXT,
    charge_ah            REAL,
    discharge_ah         REAL,
    charge_wh            REAL,
    discharge_wh         REAL,
    coulombic_eff        REAL,
    energy_eff           REAL,
    discharge_ah_smooth  REAL,
    soh_pct              REAL,
    soh_smooth_pct       REAL,
    discharge_duration_s REAL,
    min_v                REAL,
    max_v                REAL,
    mean_temp_c          REAL,
    max_temp_c           REAL,
    qc_flag              TEXT NOT NULL DEFAULT 'ok',
    PRIMARY KEY (test_id, cycle_index)
);

CREATE TABLE IF NOT EXISTS timeseries (
    test_id          TEXT    NOT NULL REFERENCES tests(test_id) ON DELETE CASCADE,
    cycle_index      INTEGER NOT NULL,
    step             TEXT    NOT NULL CHECK (step IN ('charge', 'discharge')),
    seq              INTEGER NOT NULL,
    t_s              REAL,
    voltage_v        REAL,
    voltage_smooth_v REAL,
    current_a        REAL,
    temp_c           REAL,
    capacity_ah      REAL,
    PRIMARY KEY (test_id, cycle_index, step, seq)
);

CREATE INDEX IF NOT EXISTS idx_tests_cell ON tests(cell_id);
CREATE INDEX IF NOT EXISTS idx_tests_hash ON tests(source_hash);

CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    raw_dir         TEXT,
    files_seen      INTEGER DEFAULT 0,
    files_ingested  INTEGER DEFAULT 0,
    files_skipped   INTEGER DEFAULT 0,
    files_failed    INTEGER DEFAULT 0,
    cycles_loaded   INTEGER DEFAULT 0,
    status          TEXT,
    message         TEXT
);

CREATE VIEW IF NOT EXISTS v_test_summary AS
SELECT
    t.test_id,
    t.cell_id,
    ch.name                         AS chemistry,
    t.test_name,
    t.protocol,
    t.status,
    t.ambient_temp_c,
    t.start_time,
    t.end_time,
    COUNT(c.cycle_index)            AS n_cycles,
    ROUND(AVG(c.coulombic_eff) * 100, 2) AS mean_ce_pct,
    (SELECT ROUND(c2.soh_smooth_pct, 1) FROM cycles c2
       WHERE c2.test_id = t.test_id
       ORDER BY c2.cycle_index DESC LIMIT 1) AS last_soh_pct,
    (SELECT ROUND(c3.discharge_ah, 4) FROM cycles c3
       WHERE c3.test_id = t.test_id
       ORDER BY c3.cycle_index ASC LIMIT 1)  AS initial_capacity_ah,
    SUM(CASE WHEN c.qc_flag <> 'ok' THEN 1 ELSE 0 END) AS qc_issues
FROM tests t
JOIN cells cl       ON cl.cell_id = t.cell_id
JOIN chemistries ch ON ch.chemistry_id = cl.chemistry_id
LEFT JOIN cycles c  ON c.test_id = t.test_id
GROUP BY t.test_id;
