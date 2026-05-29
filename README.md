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
