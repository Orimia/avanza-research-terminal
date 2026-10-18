.PHONY: install dev lint test run engine letter

install:          ## Install runtime dependencies
	pip install -r requirements.txt

dev:              ## Install runtime + dev dependencies (pytest, ruff)
	pip install -r requirements.txt ruff

lint:             ## Static checks (ruff)
	ruff check src tests

test:             ## Run the offline test suite
	ALLOW_NETWORK=false pytest -q

run:              ## Launch the Streamlit dashboard
	streamlit run src/dashboard/app.py

engine:           ## Dry-run the always-on engine (prints what it would send)
	python -m src.engine.scheduler dry-run

letter:           ## Preview the weekly plain-language letter (dry run)
	ALLOW_NETWORK=true python -m src.engine.scheduler letter-dry
