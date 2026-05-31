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
    "paddleocr",
    "--collect-all",
    "paddlex"
)

$vendorModelsDir = Join-Path $PSScriptRoot "..\vendor\paddlex_models"
if (-not (Test-Path $vendorModelsDir)) {
    $userModelsDir = Join-Path $env:USERPROFILE ".paddlex\official_models"
    if (Test-Path $userModelsDir) {
        Write-Host "Creating vendor/paddlex_models and copying models from $userModelsDir..."
        New-Item -ItemType Directory -Force -Path $vendorModelsDir | Out-Null
        $modelsToCopy = @("PP-OCRv5_server_det", "en_PP-OCRv5_mobile_rec", "PP-LCNet_x1_0_textline_ori")
        foreach ($model in $modelsToCopy) {
            $src = Join-Path $userModelsDir $model
            if (Test-Path $src) {
                $dest = Join-Path $vendorModelsDir $model
                Copy-Item -LiteralPath $src -Destination $dest -Recurse -Force
                Write-Host "Copied $model"
            } else {
                Write-Warning "Model $model not found in $userModelsDir"
            }
        }
    } else {
        Write-Warning "Could not find local paddle models at $userModelsDir or $vendorModelsDir."
    }
}

if (Test-Path $vendorModelsDir) {
    $argsList += @("--add-data", "$vendorModelsDir;paddlex_models")
    Write-Host "Bundling paddle models from $vendorModelsDir"
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
