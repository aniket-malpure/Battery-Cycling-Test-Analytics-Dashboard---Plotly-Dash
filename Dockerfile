FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY battery_dash ./battery_dash
COPY scripts ./scripts

ENV BCD_DATA_DIR=/data \
    BCD_REPORT_DIR=/data/reports \
    BCD_LOG_DIR=/data/logs
VOLUME ["/data"]
EXPOSE 8050

# Seed sample data on first start if the database is empty, then serve.
CMD ["sh", "-c", "[ -f /data/battery.db ] || (python -m battery_dash.ingest.synthetic --out /data/raw/synthetic && python -m battery_dash.ingest.pipeline); gunicorn battery_dash.wsgi:server -b 0.0.0.0:8050 -w 2"]
