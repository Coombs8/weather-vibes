.PHONY: install test smoke download conform analytics run validate query

DATA_DIR ?= data
PYTHON := .venv/bin/python
CLI := .venv/bin/weather-vibes

install:
	python3 -m venv .venv
	.venv/bin/pip install -e '.[dev]'

test:
	.venv/bin/pytest

smoke:
	$(CLI) --data-dir $(DATA_DIR) run --limit 2 --workers 2

download:
	$(CLI) --data-dir $(DATA_DIR) download

conform:
	$(CLI) --data-dir $(DATA_DIR) build-conformed

analytics:
	$(CLI) --data-dir $(DATA_DIR) build-analytics

run:
	$(CLI) --data-dir $(DATA_DIR) run

validate:
	$(CLI) --data-dir $(DATA_DIR) validate

query:
	$(CLI) --data-dir $(DATA_DIR) query

