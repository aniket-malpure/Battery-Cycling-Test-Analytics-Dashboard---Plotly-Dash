"""Per-test HTML reports: a self-contained page you can email or archive.

Usage:
    python -m battery_dash.reports --test-id T-SYN-NMC-02
    python -m battery_dash.reports --all
"""

from __future__ import annotations

import argparse
import html
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import config, db, figures, queries
from .ingest.transform import cycles_to_eol


def _table(df: pd.DataFrame) -> str:
    return df.to_html(index=False, border=0, classes="tbl", na_rep="n/a", float_format=lambda x: f"{x:,.4g}")


def build_report_html(con, test_id: str) -> str:
    info = queries.test_info(con, test_id)
    if info is None:
        raise KeyError(f"unknown test_id {test_id}")
    cyc = queries.cycles(con, [test_id])
    colors = figures.default_colors([test_id])
    idx = queries.cycle_indices(con, test_id)
    picks = figures.evenly_spaced(idx, 6)
    ts = queries.timeseries(con, test_id, picks, "discharge")

    figs = [
        figures.capacity_fade(cyc, colors, "soh", smooth=True),
        figures.coulombic_efficiency(cyc, colors),
        figures.voltage_curves(ts, test_id, "discharge"),
        figures.dqdv_curves(ts, test_id, "discharge"),
    ]
    fig_html = "".join(
        f.to_html(full_html=False, include_plotlyjs="cdn" if i == 0 else False, config={"displaylogo": False})
        for i, f in enumerate(figs)
    )

    eol = cycles_to_eol(cyc) if not cyc.empty else None
    last = cyc.iloc[-1] if not cyc.empty else None
    summary = pd.DataFrame(
        [
            ("Cell", info["cell_id"]),
            ("Chemistry", info["chemistry"]),
            ("Cathode / anode / electrolyte", f"{info['cathode']} / {info['anode']} / {info['electrolyte']}"),
            ("Form factor", info["form_factor"]),
            ("Protocol", info["protocol"]),
            ("Status", info["status"]),
            ("Test window", f"{info['start_time']} to {info['end_time']}"),
            ("Cycles completed", len(cyc)),
            ("Initial discharge capacity (Ah)", f"{cyc['discharge_ah'].iloc[0]:.4f}" if last is not None else "n/a"),
            ("Latest smoothed state of health", f"{last['soh_smooth_pct']:.1f}%" if last is not None else "n/a"),
            (f"Cycles to {config.EOL_SOH_PCT:.0f}% SOH", eol if eol else "not reached"),
            ("Mean coulombic efficiency", f"{cyc['coulombic_eff'].mean() * 100:.2f}%" if last is not None else "n/a"),
            ("Max cell temperature (C)", f"{cyc['max_temp_c'].max():.1f}" if last is not None else "n/a"),
            ("Cycles with QC flags", int((cyc["qc_flag"] != "ok").sum()) if last is not None else 0),
        ],
        columns=["Field", "Value"],
    )
    mats = queries.materials(con, info["cell_id"])

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Test report {html.escape(test_id)}</title>
<style>
 body {{ font-family: {figures.FONT}; color: {figures.TEXT_1}; background: {figures.SURFACE}; margin: 0 auto; max-width: 1100px; padding: 24px 16px; }}
 h1 {{ font-size: 24px; margin: 0 0 4px; }} h2 {{ font-size: 17px; margin: 32px 0 8px; }}
 .muted {{ color: {figures.TEXT_2}; font-size: 13px; }}
 .tbl {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
 .tbl th, .tbl td {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid {figures.GRID}; }}
 .tbl th {{ color: {figures.TEXT_2}; font-weight: 600; }}
</style></head><body>
<h1>Cycling test report: {html.escape(test_id)}</h1>
<div class="muted">Generated {datetime.now():%Y-%m-%d %H:%M} by battery_dash. Source: {html.escape(str(info['source_file']))}</div>
<h2>Summary</h2>{_table(summary)}
<h2>Build materials</h2>{_table(mats) if not mats.empty else '<p class="muted">No material lots recorded for this cell.</p>'}
<h2>Charts</h2>{fig_html}
</body></html>"""


def write_report(con, test_id: str, out_dir: Path = config.REPORT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{test_id}_report.html"
    path.write_text(build_report_html(con, test_id), encoding="utf-8")
    return path


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--test-id")
    group.add_argument("--all", action="store_true")
    ap.add_argument("--db", type=Path, default=config.DB_PATH)
    ap.add_argument("--out", type=Path, default=config.REPORT_DIR)
    args = ap.parse_args(argv)

    con = db.connect(args.db)
    ids = queries.test_summary(con)["test_id"].tolist() if args.all else [args.test_id]
    for test_id in ids:
        t0 = time.perf_counter()
        path = write_report(con, test_id, args.out)
        print(f"{path}  ({time.perf_counter() - t0:.2f}s)")


if __name__ == "__main__":
    main()
