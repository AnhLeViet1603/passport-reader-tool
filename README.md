# Passport Reader Tool

Desktop app for batch-reading passport MRZ from scanned or phone-captured images and saving the extracted data to Excel.

## Stack

- Python
- PySide6
- PaddleOCR
- Internal MRZ parser and checksum validator
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

PaddleOCR runs inference locally. On first use, it may download/cache model
files if they are not already available on the machine.

## Windows build

`make build` runs PyInstaller and writes the desktop app into `dist/PassportReaderTool/`.
