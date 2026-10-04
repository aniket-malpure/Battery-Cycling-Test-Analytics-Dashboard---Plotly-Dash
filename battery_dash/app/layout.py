"""Static page layout. All data arrives through callbacks."""

from __future__ import annotations

from dash import dash_table, dcc, html

from .. import config

GRAPH_CONFIG = {"displaylogo": False, "toImageButtonOptions": {"format": "png", "scale": 2}}

TABLE_STYLE = dict(
    style_table={"overflowX": "auto"},
    style_cell={"fontFamily": "Inter, -apple-system, Segoe UI, Roboto, sans-serif", "fontSize": "14px", "padding": "8px 10px", "textAlign": "left",
                "border": "none", "borderBottom": "1px solid var(--grid)", "backgroundColor": "var(--surface-1)",
                "color": "var(--text-primary)"},
    style_header={"fontWeight": 600, "color": "var(--text-secondary)", "backgroundColor": "var(--surface-1)",
                  "borderBottom": "1px solid var(--axis)"},
)


def kpi(label: str, value_id: str, sub_id: str | None = None) -> html.Div:
    children = [html.Div(label, className="kpi-label"), html.Div("-", id=value_id, className="kpi-value")]
    if sub_id:
        children.append(html.Div("", id=sub_id, className="kpi-sub"))
    return html.Div(children, className="kpi")


def control(label: str, component) -> html.Div:
    return html.Div([html.Label(label, className="control-label"), component], className="control")


def build_layout() -> html.Div:
    return html.Div(
        className="page",
        children=[
            dcc.Interval(id="refresh", interval=config.REFRESH_SECONDS * 1000, n_intervals=0),
            dcc.Store(id="color-slots", data={}),
            dcc.Download(id="report-download"),
            html.Header(
                className="header",
                children=[
                    html.Div([
                        html.H1("Battery Cycling Test Analytics"),
                        html.Div("Capacity fade, efficiency, voltage curves and test tracking", className="subtitle"),
                    ]),
                    html.Div(id="last-ingest", className="last-ingest"),
                ],
            ),
            html.Section(
                className="kpis",
                children=[
                    kpi("Cells", "kpi-cells"),
                    kpi("Tests", "kpi-tests", "kpi-running"),
                    kpi("Cycles recorded", "kpi-cycles"),
                    kpi("Lowest state of health", "kpi-soh", "kpi-soh-sub"),
                ],
            ),
            html.Section(
                className="filters",
                children=[
                    control("Chemistry", dcc.Dropdown(id="chem-filter", multi=True, placeholder="All chemistries")),
                    control("Tests (up to 8)", dcc.Dropdown(id="test-select", multi=True, placeholder="Select tests")),
                    control("Cycle range", dcc.RangeSlider(id="cycle-range", min=1, max=200, value=[1, 200], step=1,
                                                           tooltip={"placement": "bottom"}, marks=None)),
                ],
            ),
            html.Div(id="selection-note", className="note"),
            dcc.Tabs(
                id="tabs",
                value="fade",
                className="tabs",
                children=[
                    dcc.Tab(label="Capacity fade", value="fade", children=[
                        html.Div(className="tab-controls", children=[
                            dcc.RadioItems(id="fade-metric", inline=True, value="soh", options=[
                                {"label": "State of health (%)", "value": "soh"},
                                {"label": "Capacity (Ah)", "value": "ah"},
                            ]),
                            dcc.Checklist(id="fade-smooth", inline=True, value=["smooth"],
                                          options=[{"label": "Smoothed trend", "value": "smooth"}]),
                        ]),
                        dcc.Loading(dcc.Graph(id="fade-graph", config=GRAPH_CONFIG, className="graph")),
                    ]),
                    dcc.Tab(label="Efficiency", value="ce", children=[
                        dcc.Loading(dcc.Graph(id="ce-graph", config=GRAPH_CONFIG, className="graph")),
                    ]),
                    dcc.Tab(label="Voltage & dQ/dV", value="curves", children=[
                        html.Div(className="tab-controls", children=[
                            control("Test", dcc.Dropdown(id="focus-test", clearable=False)),
                            control("Cycles to overlay (up to 8)", dcc.Dropdown(id="focus-cycles", multi=True)),
                            dcc.RadioItems(id="focus-step", inline=True, value="discharge", options=[
                                {"label": "Discharge", "value": "discharge"},
                                {"label": "Charge", "value": "charge"},
                            ]),
                        ]),
                        html.Div(className="two-up", children=[
                            dcc.Loading(dcc.Graph(id="voltage-graph", config=GRAPH_CONFIG, className="graph")),
                            dcc.Loading(dcc.Graph(id="dqdv-graph", config=GRAPH_CONFIG, className="graph")),
                        ]),
                    ]),
                    dcc.Tab(label="Test tracker", value="tracker", children=[
                        html.H3("Tests"),
                        html.P("Click a row to see the material lots that went into that cell.", className="hint"),
                        dash_table.DataTable(
                            id="tracker-table",
                            columns=[
                                {"name": "Test", "id": "test_id"},
                                {"name": "Cell", "id": "cell_id"},
                                {"name": "Chemistry", "id": "chemistry"},
                                {"name": "Status", "id": "status"},
                                {"name": "Cycles", "id": "n_cycles", "type": "numeric"},
                                {"name": "Latest SOH (%)", "id": "last_soh_pct", "type": "numeric"},
                                {"name": f"Cycles to {config.EOL_SOH_PCT:.0f}% SOH", "id": "cycles_to_eol", "type": "numeric"},
                                {"name": "Mean CE (%)", "id": "mean_ce_pct", "type": "numeric"},
                                {"name": "QC flags", "id": "qc_issues", "type": "numeric"},
                                {"name": "Started", "id": "start_time"},
                            ],
                            sort_action="native",
                            filter_action="native",
                            page_size=15,
                            row_selectable="single",
                            **TABLE_STYLE,
                        ),
                        html.H3(id="materials-title", children="Build materials"),
                        dash_table.DataTable(
                            id="materials-table",
                            columns=[
                                {"name": "Role", "id": "role"},
                                {"name": "Lot", "id": "lot_code"},
                                {"name": "Supplier", "id": "supplier"},
                                {"name": "Received", "id": "received_date"},
                                {"name": "Cells using this lot", "id": "cells_using_lot", "type": "numeric"},
                            ],
                            **TABLE_STYLE,
                        ),
                        html.H3("Material lots ranked by latest state of health"),
                        dash_table.DataTable(
                            id="lots-table",
                            columns=[
                                {"name": "Material", "id": "material"},
                                {"name": "Lot", "id": "lot_code"},
                                {"name": "Cells", "id": "cells", "type": "numeric"},
                                {"name": "Avg latest SOH (%)", "id": "avg_last_soh_pct", "type": "numeric"},
                            ],
                            sort_action="native",
                            page_size=10,
                            **TABLE_STYLE,
                        ),
                    ]),
                    dcc.Tab(label="Reports", value="reports", children=[
                        html.P("Download a self-contained HTML report with summary, build materials and all charts.",
                               className="hint"),
                        html.Div(className="tab-controls", children=[
                            control("Test", dcc.Dropdown(id="report-test", clearable=False)),
                            html.Button("Download report", id="report-button", className="button", n_clicks=0),
                        ]),
                        html.Div(id="report-status", className="note"),
                    ]),
                ],
            ),
        ],
    )
