"""Download the NASA PCoE battery aging dataset and extract the B0005-B0018 cells.

The archive contains nested zip files; this walks them and pulls out only the
.mat files listed in config.NASA_CELLS.

Usage:
    python -m battery_dash.ingest.download_nasa
    python -m battery_dash.ingest.download_nasa --zip "5. Battery Data Set.zip"   # already downloaded

If the URL ever moves, download the "Battery Data Set" from the NASA Open
Data Portal / PCoE data repository manually and pass it with --zip.
"""

from __future__ import annotations

import argparse
import io
import shutil
import urllib.request
import zipfile
from pathlib import Path

from .. import config


def _extract(zf: zipfile.ZipFile, wanted: set[str], out_dir: Path, found: set[str]) -> None:
    for name in zf.namelist():
        base = Path(name).name
        if base.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(zf.read(name))) as inner:
                _extract(inner, wanted, out_dir, found)
        elif base.lower().endswith(".mat") and Path(base).stem in wanted and base not in found:
            (out_dir / base).write_bytes(zf.read(name))
            found.add(base)
            print(f"extracted {base}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=config.NASA_URL)
    ap.add_argument("--zip", type=Path, help="use a local copy of the archive instead of downloading")
    ap.add_argument("--out", type=Path, default=config.RAW_DIR / "nasa")
    ap.add_argument("--cells", nargs="+", default=list(config.NASA_CELLS))
    args = ap.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    archive = args.zip
    if archive is None:
        archive = args.out / "nasa_battery_dataset.zip"
        if not archive.exists():
            print(f"downloading {args.url}")
            with urllib.request.urlopen(args.url, timeout=120) as resp, open(archive, "wb") as fh:
                shutil.copyfileobj(resp, fh)

    found: set[str] = set()
    with zipfile.ZipFile(archive) as zf:
        _extract(zf, set(args.cells), args.out, found)

    missing = set(args.cells) - {Path(f).stem for f in found}
    if missing:
        raise SystemExit(f"cells not found in archive: {sorted(missing)}")
    print(f"done: {len(found)} files in {args.out}")


if __name__ == "__main__":
    main()
