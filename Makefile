.PHONY: run

run:
	. .venv/bin/activate && python3 store_tui/main.py

.PHONY: dev
dev:
	. .venv/bin/activate && textual run store_tui/main.py --dev
