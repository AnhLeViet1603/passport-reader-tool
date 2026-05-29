from passport_reader_tool import tesseract_runtime


def test_configure_tesseract_uses_bundled_binary(monkeypatch, tmp_path):
    bundled = tmp_path / "tesseract"
    bundled.mkdir()
    executable = bundled / "tesseract.exe"
    executable.write_text("")
    tessdata = bundled / "tessdata"
    tessdata.mkdir()

    monkeypatch.setattr(tesseract_runtime, "find_bundled_tesseract_dir", lambda: bundled)

    configured = tesseract_runtime.configure_tesseract()

    assert configured == executable
    assert tesseract_runtime.pytesseract.tesseract_cmd == str(executable)
