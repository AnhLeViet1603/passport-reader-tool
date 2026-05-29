from __future__ import annotations

import sys
from shutil import which
from datetime import date, datetime
from multiprocessing import freeze_support
from pathlib import Path

from openpyxl import Workbook
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from passport_reader_tool.batch_processor import BatchProgress, process_folder
from passport_reader_tool.excel_service import EXCEL_HEADERS, ExcelWorkbookService
from passport_reader_tool.models import PassportRecord


class BatchWorker(QThread):
    progress = Signal(object, object)
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, folder: str, start_row_number: int) -> None:
        super().__init__()
        self.folder = folder
        self.start_row_number = start_row_number

    def run(self) -> None:
        try:
            records = process_folder(self.folder, self.start_row_number, progress_callback=self.progress.emit)
            self.finished.emit(records)
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Passport Reader Tool")
        self.resize(1100, 720)

        self.excel = ExcelWorkbookService()
        self.workbook: Workbook | None = None
        self.current_path: Path | None = None
        self.records: list[PassportRecord] = []
        self.dirty = False
        self.worker: BatchWorker | None = None

        self._build_ui()
        self._update_actions()
        self._warn_if_tesseract_missing()

    def _build_ui(self) -> None:
        toolbar = QToolBar("Main")
        self.addToolBar(toolbar)

        file_button = QToolButton()
        file_button.setText("File")
        file_button.setPopupMode(QToolButton.InstantPopup)
        file_menu = QMenu(file_button)

        self.new_action = QAction("New", self)
        self.open_action = QAction("Open", self)
        self.save_action = QAction("Save", self)
        self.save_as_action = QAction("Save As", self)
        file_menu.addActions([self.new_action, self.open_action, self.save_action, self.save_as_action])
        file_button.setMenu(file_menu)
        toolbar.addWidget(file_button)

        self.import_button = QPushButton("Import Folder")
        toolbar.addWidget(self.import_button)

        self.path_label = QLabel("No workbook")
        toolbar.addWidget(self.path_label)

        self.table = QTableWidget(0, len(EXCEL_HEADERS))
        self.table.setHorizontalHeaderLabels(EXCEL_HEADERS)
        self.table.itemChanged.connect(self._mark_dirty)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        self.log = QListWidget()
        self.log.setMaximumHeight(150)

        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.addWidget(self.progress)
        bottom_layout.addWidget(QLabel("Log"))
        bottom_layout.addWidget(self.log)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.table)
        splitter.addWidget(bottom)

        container = QWidget()
        layout = QVBoxLayout(container)
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Workbook data"))
        top_row.addStretch()
        layout.addLayout(top_row)
        layout.addWidget(splitter)
        self.setCentralWidget(container)

        self.new_action.triggered.connect(self.new_workbook)
        self.open_action.triggered.connect(self.open_workbook)
        self.save_action.triggered.connect(self.save_workbook)
        self.save_as_action.triggered.connect(self.save_as_workbook)
        self.import_button.clicked.connect(self.import_folder)

    def new_workbook(self) -> None:
        if not self._confirm_discard_unsaved():
            return
        path, _ = QFileDialog.getSaveFileName(self, "Create Excel Workbook", "", "Excel Workbook (*.xlsx)")
        if not path:
            return
        self.workbook = self.excel.new_workbook()
        self.current_path = self._xlsx_path(path)
        self.records = []
        self._render_records()
        self._save_to_current_path()
        self.dirty = False
        self._update_actions()

    def open_workbook(self) -> None:
        if not self._confirm_discard_unsaved():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open Excel Workbook", "", "Excel Workbook (*.xlsx)")
        if not path:
            return
        self.workbook, self.records = self.excel.load(path)
        self.current_path = Path(path)
        self._render_records()
        self.dirty = False
        self._update_actions()
        self.log.addItem(f"Opened: {path}")

    def save_workbook(self) -> None:
        if not self.current_path:
            self.save_as_workbook()
            return
        self._save_to_current_path()
        self.dirty = False
        self._update_actions()

    def save_as_workbook(self) -> None:
        if self.workbook is None:
            self.workbook = self.excel.new_workbook()
        path, _ = QFileDialog.getSaveFileName(self, "Save Excel Workbook As", "", "Excel Workbook (*.xlsx)")
        if not path:
            return
        self.current_path = self._xlsx_path(path)
        self._save_to_current_path()
        self.dirty = False
        self._update_actions()

    def import_folder(self) -> None:
        if self.workbook is None:
            QMessageBox.information(self, "Workbook required", "Create or open an Excel workbook first.")
            return
        folder = QFileDialog.getExistingDirectory(self, "Select Image Folder")
        if not folder:
            return
        self.import_button.setEnabled(False)
        self.progress.setValue(0)
        self.log.addItem(f"Processing folder: {folder}")
        self.worker = BatchWorker(folder, len(self.records) + 1)
        self.worker.progress.connect(self._on_batch_progress)
        self.worker.finished.connect(self._on_batch_finished)
        self.worker.failed.connect(self._on_batch_failed)
        self.worker.start()

    def _on_batch_progress(self, progress: BatchProgress, record: PassportRecord) -> None:
        percent = int((progress.completed / progress.total) * 100) if progress.total else 0
        self.progress.setValue(percent)
        status = "ERROR" if record.is_error else "OK"
        self.log.addItem(f"[{status}] {progress.completed}/{progress.total}: {Path(progress.current_file).name}")

    def _on_batch_finished(self, records: list[PassportRecord]) -> None:
        self.records.extend(records)
        self._render_records()
        self.import_button.setEnabled(True)
        self.dirty = True
        self._update_actions()
        errors = sum(1 for record in records if record.is_error)
        self.log.addItem(f"Batch completed: {len(records)} files, {errors} errors")

    def _on_batch_failed(self, message: str) -> None:
        self.import_button.setEnabled(True)
        QMessageBox.critical(self, "Batch failed", message)

    def _render_records(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for record in self.records:
            self._append_table_record(record)
        self.table.blockSignals(False)

    def _append_table_record(self, record: PassportRecord) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = [
            record.row_number,
            record.full_name,
            self._format_date(record.date_of_birth),
            record.sex,
            record.passport_number,
            self._format_date(record.expiry_date),
            self._format_date(record.added_date),
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value or ""))
            if column == 0:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            if record.is_error:
                item.setBackground(QColor("#ffc7ce"))
            self.table.setItem(row, column, item)

    def _save_to_current_path(self) -> None:
        if self.workbook is None:
            self.workbook = self.excel.new_workbook()
        self.records = self._records_from_table()
        self.excel.save(self.workbook, self.current_path, self.records)
        self.log.addItem(f"Saved: {self.current_path}")

    def _records_from_table(self) -> list[PassportRecord]:
        records: list[PassportRecord] = []
        for row in range(self.table.rowCount()):
            records.append(
                PassportRecord(
                    row_number=row + 1,
                    full_name=self._text(row, 1),
                    date_of_birth=self._parse_date(self._text(row, 2)),
                    sex=self._text(row, 3),
                    passport_number=self._text(row, 4),
                    expiry_date=self._parse_date(self._text(row, 5)),
                    added_date=self._parse_date(self._text(row, 6)),
                    status=self.records[row].status if row < len(self.records) else "ok",
                    error_message=self.records[row].error_message if row < len(self.records) else "",
                    source_file=self.records[row].source_file if row < len(self.records) else "",
                )
            )
        return records

    def _text(self, row: int, column: int) -> str:
        item = self.table.item(row, column)
        return item.text().strip() if item else ""

    def _mark_dirty(self) -> None:
        self.dirty = True
        self._update_actions()

    def _confirm_discard_unsaved(self) -> bool:
        if not self.dirty:
            return True
        response = QMessageBox.question(
            self,
            "Unsaved changes",
            "Save current workbook before continuing?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
        )
        if response == QMessageBox.Save:
            self.save_workbook()
            return not self.dirty
        return response == QMessageBox.Discard

    def _update_actions(self) -> None:
        has_workbook = self.workbook is not None
        self.save_action.setEnabled(has_workbook and self.current_path is not None)
        self.save_as_action.setEnabled(has_workbook)
        self.import_button.setEnabled(has_workbook and not (self.worker and self.worker.isRunning()))
        label = str(self.current_path) if self.current_path else "No workbook"
        if self.dirty:
            label += " *"
        self.path_label.setText(label)

    def _xlsx_path(self, path: str) -> Path:
        output = Path(path)
        if output.suffix.lower() != ".xlsx":
            output = output.with_suffix(".xlsx")
        return output

    def _format_date(self, value: date | None) -> str:
        return value.strftime("%d/%m/%Y") if value else ""

    def _parse_date(self, value: str) -> date | None:
        if not value:
            return None
        try:
            return datetime.strptime(value, "%d/%m/%Y").date()
        except ValueError:
            return None

    def _warn_if_tesseract_missing(self) -> None:
        if which("tesseract"):
            return
        QMessageBox.warning(
            self,
            "Tesseract not found",
            "Tesseract OCR is not available on PATH. Excel features will work, but OCR will fail until Tesseract is installed.",
        )


def main() -> None:
    freeze_support()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
