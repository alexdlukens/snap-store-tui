UV := uv
VENV := .venv
PY := $(VENV)/bin/python

.PHONY: install run dev test lint fmt check build build-snap lock clean

install:
	$(UV) sync --locked

run:
	$(UV) run --locked store-tui

# textual-dev re-executes with argv[0]="python", which breaks venv discovery under
# uv-created venvs; -c delegates to execvpe with the real interpreter path.
dev:
	$(UV) run --locked textual run --dev -c "$(PY) -m store_tui"

test:
	$(UV) run --locked pytest

lint:
	$(UV) run --locked ruff check .

fmt:
	$(UV) run --locked ruff format .

check: lint
	$(UV) run --locked ruff format --check .
	$(UV) run --locked pytest

build:
	$(UV) build

build-snap:
	snapcraft pack

lock:
	$(UV) lock

clean:
	rm -rf dist build .ruff_cache .pytest_cache .coverage htmlcov
	find . -path ./.venv -prune -o -name '__pycache__' -type d -exec rm -rf {} +
	find . -not -path './.venv/*' -not -path './.git/*' -name '*.pyc' -type f -delete
