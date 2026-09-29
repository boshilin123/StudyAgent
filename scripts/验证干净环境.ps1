param(
    [switch]$SkipBackendInstall
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$verificationRoot = Join-Path $projectRoot 'tmp\clean-environment'
$webSource = Join-Path $projectRoot 'apps\web'
$webTarget = Join-Path $verificationRoot 'web'
$apiSource = Join-Path $projectRoot 'apps\api'
$apiVenv = Join-Path $verificationRoot 'api-venv'

if (Test-Path -LiteralPath $verificationRoot) {
    Remove-Item -LiteralPath $verificationRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $webTarget -Force | Out-Null

$webFiles = @(
    'package.json',
    'package-lock.json',
    'index.html',
    'tsconfig.json',
    'tsconfig.app.json',
    'tsconfig.node.json',
    'vite.config.ts'
)
foreach ($file in $webFiles) {
    Copy-Item -LiteralPath (Join-Path $webSource $file) -Destination $webTarget
}
Copy-Item -LiteralPath (Join-Path $webSource 'src') -Destination $webTarget -Recurse

Push-Location $webTarget
try {
    npm.cmd ci --cache (Join-Path $projectRoot 'tmp\npm-cache')
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
    npm.cmd run typecheck
    if ($LASTEXITCODE -ne 0) { throw 'frontend typecheck failed' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'frontend build failed' }
}
finally {
    Pop-Location
}

if (-not $SkipBackendInstall) {
    python -m venv $apiVenv
    $python = Join-Path $apiVenv 'Scripts\python.exe'
    & $python -m pip install --upgrade pip
    & $python -m pip install -e "${apiSource}[dev]"
    Push-Location $apiSource
    try {
        & $python -m pytest
        & $python -m ruff check --no-cache .
        & $python -m mypy --no-incremental study_agent
    }
    finally {
        Pop-Location
    }
}

Write-Host 'Clean-environment verification passed.'
