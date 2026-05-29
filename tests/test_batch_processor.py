from pathlib import Path

from passport_reader_tool.batch_processor import find_image_files


def test_find_image_files_filters_supported_extensions(tmp_path):
    for name in ["a.jpg", "b.PNG", "c.tiff", "notes.txt", "book.pdf"]:
        (tmp_path / name).write_text("x")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "d.webp").write_text("x")

    files = find_image_files(tmp_path)

    assert [path.name for path in files] == ["a.jpg", "b.PNG", "c.tiff", "d.webp"]
    assert all(isinstance(path, Path) for path in files)
