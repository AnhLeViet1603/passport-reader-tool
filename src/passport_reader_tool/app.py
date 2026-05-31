from __future__ import annotations

import sys
from datetime import date, datetime
from importlib.util import find_spec
import logging
from logging.handlers import RotatingFileHandler
from multiprocessing import freeze_support
from pathlib import Path
import traceback


def setup_logging() -> None:
    if hasattr(sys, "frozen"):
        install_dir = Path(sys.executable).resolve().parent
    else:
        install_dir = Path(__file__).resolve().parents[2]

    log_dir = install_dir / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"

    handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)


class LogWrapper:
    def __init__(self) -> None:
        self._logger = logging.getLogger("app")

    def addItem(self, text: str) -> None:
        self._logger.info(text)

from openpyxl import Workbook
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QSplashScreen,
)

from passport_reader_tool.excel_service import EXCEL_HEADERS, ExcelWorkbookService
from passport_reader_tool.models import PassportRecord


class BatchWorker(QThread):
    progress = Signal(object, object)
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, files: list[str], start_row_number: int) -> None:
        super().__init__()
        self.files = files
        self.start_row_number = start_row_number

    def run(self) -> None:
        try:
            from passport_reader_tool.batch_processor import process_files

            records = process_files(self.files, self.start_row_number, progress_callback=self.progress.emit)
            self.finished.emit(records)
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
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
        self._warn_if_paddleocr_missing()

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

        self.import_button = QToolButton()
        self.import_button.setText("Import Images")
        self.import_button.setPopupMode(QToolButton.InstantPopup)
        import_menu = QMenu(self.import_button)
        self.import_folder_action = QAction("Folder...", self)
        self.import_files_action = QAction("Files...", self)
        import_menu.addActions([self.import_folder_action, self.import_files_action])
        self.import_button.setMenu(import_menu)
        toolbar.addWidget(self.import_button)

        self.path_label = QLabel("No workbook")
        toolbar.addWidget(self.path_label)

        self.table = QTableWidget(0, len(EXCEL_HEADERS))
        self.table.setHorizontalHeaderLabels(EXCEL_HEADERS)
        self.table.itemChanged.connect(self._mark_dirty)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        # Redirect self.log.addItem(...) to rotating file logs
        self.log = LogWrapper()

        container = QWidget()
        layout = QVBoxLayout(container)
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Workbook data"))
        top_row.addStretch()
        layout.addLayout(top_row)
        layout.addWidget(self.table)
        layout.addWidget(self.progress)
        self.setCentralWidget(container)

        self.new_action.triggered.connect(self.new_workbook)
        self.open_action.triggered.connect(self.open_workbook)
        self.save_action.triggered.connect(self.save_workbook)
        self.save_as_action.triggered.connect(self.save_as_workbook)
        self.import_folder_action.triggered.connect(self.import_folder)
        self.import_files_action.triggered.connect(self.import_files)

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
        from passport_reader_tool.batch_processor import find_image_files

        files = [str(path) for path in find_image_files(folder)]
        if not files:
            QMessageBox.information(self, "No images found", "The selected folder does not contain supported image files.")
            return
        self._start_import(files, f"Processing folder: {folder}")

    def import_files(self) -> None:
        if self.workbook is None:
            QMessageBox.information(self, "Workbook required", "Create or open an Excel workbook first.")
            return
        image_filter = "Images (*.jpg *.jpeg *.png *.tif *.tiff *.bmp *.webp)"
        files, _ = QFileDialog.getOpenFileNames(self, "Select Image Files", "", image_filter)
        if not files:
            return
        self._start_import(files, f"Processing {len(files)} selected file(s)")

    def _start_import(self, files: list[str], log_message: str) -> None:
        self.import_button.setEnabled(False)
        self.progress.setValue(0)
        self.log.addItem(log_message)
        self.worker = BatchWorker(files, len(self.records) + 1)
        self.worker.progress.connect(self._on_batch_progress)
        self.worker.finished.connect(self._on_batch_finished)
        self.worker.failed.connect(self._on_batch_failed)
        self.worker.start()

    def _on_batch_progress(self, progress: object, record: PassportRecord) -> None:
        percent = int((progress.completed / progress.total) * 100) if progress.total else 0
        self.progress.setValue(percent)
        status = "ERROR" if record.is_error else "OK"
        status_line = f"[{status}] {progress.completed}/{progress.total}: {Path(progress.current_file).name}"
        print(status_line, file=sys.stderr if record.is_error else sys.stdout, flush=True)
        self.log.addItem(status_line)
        if record.error_message:
            error_line = f"  error: {record.error_message}"
            print(error_line, file=sys.stderr, flush=True)
            self.log.addItem(error_line)
        if record.debug_message:
            for line in record.debug_message.splitlines():
                debug_line = f"  debug: {line}"
                print(debug_line, file=sys.stderr if record.is_error else sys.stdout, flush=True)
                self.log.addItem(debug_line)

    def _on_batch_finished(self, records: list[PassportRecord]) -> None:
        existing_passport_numbers = {_normalize_passport_number(record.passport_number) for record in self.records}
        records_to_add: list[PassportRecord] = []
        skipped = 0
        for record in records:
            passport_number = _normalize_passport_number(record.passport_number)
            if passport_number and passport_number in existing_passport_numbers:
                skipped += 1
                self.log.addItem(f"[SKIP] Duplicate passport number: {record.passport_number} ({Path(record.source_file).name})")
                continue
            if passport_number:
                existing_passport_numbers.add(passport_number)
            records_to_add.append(record)

        self.records.extend(records_to_add)
        self._render_records()
        self.import_button.setEnabled(True)
        self.dirty = bool(records_to_add)
        self._update_actions()
        errors = sum(1 for record in records if record.is_error)
        self.log.addItem(f"Batch completed: {len(records)} files, {len(records_to_add)} added, {skipped} skipped, {errors} errors")

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
            self._format_date(record.issue_date),
            self._format_date(record.expiry_date),
            self._format_date(record.added_date),
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value or ""))
            if column == 0:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            if record.is_error:
                item.setBackground(QColor("#ffc7ce"))
            elif record.name_mismatch and column == 1:
                item.setBackground(QColor("#ffeb9c"))
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
                    issue_date=self._parse_date(self._text(row, 5)),
                    expiry_date=self._parse_date(self._text(row, 6)),
                    added_date=self._parse_date(self._text(row, 7)),
                    mrz_full_name=self.records[row].mrz_full_name if row < len(self.records) else "",
                    name_mismatch=self.records[row].name_mismatch if row < len(self.records) else False,
                    status=self.records[row].status if row < len(self.records) else "ok",
                    error_message=self.records[row].error_message if row < len(self.records) else "",
                    debug_message=self.records[row].debug_message if row < len(self.records) else "",
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
        self.import_folder_action.setEnabled(self.import_button.isEnabled())
        self.import_files_action.setEnabled(self.import_button.isEnabled())
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

    def _warn_if_paddleocr_missing(self) -> None:
        if find_spec("paddleocr") is not None:
            return
        QMessageBox.warning(
            self,
            "PaddleOCR not found",
            "PaddleOCR is not installed. Excel features will work, but OCR will fail until dependencies are installed with uv sync.",
        )


