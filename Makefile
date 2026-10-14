PYTHON ?= .venv/bin/python
FORECASTER ?= m0
CARDS ?= 2060
ARGS ?=

.PHONY: setup test backtest eval-practice admissibility calibration generate reference-smoke docker-smoke
setup:
	bash scripts/setup.sh
test:
	$(PYTHON) -m pytest
backtest eval-practice admissibility calibration generate:
	$(PYTHON) -m t2eval.cli $@ --forecaster $(FORECASTER) --cards $(CARDS) $(ARGS)
reference-smoke:
	$(PYTHON) -m qfbench2_track_forecasting.cli --panels vendor/track2/units/t2-EXAMPLE-ust-curve-1m/panels --text vendor/track2/units/t2-EXAMPLE-ust-curve-1m/text --asof 2024-06-28 --out .context/reference-exemplar/forecast.parquet
	$(PYTHON) vendor/track2/scoring/scoring.py score --card vendor/track2/units/t2-EXAMPLE-ust-curve-1m/card.toml --forecast .context/reference-exemplar/forecast.parquet
docker-smoke:
	$(PYTHON) scripts/docker_smoke.py --forecaster $(FORECASTER)
