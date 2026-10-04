"""Generate realistic cycler CSV exports so the project runs fully offline.

Every file is clearly labeled synthetic. The model is physically motivated:
an open-circuit-voltage curve per chemistry, ohmic drop that grows with
resistance, CC-CV charging, capacity fade with a linear and a quadratic
term, formation-stage coulombic efficiency, and resistive heating. One
electrolyte lot is given a faster fade so the build & materials tracker has
something real to find.

Usage:
    python -m battery_dash.ingest.synthetic --out data/raw/synthetic
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .. import config

CHEMISTRIES = {
    "LFP": {
        "name": "LFP/Graphite (synthetic)",
        "cathode": "LiFePO4",
        "anode": "Graphite",
        "electrolyte": "1M LiPF6 in EC/DMC",
        "nominal_capacity_ah": 2.5,
        "nominal_voltage_v": 3.2,
        "_v_lo": 2.5, "_v_hi": 3.65, "_alpha": 0.12, "_r0": 0.030,
        "_fade_a": 1.6e-4, "_fade_b": 3.0e-7, "_ce": 0.9992,
    },
    "NMC": {
        "name": "NMC811/Graphite (synthetic)",
        "cathode": "LiNi0.8Mn0.1Co0.1O2",
        "anode": "Graphite",
        "electrolyte": "1M LiPF6 in EC/EMC",
        "nominal_capacity_ah": 3.0,
        "nominal_voltage_v": 3.6,
        "_v_lo": 2.8, "_v_hi": 4.2, "_alpha": 0.70, "_r0": 0.040,
        "_fade_a": 3.5e-4, "_fade_b": 9.0e-7, "_ce": 0.9985,
    },
    "ZN": {
        "name": "Aqueous Zn/MnO2 (synthetic)",
        "cathode": "MnO2",
        "anode": "Zinc",
        "electrolyte": "2M ZnSO4 aqueous",
        "nominal_capacity_ah": 1.5,
        "nominal_voltage_v": 1.35,
        "_v_lo": 0.9, "_v_hi": 1.85, "_alpha": 0.40, "_r0": 0.120,
        "_fade_a": 5.5e-4, "_fade_b": 1.8e-6, "_ce": 0.9940,
    },
}

# cell_id, chemistry key, n_cycles, status, electrolyte lot, fade multiplier
CELL_PLAN = [
    ("SYN-LFP-01", "LFP", 200, "complete", "EL-2405-A", 1.0),
    ("SYN-LFP-02", "LFP", 140, "running", "EL-2405-A", 1.0),
    ("SYN-NMC-01", "NMC", 200, "complete", "EL-2406-C", 1.0),
    ("SYN-NMC-02", "NMC", 200, "complete", "EL-2407-B", 1.8),  # suspect lot
    ("SYN-ZN-01", "ZN", 180, "complete", "EL-2406-Z", 1.0),
    ("SYN-ZN-02", "ZN", 120, "running", "EL-2407-B", 1.8),  # suspect lot
]

SUPPLIERS = {
    "cathode": "Synthetic Cathode Co.",
    "anode": "Synthetic Anode Co.",
    "electrolyte": "Synthetic Electrolytes LLC",
    "separator": "Synthetic Separators Inc.",
}


def ocv(soc: np.ndarray, p: dict) -> np.ndarray:
    """Open circuit voltage: sloped plateau with steep knees at both ends."""
    soc = np.clip(soc, 1e-4, 1 - 1e-4)
    span = p["_v_hi"] - p["_v_lo"]
    sig = 1.0 / (1.0 + np.exp(-10.0 * (soc - 0.5)))
    base = p["_alpha"] * soc + (1 - p["_alpha"]) * sig
    return (
        p["_v_lo"]
        + span * (0.12 + 0.78 * base)
        - 0.12 * span * np.exp(-soc / 0.04)
        + 0.10 * span * np.exp(-(1 - soc) / 0.04)
    )


def _discharge(q_cap, current, r, p, n_pts, amb, rng):
    q = np.linspace(0, q_cap, n_pts)
    t = q / current * 3600.0
    v = ocv(1 - q / q_cap, p) - current * r + rng.normal(0, 0.0015, n_pts)
    heat = 0.4 + 6.0 * current**2 * r
    temp = amb + heat * (t / t[-1]) ** 0.8 + rng.normal(0, 0.05, n_pts)
    return t, np.maximum(v, p["_v_lo"] - 0.05), -np.full(n_pts, current), temp


def _charge(q_cap, current, r, p, n_pts, amb, rng):
    q = np.linspace(0, q_cap, n_pts)
    cv_start = 0.85 * q_cap
    i = np.where(
        q < cv_start,
        current,
        current * np.exp(-4.0 * (q - cv_start) / (q_cap - cv_start)),
    )
    i = np.maximum(i, 0.05 * current)
    dt = np.diff(q) / ((i[1:] + i[:-1]) / 2) * 3600.0
    t = np.concatenate([[0.0], np.cumsum(dt)])
    v = np.minimum(ocv(q / q_cap, p) + i * r, p["_v_hi"]) + rng.normal(0, 0.0015, n_pts)
    temp = amb + (0.3 + 4.0 * current**2 * r) * np.sin(np.pi * q / q_cap) + rng.normal(0, 0.05, n_pts)
    return t, v, i, temp


def generate_cell(cell_id, chem_key, n_cycles, status, el_lot, fade_mult, out_dir, rng, n_pts=90):
    p = CHEMISTRIES[chem_key]
    q0 = p["nominal_capacity_ah"] * (1 + rng.normal(0, 0.01))
    c_rate = 0.5 * p["nominal_capacity_ah"]
    amb = 25.0
    a, b = p["_fade_a"] * fade_mult, p["_fade_b"] * fade_mult

    rows, clock = [], 0.0
    for n in range(1, n_cycles + 1):
        fade = 1 - a * n - b * n**2
        # Small recoveries after long rests are typical in real cycling data.
        recovery = 0.004 if n % 50 == 1 and n > 1 else 0.0
        q_dis = q0 * (fade + recovery) * (1 + rng.normal(0, 0.002))
        ce = min(p["_ce"] - 0.02 * np.exp(-n / 4) + rng.normal(0, 0.0006), 0.9999)
        r = p["_r0"] * (1 + 0.0035 * n)

        for step, (t, v, i, temp) in (
            ("charge", _charge(q_dis / ce, c_rate, r, p, n_pts, amb, rng)),
            ("discharge", _discharge(q_dis, c_rate, r, p, n_pts, amb, rng)),
        ):
            rows.append(
                pd.DataFrame(
                    {
                        "cycle_index": n,
                        "step_type": step,
                        "test_time_s": clock + t,
                        "voltage_v": v,
                        "current_a": i,
                        "temperature_c": temp,
                    }
                )
            )
            clock += t[-1] + 600.0  # 10 minute rest between steps

    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{cell_id}.csv"
    pd.concat(rows, ignore_index=True).to_csv(csv_path, index=False, float_format="%.6g")

    build_date = datetime(2026, 5, 4) + timedelta(days=int(rng.integers(0, 30)))
    lots = {
        "cathode": f"CA-{chem_key}-24{int(rng.integers(10, 99))}",
        "anode": f"AN-{chem_key}-24{int(rng.integers(10, 99))}",
        "electrolyte": el_lot,
        "separator": "SP-2404-01",
    }
    meta = {
        "test_id": f"T-{cell_id}",
        "cell_id": cell_id,
        "test_name": f"{p['name']} 0.5C cycle life",
        "protocol": "CC-CV charge 0.5C, CC discharge 0.5C, 10 min rests, 25C",
        "ambient_temp_c": amb,
        "start_time": (build_date + timedelta(days=7)).isoformat(),
        "status": status,
        "chemistry": {k: v for k, v in p.items() if not k.startswith("_")},
        "cell": {
            "form_factor": "Pouch" if chem_key != "ZN" else "Coin (CR2032)",
            "build_date": build_date.date().isoformat(),
            "source": "synthetic",
            "notes": "Generated by battery_dash.ingest.synthetic",
        },
        "materials": [
            {
                "role": role,
                "material_type": role,
                "supplier": SUPPLIERS[role],
                "lot_code": code,
                "received_date": (build_date - timedelta(days=14)).date().isoformat(),
            }
            for role, code in lots.items()
        ],
    }
    csv_path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2))
    return csv_path


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=config.RAW_DIR / "synthetic")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--points", type=int, default=90, help="samples per step")
    args = ap.parse_args(argv)

    rng = np.random.default_rng(args.seed)
    for plan in CELL_PLAN:
        path = generate_cell(*plan, out_dir=args.out, rng=rng, n_pts=args.points)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
