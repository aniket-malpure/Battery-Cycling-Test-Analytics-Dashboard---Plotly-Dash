"""Plotly figure builders shared by the dashboard and HTML reports.

Color rules:
  * Tests are identities, so they get categorical colors in a fixed slot
    order. The dashboard keeps a test's slot for as long as it stays
    selected, so filtering never repaints the survivors.
  * Cycle number is a magnitude, so overlays of several cycles from one test
    use a single-hue ramp, light (early) to dark (late).
  * Every chart has one y axis.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from . import config
from .ingest.transform import incremental_capacity

# Validated categorical palette (light surface), assigned in this order.
CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
MAX_SERIES = len(CATEGORICAL)

SURFACE = "#fcfcfb"
TEXT_1 = "#0b0b0b"
TEXT_2 = "#52514e"
TEXT_3 = "#8a8983"
GRID = "#ecebe7"
AXIS = "#cfcec8"
FONT = "Inter, -apple-system, Segoe UI, Roboto, sans-serif"

SEQ_LIGHT, SEQ_DARK = "#a9c8ee", "#0e3a70"


def sequential(n: int) -> list[str]:
    """n steps of one blue hue from light to dark."""
    if n <= 1:
        return [CATEGORICAL[0]]
    a = np.array([int(SEQ_LIGHT[i:i + 2], 16) for i in (1, 3, 5)])
    b = np.array([int(SEQ_DARK[i:i + 2], 16) for i in (1, 3, 5)])
    return ["#%02x%02x%02x" % tuple((a + (b - a) * k / (n - 1)).round().astype(int)) for k in range(n)]


def default_colors(test_ids: list[str]) -> dict[str, str]:
    return {t: CATEGORICAL[i % MAX_SERIES] for i, t in enumerate(test_ids[:MAX_SERIES])}


def _style(fig: go.Figure, title: str, x_title: str, y_title: str, n_series: int) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(family=FONT, color=TEXT_2, size=13),
        title=dict(text=title, font=dict(color=TEXT_1, size=16), x=0.01, xanchor="left"),
        margin=dict(l=64, r=24, t=56, b=110 if n_series >= 2 else 56),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="white", font=dict(color=TEXT_1, family=FONT)),
        showlegend=n_series >= 2,
        # Legend sits under the x axis so it can wrap without hitting the title.
        legend=dict(orientation="h", x=0, xanchor="left", y=-0.2, yanchor="top", font=dict(color=TEXT_2), title=None),
    )
    axis = dict(gridcolor=GRID, zeroline=False, linecolor=AXIS, showline=True, ticks="outside",
                tickcolor=AXIS, title_font=dict(color=TEXT_2))
    fig.update_xaxes(title=x_title, **axis)
    fig.update_yaxes(title=y_title, **axis)
    return fig


def empty_figure(message: str = "No data for this selection") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=message, showarrow=False, font=dict(color=TEXT_3, size=15), x=0.5, y=0.5,
                       xref="paper", yref="paper")
    fig.update_layout(paper_bgcolor=SURFACE, plot_bgcolor=SURFACE, xaxis=dict(visible=False),
                      yaxis=dict(visible=False), margin=dict(l=20, r=20, t=20, b=20))
    return fig


# ---------------------------------------------------------------- per-cycle trends
def capacity_fade(cyc: pd.DataFrame, colors: dict[str, str], metric: str = "soh", smooth: bool = True) -> go.Figure:
    """Discharge capacity (Ah) or state of health (%) against cycle number."""
    if cyc.empty:
        return empty_figure()
    raw_col, smooth_col, y_title, fmt = (
        ("soh_pct", "soh_smooth_pct", "State of health (%)", ".1f")
        if metric == "soh"
        else ("discharge_ah", "discharge_ah_smooth", "Discharge capacity (Ah)", ".3f")
    )
    fig = go.Figure()
    tests = [t for t in colors if t in set(cyc["test_id"])]
    for t in tests:
        d = cyc[cyc["test_id"] == t]
        color = colors[t]
        fig.add_trace(go.Scatter(
            x=d["cycle_index"], y=d[raw_col], name=t, legendgroup=t, mode="lines",
            line=dict(color=color, width=1 if smooth else 2), opacity=0.35 if smooth else 1,
            showlegend=not smooth, hovertemplate=f"%{{y:{fmt}}}" + ("<extra>raw</extra>" if smooth else f"<extra>{t}</extra>"),
            hoverinfo="skip" if smooth else None,
        ))
        if smooth:
            fig.add_trace(go.Scatter(
                x=d["cycle_index"], y=d[smooth_col], name=t, legendgroup=t, mode="lines",
                line=dict(color=color, width=2), hovertemplate=f"%{{y:{fmt}}}<extra>{t}</extra>",
            ))
    if metric == "soh":
        fig.add_hline(y=config.EOL_SOH_PCT, line=dict(color=TEXT_3, width=1, dash="dash"),
                      annotation=dict(text=f"{config.EOL_SOH_PCT:.0f}% end of life", font=dict(color=TEXT_2, size=12)),
                      annotation_position="bottom right")
    title = "Capacity fade" + (" (Savitzky-Golay smoothed)" if smooth else "")
    return _style(fig, title, "Cycle", y_title, len(tests))


def coulombic_efficiency(cyc: pd.DataFrame, colors: dict[str, str]) -> go.Figure:
    if cyc.empty or cyc["coulombic_eff"].notna().sum() == 0:
        return empty_figure()
    fig = go.Figure()
    tests = [t for t in colors if t in set(cyc["test_id"])]
    for t in tests:
        d = cyc[cyc["test_id"] == t]
        fig.add_trace(go.Scatter(
            x=d["cycle_index"], y=d["coulombic_eff"] * 100, name=t, mode="lines",
            line=dict(color=colors[t], width=2), connectgaps=False,
            hovertemplate="%{y:.2f}%<extra>" + t + "</extra>",
        ))
    return _style(fig, "Coulombic efficiency (discharge Ah / charge Ah)", "Cycle", "Coulombic efficiency (%)", len(tests))


def energy_and_temperature_table(cyc: pd.DataFrame) -> pd.DataFrame:
    """Compact per-test stats used in the tracker and in reports."""
    if cyc.empty:
        return pd.DataFrame()
    return (
        cyc.groupby("test_id")
        .agg(cycles=("cycle_index", "max"), mean_energy_eff_pct=("energy_eff", lambda s: round(s.mean() * 100, 2)),
             max_temp_c=("max_temp_c", "max"), qc_issues=("qc_flag", lambda s: int((s != "ok").sum())))
        .reset_index()
    )


# ---------------------------------------------------------------- per-cycle curves
def voltage_curves(ts: pd.DataFrame, test_id: str, step: str, smooth: bool = True) -> go.Figure:
    """Voltage against step capacity for several cycles of one test."""
    if ts.empty:
        return empty_figure("Pick a test and at least one cycle")
    cycles = sorted(ts["cycle_index"].unique())
    ramp = sequential(len(cycles))
    y = "voltage_smooth_v" if smooth else "voltage_v"
    fig = go.Figure()
    for c, color in zip(cycles, ramp):
        d = ts[ts["cycle_index"] == c]
        fig.add_trace(go.Scatter(
            x=d["capacity_ah"], y=d[y], name=f"Cycle {c}", mode="lines", line=dict(color=color, width=2),
            hovertemplate="%{x:.3f} Ah, %{y:.3f} V<extra>Cycle " + str(c) + "</extra>",
        ))
    fig = _style(fig, f"{step.title()} voltage curves, {test_id}", f"{step.title()} capacity (Ah)", "Voltage (V)", len(cycles))
    fig.update_layout(hovermode="closest")
    return fig


def dqdv_curves(ts: pd.DataFrame, test_id: str, step: str) -> go.Figure:
    """Incremental capacity (dQ/dV) for several cycles of one test."""
    if ts.empty:
        return empty_figure("Pick a test and at least one cycle")
    cycles = sorted(ts["cycle_index"].unique())
    ramp = sequential(len(cycles))
    fig = go.Figure()
    for c, color in zip(cycles, ramp):
        d = ts[ts["cycle_index"] == c]
        v, dq = incremental_capacity(d["capacity_ah"], d["voltage_smooth_v"])
        if v.size == 0:
            continue
        fig.add_trace(go.Scatter(
            x=v, y=dq, name=f"Cycle {c}", mode="lines", line=dict(color=color, width=2),
            hovertemplate="%{x:.3f} V, %{y:.2f} Ah/V<extra>Cycle " + str(c) + "</extra>",
        ))
    if not fig.data:
        return empty_figure("Not enough points to compute dQ/dV")
    fig = _style(fig, f"Incremental capacity (dQ/dV), {step}, {test_id}", "Voltage (V)", "dQ/dV (Ah/V)", len(fig.data))
    fig.update_layout(hovermode="closest")
    return fig


def evenly_spaced(values: list[int], k: int = 6) -> list[int]:
    if len(values) <= k:
        return list(values)
    idx = np.unique(np.linspace(0, len(values) - 1, k).round().astype(int))
    return [values[i] for i in idx]
