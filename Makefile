.PHONY: all run once test clean

# Define o interpretador Python a ser usado (procura em .venv primeiro)
PYTHON := .venv/bin/python

all: run

run:
	@echo "Starting the application in scheduled mode..."
	$(PYTHON) -m app.main

once:
	@echo "Running a single pipeline cycle..."
	$(PYTHON) -m app.main --once

test:
	@echo "Running tests..."
	$(PYTHON) -m pytest

clean:
	@echo "Cleaning up database and logs..."
	@rm -f data/app.db
	@rm -f logs/*.log