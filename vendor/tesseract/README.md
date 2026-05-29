# Bundled Tesseract

Put a portable Windows Tesseract distribution in this folder before running `make build`.

Required layout:

```text
vendor/tesseract/tesseract.exe
vendor/tesseract/tessdata/eng.traineddata
```

When this folder contains `tesseract.exe`, `make build` copies it into
`dist/PassportReaderTool/_internal/tesseract`, and the app uses it automatically.
