.PHONY: install dev start test format lint typecheck

# Install all dependencies (pip workflow, installs open-coscientist).
install:
	pip install -e ".[dev]"

dev:
	python -m uvicorn app.main:app --reload --reload-dir app --host 0.0.0.0 --port 8008

start:
	python -m uvicorn app.main:app --host 0.0.0.0 --port 8008

test:
	pytest

format:
	black . && ruff check --fix .

lint:
	ruff check .

typecheck:
	mypy .
