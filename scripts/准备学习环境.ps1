param([switch]$SkipInstall)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$apiRoot = Join-Path $projectRoot 'apps/api'
$python = Join-Path $apiRoot '.venv/Scripts/python.exe'

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $Executable (exit $LASTEXITCODE)" }
}

if (-not (Test-Path -LiteralPath $python)) {
    Invoke-Checked 'py' @('-3.12', '-m', 'venv', (Join-Path $apiRoot '.venv'))
}
Invoke-Checked $python @('-c', 'import sys; assert sys.version_info[:2] == (3, 12), "Python 3.12 required"')
if (-not $SkipInstall) {
    Invoke-Checked $python @('-m', 'pip', 'install', '--disable-pip-version-check', '-q', '-r', (Join-Path $apiRoot 'requirements-dev.lock'))
    Invoke-Checked $python @('-m', 'pip', 'install', '--disable-pip-version-check', '-q', '--no-deps', '-e', $apiRoot)
    # 原环境的遗留 adapter 未被源码使用，也不在 v1 锁文件中；它要求 core < 0.4。
    & $python -m pip show langchain-milvus 1>$null 2>$null
    if ($LASTEXITCODE -eq 0) {
        Invoke-Checked $python @('-m', 'pip', 'uninstall', '-y', 'langchain-milvus')
    }
}
Invoke-Checked $python @('-m', 'pip', 'check')
Invoke-Checked $python @((Join-Path $projectRoot 'scripts/验证学习准备.py'))
Write-Host "Learning interpreter: $python"
