param(
    [switch]$NoBrowser,
    [switch]$FollowLogs,
    [switch]$Rebuild
)

# Keep this entry point ASCII-only for Windows PowerShell 5.1 (no BOM required).
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$environmentFile = Join-Path $projectRoot ".env"
$environmentExample = Join-Path $projectRoot ".env.example"

if (-not (Test-Path -LiteralPath $environmentFile)) {
    Copy-Item -LiteralPath $environmentExample -Destination $environmentFile
    Write-Host "Created .env from .env.example. Configure model API keys before using AI features."
}

$composeArguments = @(
    "compose", "--project-directory", $projectRoot,
    "--env-file", $environmentFile,
    "--file", (Join-Path $projectRoot "compose.yaml")
)

# Resolve the effective port through Compose, including .env and shell overrides.
# Do not print this configuration: it can contain credentials.
$configurationJson = docker @composeArguments config --format json
if ($LASTEXITCODE -ne 0) {
    throw "Compose configuration failed. Check Docker Desktop and the project .env file."
}
$configuration = ($configurationJson -join [Environment]::NewLine) | ConvertFrom-Json
$webBinding = @($configuration.services.web.ports | Where-Object { $_.target -eq 5173 })
if ($webBinding.Count -ne 1 -or [int]$webBinding[0].published -notin 1..65535) {
    throw "Cannot determine the published Web port from Compose configuration."
}
$webUrl = "http://localhost:$($webBinding[0].published)"

Write-Host "Starting StudyAgent in background. First-time image builds may take a few minutes."
$startupArguments = $composeArguments + @("up", "--detach", "--wait", "--wait-timeout", "180")
if ($Rebuild) { $startupArguments += "--build" }
docker @startupArguments
if ($LASTEXITCODE -ne 0) {
    throw "Startup failed or timed out. Check Docker Desktop, then use docker compose logs to diagnose."
}

try {
    $page = Invoke-WebRequest -Uri $webUrl -UseBasicParsing -TimeoutSec 10
    $readiness = Invoke-RestMethod -Uri "$webUrl/api/health/ready" -TimeoutSec 10
    if ($page.StatusCode -ne 200 -or $readiness.status -ne "ok") {
        throw "Web or API is not ready."
    }
}
catch {
    throw "Containers started, but the Web/API check failed. View api and web logs before retrying."
}

Write-Host "Ready: $webUrl"
Write-Host "Services run in background. You may close this terminal."
if (-not $NoBrowser) {
    try { Start-Process -FilePath $webUrl }
    catch { Write-Warning "Cannot open the browser automatically. Open $webUrl manually." }
}

if ($FollowLogs) {
    # Show application logs only; Milvus and other infrastructure stay out of the terminal.
    docker @composeArguments logs --follow --tail 50 api worker web
    if ($LASTEXITCODE -ne 0) { throw "Could not follow application logs." }
}
