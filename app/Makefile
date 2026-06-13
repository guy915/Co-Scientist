.PHONY: install dev start test format lint typecheck

# Install all dependencies (pip workflow, installs co-scientist-engine).
install:
	pip install -e ".[dev]"

dev:
	python -m uvicorn app.main:app --reload --reload-dir app --host 0.0.0.0 --port 8008

start:
	python -m uvicorn app.main:app --host 0.0.0.0 --port 8008

test:
	pytest

format:
	yapf -ir app tests

lint:
	pylint --rcfile=../pylintrc app tests

typecheck:
	mypy .
