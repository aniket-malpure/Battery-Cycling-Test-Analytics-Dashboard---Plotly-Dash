import numpy as np
import pytest
from scipy.io import savemat


def _nasa_step(kind, n_pts, start_vec, cap=None):
    t = np.linspace(0, 3600 if kind == "discharge" else 9000, n_pts)
    if kind == "charge":
        v = np.linspace(3.5, 4.2, n_pts)
        i = np.full(n_pts, 1.5)
        i[int(n_pts * 0.8):] = np.linspace(1.5, 0.02, n_pts - int(n_pts * 0.8))
    else:
        v = np.linspace(4.1, 2.8, n_pts)
        i = np.full(n_pts, -2.0)
    data = {
        "Voltage_measured": v,
        "Current_measured": i,
        "Temperature_measured": np.full(n_pts, 25.0),
        "Time": t,
    }
    if cap is not None:
        data["Capacity"] = cap
    return (kind, 24, np.array(start_vec, dtype=float), data)


@pytest.fixture
def nasa_mat(tmp_path):
    """A small .mat file laid out exactly like the NASA PCoE B00xx files."""
    entries = []
    for k in range(5):
        day = 2 + k
        entries.append(_nasa_step("charge", 60, [2008, 4, day, 9, 0, 0.0]))
        entries.append(_nasa_step("discharge", 60, [2008, 4, day, 12, 0, 0.0], cap=1.85 - 0.01 * k))
        entries.append(("impedance", 24, np.array([2008, 4, day, 13, 0, 0.0]), {"Rct": 0.1}))
    dtype = [("type", "O"), ("ambient_temperature", "O"), ("time", "O"), ("data", "O")]
    cyc = np.empty((1, len(entries)), dtype=dtype)
    for j, e in enumerate(entries):
        cyc[0, j] = e
    path = tmp_path / "B0005.mat"
    savemat(path, {"B0005": {"cycle": cyc}})
    return path


@pytest.fixture
def synthetic_dir(tmp_path):
    from battery_dash.ingest.synthetic import generate_cell

    out = tmp_path / "raw"
    rng = np.random.default_rng(1)
    generate_cell("SYN-T-01", "NMC", 30, "complete", "EL-X", 1.0, out, rng, n_pts=40)
    generate_cell("SYN-T-02", "ZN", 20, "running", "EL-Y", 1.8, out, rng, n_pts=40)
    return out
