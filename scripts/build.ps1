$ErrorActionPreference = "Stop"

$distAppDir = Join-Path $PSScriptRoot "..\dist\PassportReaderTool"
$preserveDir = Join-Path ([System.IO.Path]::GetTempPath()) ("PassportReaderTool-build-preserve-" + [System.Guid]::NewGuid())
$preservedPaths = @()

function Preserve-BuildArtifact {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    New-Item -ItemType Directory -Force -Path $preserveDir | Out-Null
    $destination = Join-Path $preserveDir (Split-Path -Leaf $Path)
    Copy-Item -LiteralPath $Path -Destination $destination -Recurse -Force
    $script:preservedPaths += [PSCustomObject]@{
        Source = $Path
        Backup = $destination
    }
}

Preserve-BuildArtifact (Join-Path $distAppDir "test")
if (Test-Path -LiteralPath $distAppDir) {
    Get-ChildItem -LiteralPath $distAppDir -File -Filter "*.xlsx" | ForEach-Object {
        Preserve-BuildArtifact $_.FullName
    }
}

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

try {
    & uv @argsList
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
} finally {
    foreach ($item in $preservedPaths) {
        $parent = Split-Path -Parent $item.Source
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
        Copy-Item -LiteralPath $item.Backup -Destination $item.Source -Recurse -Force
    }
    if (Test-Path -LiteralPath $preserveDir) {
        Remove-Item -LiteralPath $preserveDir -Recurse -Force
    }
}
