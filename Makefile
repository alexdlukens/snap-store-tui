VENV := .venv
PY := $(VENV)/bin/python
RUFF := $(VENV)/bin/ruff
PYTEST := $(VENV)/bin/pytest
TEXTUAL := $(VENV)/bin/textual

.PHONY: install run dev test lint fmt check build-snap clean

install:
	poetry install

run:
	$(PY) -m store_tui

# textual-dev re-executes with argv[0]="python", which breaks venv discovery under
# uv-created venvs; -c delegates to execvpe with the real interpreter path.
dev:
	$(TEXTUAL) run --dev -c "$(PY) -m store_tui"

test:
	$(PYTEST)

lint:
	$(RUFF) check .

fmt:
	$(RUFF) format .

check: lint
	$(RUFF) format --check .
	$(PYTEST)

build-snap:
	snapcraft pack

clean:
	rm -rf dist build .ruff_cache .pytest_cache .coverage htmlcov
	find . -path ./.venv -prune -o -name '__pycache__' -type d -exec rm -rf {} +
	find . -not -path './.venv/*' -not -path './.git/*' -name '*.pyc' -type f -delete
