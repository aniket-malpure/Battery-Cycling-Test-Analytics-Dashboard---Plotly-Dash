"""WSGI entry point: gunicorn "battery_dash.wsgi:server"."""

from .app import create_app

app = create_app()
server = app.server
