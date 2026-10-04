import json
import sqlite3

from battery_dash.ingest.parse_nasa import read_nasa_mat
from battery_dash.ingest.pipeline import run


def test_nasa_parser_reads_charge_and_discharge_only(nasa_mat):
    raw = read_nasa_mat(nasa_mat)
    assert raw.test_id == "NASA-B0005"
    assert [s.step for s in raw.steps[:2]] == ["charge", "discharge"]
    assert len(raw.steps) == 10  # impedance entries skipped
    assert abs(raw.steps[1].reported_capacity_ah - 1.85) < 1e-9


def test_pipeline_loads_nasa_and_csv(tmp_path, nasa_mat, synthetic_dir):
    nasa_mat.rename(synthetic_dir / nasa_mat.name)
    db_path = tmp_path / "t.db"
    stats = run(synthetic_dir, db_path)
    assert stats["files_ingested"] == 3 and stats["files_failed"] == 0
    assert stats["cycles_loaded"] == 30 + 20 + 5

    con = sqlite3.connect(db_path)
    assert con.execute("SELECT COUNT(*) FROM tests").fetchone()[0] == 3
    assert con.execute("SELECT COUNT(*) FROM build_materials").fetchone()[0] == 8
    nasa_cap = con.execute(
        "SELECT discharge_ah FROM cycles WHERE test_id='NASA-B0005' AND cycle_index=1"
    ).fetchone()[0]
    assert abs(nasa_cap - 1.85) < 1e-9  # reported capacity wins over integration


def test_rerun_skips_unchanged_and_reloads_changed(tmp_path, synthetic_dir):
    db_path = tmp_path / "t.db"
    run(synthetic_dir, db_path)
    assert run(synthetic_dir, db_path)["files_skipped"] == 2

    meta = synthetic_dir / "SYN-T-02.meta.json"
    data = json.loads(meta.read_text())
    data["status"] = "complete"
    meta.write_text(json.dumps(data))

    stats = run(synthetic_dir, db_path)
    assert stats["files_ingested"] == 1 and stats["files_skipped"] == 1
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT status FROM tests WHERE test_id='T-SYN-T-02'").fetchone()[0] == "complete"
    assert con.execute("SELECT COUNT(*) FROM cycles WHERE test_id='T-SYN-T-02'").fetchone()[0] == 20


def test_bad_file_is_recorded_and_others_still_load(tmp_path, synthetic_dir):
    bad = synthetic_dir / "BROKEN.csv"
    bad.write_text("nope,columns\n1,2\n")
    bad.with_suffix(".meta.json").write_text(json.dumps({"test_id": "X", "cell_id": "X", "start_time": "2026-01-01T00:00:00", "chemistry": {"name": "c"}}))
    stats = run(synthetic_dir, tmp_path / "t.db")
    assert stats["files_failed"] == 1 and stats["files_ingested"] == 2 and stats["status"] == "partial"