def main() -> None:
    freeze_support()
    setup_logging()
    app = QApplication(sys.argv)
    _apply_light_theme(app)
    splash = _create_splash()
    splash.show()
    splash.showMessage("Loading workbook tools...", Qt.AlignBottom | Qt.AlignHCenter, QColor("#20242a"))
    app.processEvents()
    window = MainWindow()
    splash.showMessage("Opening app...", Qt.AlignBottom | Qt.AlignHCenter, QColor("#20242a"))
    app.processEvents()
    window.show()
    splash.finish(window)
    sys.exit(app.exec())


def _apply_light_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#f6f7f9"))
    palette.setColor(QPalette.WindowText, QColor("#20242a"))
    palette.setColor(QPalette.Base, QColor("#ffffff"))
    palette.setColor(QPalette.AlternateBase, QColor("#eef1f5"))
    palette.setColor(QPalette.ToolTipBase, QColor("#ffffff"))
    palette.setColor(QPalette.ToolTipText, QColor("#20242a"))
    palette.setColor(QPalette.Text, QColor("#20242a"))
    palette.setColor(QPalette.Button, QColor("#f1f3f6"))
    palette.setColor(QPalette.ButtonText, QColor("#20242a"))
    palette.setColor(QPalette.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.Highlight, QColor("#2f6fed"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.Link, QColor("#2f6fed"))
    app.setPalette(palette)
    app.setStyleSheet(
        """
        QMainWindow, QWidget {
            background: #f6f7f9;
            color: #20242a;
        }
        QToolBar {
            background: #ffffff;
            border-bottom: 1px solid #d8dde6;
            spacing: 8px;
        }
        QTableWidget, QListWidget {
            background: #ffffff;
            border: 1px solid #d8dde6;
            gridline-color: #e3e7ee;
            selection-background-color: #d9e7ff;
            selection-color: #111827;
        }
        QHeaderView::section {
            background: #eef1f5;
            color: #20242a;
            border: 0;
            border-right: 1px solid #d8dde6;
            border-bottom: 1px solid #d8dde6;
            padding: 6px;
        }
        QPushButton, QToolButton {
            background: #ffffff;
            border: 1px solid #c8ced8;
            border-radius: 4px;
            padding: 5px 10px;
        }
        QPushButton:hover, QToolButton:hover {
            background: #eef4ff;
            border-color: #9bbbf5;
        }
        QPushButton:disabled, QToolButton:disabled {
            background: #eef1f5;
            color: #8b95a1;
        }
        QMenu {
            background: #ffffff;
            border: 1px solid #c8ced8;
        }
        QMenu::item:selected {
            background: #d9e7ff;
            color: #111827;
        }
        QProgressBar {
            background: #ffffff;
            border: 1px solid #c8ced8;
            border-radius: 4px;
            text-align: center;
        }
        QProgressBar::chunk {
            background: #2f6fed;
            border-radius: 3px;
        }
        """
    )


def _normalize_passport_number(value: str) -> str:
    return "".join(character for character in str(value or "").upper() if character.isalnum())


def _create_splash() -> QSplashScreen:
    pixmap = QPixmap(520, 280)
    pixmap.fill(QColor("#f6f7f9"))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QColor("#20242a"))
    title_font = QFont("Segoe UI", 24)
    title_font.setBold(True)
    painter.setFont(title_font)
    painter.drawText(32, 86, "Passport Reader Tool")

    painter.setPen(QColor("#4b5563"))
    subtitle_font = QFont("Segoe UI", 11)
    painter.setFont(subtitle_font)
    painter.drawText(34, 126, "Preparing desktop workspace and PaddleOCR runtime")

    painter.setPen(QColor("#2f6fed"))
    painter.setBrush(QColor("#2f6fed"))
    painter.drawRoundedRect(34, 166, 452, 6, 3, 3)
    painter.end()

    return QSplashScreen(pixmap)


if __name__ == "__main__":
    main()
