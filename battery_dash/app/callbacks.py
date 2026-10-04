"""Dash callbacks. Each one opens its own short-lived SQLite connection."""

from __future__ import annotations

import time
from contextlib import closing

from dash import Input, Output, State, dcc, no_update

from .. import figures, queries, reports
from .. import db as dbmod


def register_callbacks(app, db_path) -> None:
    def conn():
        return closing(dbmod.connect(db_path))

    # ------------------------------------------------------------ header + KPIs
    @app.callback(
        Output("kpi-cells", "children"),
        Output("kpi-tests", "children"),
        Output("kpi-running", "children"),
        Output("kpi-cycles", "children"),
        Output("kpi-soh", "children"),
        Output("kpi-soh-sub", "children"),
        Output("last-ingest", "children"),
        Output("chem-filter", "options"),
        Input("refresh", "n_intervals"),
    )
    def refresh_header(_):
        with conn() as con:
            k = queries.kpis(con)
            summary = queries.test_summary(con)
            chems = queries.chemistries(con)
        soh, soh_sub = "-", ""
        if not summary.empty and summary["last_soh_pct"].notna().any():
            worst = summary.loc[summary["last_soh_pct"].idxmin()]
            soh, soh_sub = f"{worst['last_soh_pct']:.1f}%", str(worst["test_id"])
        run = k["last_run"]
        last = f"Last ingest {run['finished_at'].replace('T', ' ')} ({run['status']})" if run else "No ingest runs yet"
        return (
            f"{k['cells']:,}", f"{k['tests']:,}", f"{k['running']} running", f"{k['cycles']:,}",
            soh, soh_sub, last, [{"label": c, "value": c} for c in chems],
        )

    # ------------------------------------------------------------ test selection
    @app.callback(
        Output("test-select", "options"),
        Output("test-select", "value"),
        Input("chem-filter", "value"),
        Input("refresh", "n_intervals"),
        State("test-select", "value"),
    )
    def test_options(chems, _, current):
        with conn() as con:
            summary = queries.test_summary(con, chems or None)
        ids = summary["test_id"].tolist()
        options = [{"label": f"{r.test_id}  ({r.chemistry})", "value": r.test_id} for r in summary.itertuples()]
        if current:
            value = [t for t in current if t in ids]
        else:
            value = ids[:4]
        return options, value[: figures.MAX_SERIES]

    @app.callback(
        Output("color-slots", "data"),
        Output("selection-note", "children"),
        Input("test-select", "value"),
        State("color-slots", "data"),
    )
    def assign_colors(selected, slots):
        """Keep each test's color for as long as it stays selected."""
        selected = selected or []
        note = ""
        if len(selected) > figures.MAX_SERIES:
            note = f"Showing the first {figures.MAX_SERIES} tests. Remove one to add another."
            selected = selected[: figures.MAX_SERIES]
        slots = {t: s for t, s in (slots or {}).items() if t in selected}
        free = [i for i in range(figures.MAX_SERIES) if i not in slots.values()]
        for t in selected:
            if t not in slots:
                slots[t] = free.pop(0)
        return slots, note

    @app.callback(
        Output("cycle-range", "max"),
        Output("cycle-range", "value"),
        Input("test-select", "value"),
        State("cycle-range", "value"),
        State("cycle-range", "max"),
    )
    def cycle_bounds(selected, current, old_max):
        if not selected:
            return no_update, no_update
        with conn() as con:
            row = con.execute(
                f"SELECT MAX(cycle_index) FROM cycles WHERE test_id IN ({','.join('?' * len(selected))})", selected
            ).fetchone()
        new_max = int(row[0] or 1)
        lo, hi = current or [1, new_max]
        if hi >= (old_max or hi):  # slider was at the end: follow the new end
            hi = new_max
        return new_max, [min(lo, new_max), min(hi, new_max)]

    def _colors(selected, slots):
        slots = slots or {}
        return {t: figures.CATEGORICAL[slots[t]] for t in (selected or []) if t in slots}

    # ------------------------------------------------------------ trend charts
    @app.callback(
        Output("fade-graph", "figure"),
        Input("test-select", "value"),
        Input("color-slots", "data"),
        Input("fade-metric", "value"),
        Input("fade-smooth", "value"),
        Input("cycle-range", "value"),
    )
    def fade_chart(selected, slots, metric, smooth, crange):
        colors = _colors(selected, slots)
        if not colors:
            return figures.empty_figure("Select one or more tests")
        with conn() as con:
            cyc = queries.cycles(con, list(colors), *(crange or [None, None]))
        return figures.capacity_fade(cyc, colors, metric, smooth=bool(smooth))

    @app.callback(
        Output("ce-graph", "figure"),
        Input("test-select", "value"),
        Input("color-slots", "data"),
        Input("cycle-range", "value"),
    )
    def ce_chart(selected, slots, crange):
        colors = _colors(selected, slots)
        if not colors:
            return figures.empty_figure("Select one or more tests")
        with conn() as con:
            cyc = queries.cycles(con, list(colors), *(crange or [None, None]))
        return figures.coulombic_efficiency(cyc, colors)

    # ------------------------------------------------------------ curve charts
    @app.callback(
        Output("focus-test", "options"),
        Output("focus-test", "value"),
        Output("report-test", "options"),
        Output("report-test", "value"),
        Input("test-select", "options"),
        Input("test-select", "value"),
        State("focus-test", "value"),
        State("report-test", "value"),
    )
    def focus_options(all_options, selected, focus, report):
        all_options = all_options or []
        ids = [o["value"] for o in all_options]
        focus = focus if focus in ids else ((selected or ids or [None])[0])
        report = report if report in ids else focus
        return all_options, focus, all_options, report

    @app.callback(
        Output("focus-cycles", "options"),
        Output("focus-cycles", "value"),
        Input("focus-test", "value"),
    )
    def focus_cycles(test_id):
        if not test_id:
            return [], []
        with conn() as con:
            idx = queries.cycle_indices(con, test_id)
        return [{"label": f"Cycle {c}", "value": c} for c in idx], figures.evenly_spaced(idx, 6)

    @app.callback(
        Output("voltage-graph", "figure"),
        Output("dqdv-graph", "figure"),
        Input("focus-test", "value"),
        Input("focus-cycles", "value"),
        Input("focus-step", "value"),
    )
    def curve_charts(test_id, cycles, step):
        if not test_id or not cycles:
            empty = figures.empty_figure("Pick a test and at least one cycle")
            return empty, empty
        cycles = sorted(cycles)[: figures.MAX_SERIES]
        with conn() as con:
            ts = queries.timeseries(con, test_id, cycles, step)
        return figures.voltage_curves(ts, test_id, step), figures.dqdv_curves(ts, test_id, step)

    # ------------------------------------------------------------ tracker
    @app.callback(
        Output("tracker-table", "data"),
        Output("lots-table", "data"),
        Input("refresh", "n_intervals"),
        Input("chem-filter", "value"),
    )
    def tracker(_, chems):
        with conn() as con:
            summary = queries.test_summary(con, chems or None)
            lots = queries.lot_performance(con)
        summary["start_time"] = summary["start_time"].str.replace("T", " ").str.slice(0, 16)
        summary = summary.astype(object).where(summary.notna(), None)
        return summary.to_dict("records"), lots.to_dict("records")

    @app.callback(
        Output("materials-table", "data"),
        Output("materials-title", "children"),
        Input("tracker-table", "selected_rows"),
        State("tracker-table", "data"),
    )
    def materials(selected_rows, data):
        if not selected_rows or not data:
            return [], "Build materials (select a test above)"
        cell_id = data[selected_rows[0]]["cell_id"]
        with conn() as con:
            mats = queries.materials(con, cell_id)
        title = f"Build materials for {cell_id}" + ("" if not mats.empty else ": none recorded")
        return mats.to_dict("records"), title

    # ------------------------------------------------------------ reports
    @app.callback(
        Output("report-download", "data"),
        Output("report-status", "children"),
        Input("report-button", "n_clicks"),
        State("report-test", "value"),
        prevent_initial_call=True,
    )
    def download_report(_, test_id):
        if not test_id:
            return no_update, "Pick a test first."
        t0 = time.perf_counter()
        with conn() as con:
            page = reports.build_report_html(con, test_id)
        took = time.perf_counter() - t0
        return dcc.send_string(page, f"{test_id}_report.html"), f"Built {test_id} report in {took:.1f}s."
