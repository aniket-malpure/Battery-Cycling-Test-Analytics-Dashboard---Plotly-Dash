"""Dash application factory and dev-server entry point.

Development:
    python -m battery_dash.app
Production:
    gunicorn "battery_dash.wsgi:server" -b 0.0.0.0:8050 -w 2
"""

from __future__ import annotations

import argparse
from pathlib import Path

from dash import Dash

from .. import config, db
from .callbacks import register_callbacks
from .layout import build_layout


def create_app(db_path: str | Path | None = None) -> Dash:
    db_path = Path(db_path or config.DB_PATH)
    with db.connect(db_path) as con:  # make sure the schema exists before the first request
        db.init_db(con)

    app = Dash(
        __name__,
        title="Battery Cycling Test Analytics",
        assets_folder=str(Path(__file__).with_name("assets")),
        suppress_callback_exceptions=False,
    )
    app.layout = build_layout
    register_callbacks(app, db_path)
    return app


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Run the dashboard dev server")
    ap.add_argument("--host", default=config.APP_HOST)
    ap.add_argument("--port", type=int, default=config.APP_PORT)
    ap.add_argument("--db", type=Path, default=config.DB_PATH)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args(argv)
    create_app(args.db).run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
