"""Smoke tests for figures, reports and every Dash callback against a real database."""

import pytest

from battery_dash import db, figures, queries, reports
from battery_dash.ingest.pipeline import run


@pytest.fixture
def loaded_db(tmp_path, synthetic_dir):
    path = tmp_path / "t.db"
    run(synthetic_dir, path)
    return path


def test_figures_render(loaded_db):
    con = db.connect(loaded_db)
    ids = queries.test_summary(con)["test_id"].tolist()
    colors = figures.default_colors(ids)
    cyc = queries.cycles(con, ids)
    assert len(figures.capacity_fade(cyc, colors, "soh").data) == 2 * len(ids)  # raw + smoothed
    assert len(figures.capacity_fade(cyc, colors, "ah", smooth=False).data) == len(ids)
    assert len(figures.coulombic_efficiency(cyc, colors).data) == len(ids)

    picks = figures.evenly_spaced(queries.cycle_indices(con, ids[0]), 4)
    ts = queries.timeseries(con, ids[0], picks)
    assert len(figures.voltage_curves(ts, ids[0], "discharge").data) == 4
    assert len(figures.dqdv_curves(ts, ids[0], "discharge").data) == 4


def test_sequential_ramp_goes_light_to_dark():
    ramp = figures.sequential(5)
    lum = [sum(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in ramp]
    assert lum == sorted(lum, reverse=True)


def test_report_contains_summary_and_materials(loaded_db, tmp_path):
    con = db.connect(loaded_db)
    path = reports.write_report(con, "T-SYN-T-01", tmp_path)
    page = path.read_text()
    assert "Cycling test report: T-SYN-T-01" in page and "EL-X" in page and "plotly" in page


def test_every_callback_runs(loaded_db):
    from battery_dash.app import create_app

    app = create_app(loaded_db)
    cb = {k.split("..")[1].split(".")[0] if ".." in k else k.split(".")[0]: v["callback"]
          for k, v in app.callback_map.items()}
    call = lambda name, *args: cb[name].__wrapped__(*args)  # noqa: E731

    header = call("kpi-cells", 0)
    assert header[0] == "2" and header[1] == "2"

    options, value = call("test-select", None, 0, None)
    assert value == ["T-SYN-T-01", "T-SYN-T-02"]

    slots, _ = call("color-slots", value, {})
    assert slots == {"T-SYN-T-01": 0, "T-SYN-T-02": 1}
    slots2, _ = call("color-slots", ["T-SYN-T-02"], slots)
    assert slots2 == {"T-SYN-T-02": 1}  # survivor keeps its color

    assert call("cycle-range", value, [1, 200], 200)[0] == 30
    assert call("fade-graph", value, slots, "soh", ["smooth"], [1, 30]).data
    assert call("ce-graph", value, slots, [1, 30]).data

    focus = call("focus-test", options, value, None, None)
    cyc_opts, cyc_val = call("focus-cycles", focus[1])
    v_fig, d_fig = call("voltage-graph", focus[1], cyc_val, "discharge")
    assert len(v_fig.data) == len(cyc_val) and d_fig.data

    rows, lots = call("tracker-table", 0, None)
    assert len(rows) == 2 and lots
    mats, title = call("materials-table", [0], rows)
    assert len(mats) == 4 and "SYN-T-01" in title

    download, status = call("report-download", 1, "T-SYN-T-01")
    assert download["filename"] == "T-SYN-T-01_report.html" and "Built" in status
