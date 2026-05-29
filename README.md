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
Install Tesseract OCR on the target machine or package it separately and make sure
`tesseract.exe` is available on `PATH`.
