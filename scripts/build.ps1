$ErrorActionPreference = "Stop"

$argsList = @(
    "run",
    "pyinstaller",
    "--clean",
    "--noconfirm",
    "--windowed",
    "--name",
    "PassportReaderTool",
    "--collect-all",
    "passporteye",
    "--collect-all",
    "PySide6",
    "--collect-all",
    "imageio",
    "--copy-metadata",
    "imageio"
)

$tesseractDir = Join-Path $PSScriptRoot "..\vendor\tesseract"
$tesseractExe = Join-Path $tesseractDir "tesseract.exe"
if (Test-Path $tesseractExe) {
    $argsList += @("--add-data", "$tesseractDir;tesseract")
    Write-Host "Bundling Tesseract from $tesseractDir"
} else {
    Write-Host "No bundled Tesseract found at $tesseractDir"
    Write-Host "Build will still work, but OCR requires Tesseract on PATH unless vendor/tesseract is added."
}

$argsList += "src/passport_reader_tool/app.py"

& uv @argsList
