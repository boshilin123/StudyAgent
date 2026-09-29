$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$environmentFile = Join-Path $projectRoot ".env"
$environmentExample = Join-Path $projectRoot ".env.example"

if (-not (Test-Path -LiteralPath $environmentFile)) {
    Copy-Item -LiteralPath $environmentExample -Destination $environmentFile
    Write-Host "已从 .env.example 创建 .env，请在接入模型前填写密钥。"
}

docker compose --file (Join-Path $projectRoot "compose.yaml") up --build
