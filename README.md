# Passport Reader Tool

Desktop app for batch-reading passport MRZ from scanned or phone-captured images and saving the extracted data to Excel.

## Stack

- Python
- PySide6
- PassportEye + Tesseract OCR
- OpenCV
- openpyxl
- uv
- PyInstaller

## Development

```powershell
make install
make run
make test
make build
```

Tesseract OCR must be installed and available on `PATH` for OCR to work.

## Windows build

`make build` runs PyInstaller and writes the desktop app into `dist/PassportReaderTool/`.

To ship OCR without requiring users to install Tesseract, put a portable Windows
Tesseract distribution in:

```text
vendor/tesseract/tesseract.exe
vendor/tesseract/tessdata/eng.traineddata
```

Then run:

```powershell
make build
```

The build copies that folder into `dist/PassportReaderTool/_internal/tesseract`,
and the app uses the bundled `tesseract.exe` automatically.
