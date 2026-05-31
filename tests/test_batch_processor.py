from pathlib import Path

import passport_reader_tool.batch_processor as batch_processor
from passport_reader_tool.batch_processor import find_image_files
from passport_reader_tool.batch_processor import recommended_worker_count


def test_find_image_files_filters_supported_extensions(tmp_path):
    for name in ["a.jpg", "b.PNG", "c.tiff", "notes.txt", "book.pdf"]:
        (tmp_path / name).write_text("x")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "d.webp").write_text("x")

    files = find_image_files(tmp_path)

    assert [path.name for path in files] == ["a.jpg", "b.PNG", "c.tiff", "d.webp"]
    assert all(isinstance(path, Path) for path in files)


def test_recommended_worker_count_keeps_one_ocr_model_loaded_on_small_office_machines(monkeypatch):
    monkeypatch.setattr(batch_processor, "_total_memory_gb", lambda: 8)
    monkeypatch.setattr(batch_processor.os, "cpu_count", lambda: 8)

    assert recommended_worker_count() == 1


def test_recommended_worker_count_allows_two_workers_when_memory_and_cpu_allow(monkeypatch):
    monkeypatch.setattr(batch_processor, "_total_memory_gb", lambda: 16)
    monkeypatch.setattr(batch_processor.os, "cpu_count", lambda: 8)

    assert recommended_worker_count() == 2
