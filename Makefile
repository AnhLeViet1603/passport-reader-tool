.PHONY: install build test run

install:
	uv sync

run:
	uv run passport-reader-tool

test:
	uv run pytest

build:
	powershell -ExecutionPolicy Bypass -File scripts/build.ps1
