param(
    [switch]$SkipBackendInstall
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$verificationRoot = Join-Path $projectRoot ('tmp\clean-environment-' + [guid]::NewGuid().ToString('N'))
$webSource = Join-Path $projectRoot 'apps\web'
$webTarget = Join-Path $verificationRoot 'web'
$apiSource = Join-Path $projectRoot 'apps\api'
$apiTarget = Join-Path $verificationRoot 'api'
$apiVenv = Join-Path $verificationRoot 'api-venv'

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Native command failed (exit $LASTEXITCODE): $Executable"
    }
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
    'playwright.config.ts'
)
foreach ($file in $webFiles) {
    Copy-Item -LiteralPath (Join-Path $webSource $file) -Destination $webTarget
}
Copy-Item -LiteralPath (Join-Path $webSource 'src') -Destination $webTarget -Recurse
Copy-Item -LiteralPath (Join-Path $webSource 'tests') -Destination $webTarget -Recurse

Push-Location $webTarget
try {
    npm.cmd ci --cache (Join-Path $projectRoot 'tmp\npm-cache')
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
    npm.cmd run typecheck
    if ($LASTEXITCODE -ne 0) { throw 'frontend typecheck failed' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'frontend build failed' }
    if (-not $env:PLAYWRIGHT_CHROMIUM_EXECUTABLE) {
        $chromePath = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
        if (Test-Path -LiteralPath $chromePath) { $env:PLAYWRIGHT_CHROMIUM_EXECUTABLE = $chromePath }
        else {
            npm.cmd exec playwright install chromium
            if ($LASTEXITCODE -ne 0) { throw 'browser installation failed' }
        }
    }
    npm.cmd run test:e2e -- --max-failures=1
    if ($LASTEXITCODE -ne 0) { throw 'frontend browser tests failed' }
}
finally {
    Pop-Location
}

if (-not $SkipBackendInstall) {
    New-Item -ItemType Directory -Path $apiTarget -Force | Out-Null
    foreach ($file in @('pyproject.toml', 'requirements-dev.lock', 'alembic.ini')) {
        Copy-Item -LiteralPath (Join-Path $apiSource $file) -Destination $apiTarget
    }
    foreach ($directory in @('study_agent', 'tests', 'migrations')) {
        Copy-Item -LiteralPath (Join-Path $apiSource $directory) -Destination $apiTarget -Recurse
    }
    Invoke-Checked 'python' @('-m', 'venv', $apiVenv)
    $python = Join-Path $apiVenv 'Scripts\python.exe'
    Invoke-Checked $python @('-m', 'pip', 'install', '-r', (Join-Path $apiTarget 'requirements-dev.lock'))
    Invoke-Checked $python @('-m', 'pip', 'install', '--no-deps', '-e', $apiTarget)
    Invoke-Checked $python @('-m', 'pip', 'check')
    Push-Location $apiTarget
    try {
        if ($env:TEST_DATABASE_URL) {
            Invoke-Checked $python @('-c', "import os; from sqlalchemy.engine import make_url; assert (make_url(os.environ['TEST_DATABASE_URL']).database or '').startswith('study_agent_test'), 'refuse non-test database'")
            $verificationDatabaseUrl = $env:DATABASE_URL
            try {
                $env:DATABASE_URL = $env:TEST_DATABASE_URL
                Invoke-Checked $python @('-m', 'alembic', 'upgrade', 'head')
            }
            finally { $env:DATABASE_URL = $verificationDatabaseUrl }
        }
        Invoke-Checked $python @('-m', 'pytest')
        Invoke-Checked $python @('-m', 'ruff', 'check', '--no-cache', '.')
        Invoke-Checked $python @('-m', 'mypy', '--no-incremental', 'study_agent')
    }
    finally {
        Pop-Location
    }
}

if ($SkipBackendInstall) { Write-Host 'Frontend clean-environment verification passed; backend skipped by request.' }
else { Write-Host 'Clean-environment verification passed.' }
if (-not $env:TEST_DATABASE_URL) { Write-Host 'PostgreSQL integration tests skipped: TEST_DATABASE_URL is not set.' }
Write-Host "Preserved verification directory: $verificationRoot"
