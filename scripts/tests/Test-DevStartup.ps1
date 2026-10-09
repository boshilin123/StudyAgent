# Isolated launcher regression: no containers, browsers or .env files are modified.
$ErrorActionPreference = 'Stop'
$launcherRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$launcherPath = Join-Path $launcherRoot 'scripts\dev.ps1'
$global:StudyStartupTestRoot = $launcherRoot

function Assert-Startup {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$tokens = $null
$parseErrors = $null
$null = [System.Management.Automation.Language.Parser]::ParseFile($launcherPath, [ref]$tokens, [ref]$parseErrors)
Assert-Startup ($parseErrors.Count -eq 0) 'Launcher must parse without errors.'
Assert-Startup (@([IO.File]::ReadAllBytes($launcherPath) | Where-Object { $_ -gt 127 }).Count -eq 0) 'Launcher must remain ASCII-only for PowerShell 5.1.'

function Reset-StartupState {
    $global:StudyStartupTestState = @{
        Commands = @(); Browsers = @(); Requests = @(); Copies = 0
        MissingEnvironment = $false; FailStartup = $false; FailReadiness = $false
        FailMigration = $false; FailUpdate = $false; FailDependencies = $false; FailBuild = $false
    }
}

function Test-Path {
    param([string]$LiteralPath)
    if ($LiteralPath -eq (Join-Path $global:StudyStartupTestRoot '.env')) {
        return -not $global:StudyStartupTestState.MissingEnvironment
    }
    return Microsoft.PowerShell.Management\Test-Path -LiteralPath $LiteralPath
}

function Copy-Item {
    param([string]$LiteralPath, [string]$Destination)
    Assert-Startup ($LiteralPath -eq (Join-Path $global:StudyStartupTestRoot '.env.example')) 'Unexpected configuration source.'
    Assert-Startup ($Destination -eq (Join-Path $global:StudyStartupTestRoot '.env')) 'Unexpected configuration destination.'
    $global:StudyStartupTestState.Copies++
}

function docker {
    $global:StudyStartupTestState.Commands += ,@($args)
    Assert-Startup ($args[0] -eq 'compose') 'Expected Compose command.'
    Assert-Startup ($args[2] -eq $global:StudyStartupTestRoot) 'Project path depends on current directory.'
    Assert-Startup ($args[4] -eq (Join-Path $global:StudyStartupTestRoot '.env')) 'Wrong environment path.'
    Assert-Startup ($args[6] -eq (Join-Path $global:StudyStartupTestRoot 'compose.yaml')) 'Wrong Compose path.'
    if ($args -contains 'config') {
        $global:LASTEXITCODE = 0
        return '{"services":{"web":{"ports":[{"target":5173,"published":"55321"}]}}}'
    }
    if (($args -contains 'up') -and $global:StudyStartupTestState.FailStartup) {
        $global:LASTEXITCODE = 42
        return
    }
    if (($args -contains 'alembic') -and $global:StudyStartupTestState.FailMigration) {
        $global:LASTEXITCODE = 43
        return
    }
    if (($args -contains '--force-recreate') -and $global:StudyStartupTestState.FailUpdate) {
        $global:LASTEXITCODE = 44
        return
    }
    if (($args -contains 'ci') -and $global:StudyStartupTestState.FailDependencies) {
        $global:LASTEXITCODE = 45
        return
    }
    if (($args -contains 'build') -and $global:StudyStartupTestState.FailBuild) {
        $global:LASTEXITCODE = 46
        return
    }
    $global:LASTEXITCODE = 0
}

function Invoke-WebRequest {
    param([string]$Uri, [switch]$UseBasicParsing, [int]$TimeoutSec)
    $global:StudyStartupTestState.Requests += $Uri
    return [pscustomobject]@{ StatusCode = 200 }
}

function Invoke-RestMethod {
    param([string]$Uri, [int]$TimeoutSec)
    $global:StudyStartupTestState.Requests += $Uri
    if ($global:StudyStartupTestState.FailReadiness) { throw 'Simulated unavailable API.' }
    return [pscustomobject]@{ status = 'ok' }
}

function Start-Process {
    param([string]$FilePath)
    $global:StudyStartupTestState.Browsers += $FilePath
}

Push-Location $env:TEMP
try {
    Reset-StartupState
    & $launcherPath
    $up = $global:StudyStartupTestState.Commands[1]
    Assert-Startup (($up -contains '--detach') -and ($up -contains '--wait')) 'Default startup must be detached and wait for health.'
    Assert-Startup (-not ($up -contains '--build')) 'Default startup should not force image rebuilds.'
    Assert-Startup ($global:StudyStartupTestState.Browsers[0] -eq 'http://localhost:55321') 'Browser URL must use effective Compose port.'
    Assert-Startup ($global:StudyStartupTestState.Requests[1] -eq 'http://localhost:55321/api/health/ready') 'API must be checked through Web proxy.'
    Assert-Startup ($global:StudyStartupTestState.Commands.Count -eq 2) 'Default startup must not follow container logs.'
    Write-Output 'PASS: background startup, ready checks, browser, custom port and different working directory.'

    Reset-StartupState
    $global:StudyStartupTestState.MissingEnvironment = $true
    & $launcherPath -NoBrowser -Rebuild
    Assert-Startup ($global:StudyStartupTestState.Copies -eq 1) 'First-run environment setup was skipped.'
    Assert-Startup ($global:StudyStartupTestState.Browsers.Count -eq 0) 'NoBrowser opened a browser.'
    Assert-Startup ($global:StudyStartupTestState.Commands[1] -contains 'build') 'Rebuild must rebuild images.'
    Write-Output 'PASS: first-run configuration, NoBrowser and Rebuild.'

    $dependencyCommand = $global:StudyStartupTestState.Commands[2]
    Assert-Startup (($dependencyCommand -contains 'ci') -and ($dependencyCommand -contains '--no-deps')) 'Rebuild must refresh the persistent frontend dependency volume.'
    Assert-Startup ($global:StudyStartupTestState.Commands[3] -contains 'up') 'Dependencies must be synchronized before waiting for Web readiness.'
    Assert-Startup ($global:StudyStartupTestState.Commands[5] -contains '--force-recreate') 'Rebuild must reload application processes.'

    Reset-StartupState
    & $launcherPath -NoBrowser -Update
    $migration = $global:StudyStartupTestState.Commands[2]
    $update = $global:StudyStartupTestState.Commands[3]
    Assert-Startup (($migration -contains 'alembic') -and ($migration -contains 'head')) 'Update must migrate before recreation.'
    Assert-Startup (($update -contains '--force-recreate') -and ($update -contains '--wait') -and ($update -contains '--no-deps')) 'Update must recreate application services and wait for health.'
    Assert-Startup (($update[-3] -eq 'api') -and ($update[-2] -eq 'worker') -and ($update[-1] -eq 'web')) 'Update must target only API, Worker and Web.'
    Assert-Startup (-not ($update -contains '--build')) 'Source-only update should not rebuild images.'
    Assert-Startup ($global:StudyStartupTestState.Browsers.Count -eq 0) 'Update NoBrowser opened a browser.'
    Write-Output 'PASS: Update applies migrations and reloads only application containers.'

    foreach ($failure in @('FailMigration', 'FailUpdate', 'FailDependencies', 'FailBuild')) {
        Reset-StartupState
        $global:StudyStartupTestState[$failure] = $true
        $failed = $false
        try { & $launcherPath -Rebuild }
        catch { $failed = $true }
        Assert-Startup $failed "Expected $failure to fail explicitly."
        Assert-Startup ($global:StudyStartupTestState.Browsers.Count -eq 0) 'Failed update must not open a browser.'
        if ($failure -eq 'FailMigration') {
            Assert-Startup ($global:StudyStartupTestState.Commands.Count -eq 5) 'Migration failure must stop before application recreation.'
        }
        if ($failure -eq 'FailDependencies') {
            Assert-Startup ($global:StudyStartupTestState.Commands.Count -eq 3) 'Dependency failure must stop before application startup.'
        }
        if ($failure -eq 'FailBuild') {
            Assert-Startup ($global:StudyStartupTestState.Commands.Count -eq 2) 'Build failure must stop before dependency install or startup.'
        }
        Write-Output "PASS: $failure stops the update and does not open a browser."
    }

    Reset-StartupState
    & $launcherPath -NoBrowser -FollowLogs
    $logs = $global:StudyStartupTestState.Commands[2]
    Assert-Startup (($logs -contains 'logs') -and ($logs -contains '--follow')) 'FollowLogs did not request application logs.'
    Assert-Startup (($logs -contains 'api') -and ($logs -contains 'worker') -and ($logs -contains 'web')) 'Expected application log services.'
    Assert-Startup (-not ($logs -contains 'milvus')) 'Milvus should not stream in application logs.'
    Write-Output 'PASS: opt-in application logs exclude Milvus.'

    foreach ($failure in @('FailStartup', 'FailReadiness')) {
        Reset-StartupState
        $global:StudyStartupTestState[$failure] = $true
        $failed = $false
        try { & $launcherPath }
        catch { $failed = $true }
        Assert-Startup $failed "Expected $failure to fail explicitly."
        Assert-Startup ($global:StudyStartupTestState.Browsers.Count -eq 0) 'Failed startup must not open a browser.'
        Write-Output "PASS: $failure fails without opening browser."
    }
}
finally { Pop-Location }

Write-Output 'All startup regressions passed. No user configuration or running containers changed.'
