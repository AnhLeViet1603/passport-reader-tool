.PHONY: install build test run

install:
	uv sync

run:
	uv run passport-reader-tool

test:
	uv run pytest

build:
	uv run pyinstaller --noconfirm --windowed --name PassportReaderTool --collect-all passporteye --collect-all PySide6 src/passport_reader_tool/app.py
