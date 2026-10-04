PY ?= .venv/bin/python

.PHONY: venv install sample-data nasa-data ingest app serve report test clean demo

venv:
	python3 -m venv .venv

install: venv
	$(PY) -m pip install -r requirements.txt

sample-data:
	$(PY) -m battery_dash.ingest.synthetic

nasa-data:
	$(PY) -m battery_dash.ingest.download_nasa

ingest:
	$(PY) -m battery_dash.ingest.pipeline

app:
	$(PY) -m battery_dash.app --debug

serve:
	.venv/bin/gunicorn "battery_dash.wsgi:server" -b 0.0.0.0:8050 -w 2

report:
	$(PY) -m battery_dash.reports --all

test:
	$(PY) -m pytest -q

demo: sample-data ingest report app

clean:
	rm -rf data/battery.db* data/.ingest.lock reports/*.html logs/*.log
