$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$environmentFile = Join-Path $projectRoot ".env"
$environmentExample = Join-Path $projectRoot ".env.example"

if (-not (Test-Path -LiteralPath $environmentFile)) {
    Copy-Item -LiteralPath $environmentExample -Destination $environmentFile
    # Keep this entry point ASCII-only for Windows PowerShell 5.1 (no BOM required).
    Write-Host "Created .env from .env.example. Configure model API keys before using AI features."
}

docker compose --file (Join-Path $projectRoot "compose.yaml") up --build
