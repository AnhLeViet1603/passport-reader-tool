from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from passport_reader_tool.models import PassportRecord
from passport_reader_tool.ocr_pipeline import MrzOcrPipeline, OcrConfig


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}


@dataclass(frozen=True, slots=True)
class BatchProgress:
    completed: int
    total: int
    current_file: str
    errors: int


ProgressCallback = Callable[[BatchProgress, PassportRecord], None]


def find_image_files(folder: str | Path) -> list[Path]:
    root = Path(folder)
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Folder không tồn tại: {root}")
    return sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS)


def recommended_worker_count() -> int:
    try:
        import os

        return max(1, min(4, (os.cpu_count() or 2) - 1))
    except Exception:
        return 1


def process_folder(
    folder: str | Path,
    start_row_number: int = 1,
    max_workers: int | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[PassportRecord]:
    files = find_image_files(folder)
    return process_files(files, start_row_number, max_workers, progress_callback)


def process_files(
    files: Iterable[str | Path],
    start_row_number: int = 1,
    max_workers: int | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[PassportRecord]:
    file_list = [Path(path) for path in files]
    total = len(file_list)
    if total == 0:
        return []

    workers = max_workers or recommended_worker_count()
    added_date = date.today()
    results_by_index: dict[int, PassportRecord] = {}
    errors = 0

    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_process_one_file, path, start_row_number + index, added_date): index
            for index, path in enumerate(file_list)
        }
        completed = 0
        for future in as_completed(futures):
            index = futures[future]
            completed += 1
            try:
                record = future.result()
            except Exception as exc:
                record = PassportRecord(
                    row_number=start_row_number + index,
                    added_date=added_date,
                    status="error",
                    error_message=str(exc),
                    source_file=str(file_list[index]),
                )
            if record.is_error:
                errors += 1
            results_by_index[index] = record
            if progress_callback:
                progress_callback(
                    BatchProgress(completed, total, str(file_list[index]), errors),
                    record,
                )

    return [results_by_index[index] for index in sorted(results_by_index)]


def _process_one_file(path: Path, row_number: int, added_date: date) -> PassportRecord:
    pipeline = MrzOcrPipeline(OcrConfig())
    return pipeline.read_passport(path, row_number, added_date)
