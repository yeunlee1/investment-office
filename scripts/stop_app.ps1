# 이 프로젝트가 시작한 픽셀 투자 사무실 웹 서버만 종료한다.
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$workspace = Split-Path -Parent $PSScriptRoot
$pidPath = Join-Path $workspace "var\run\investment-office.pid"

if (-not (Test-Path -LiteralPath $pidPath)) {
    Write-Output "No application PID file was found."
    exit 0
}

$processId = [int][System.IO.File]::ReadAllText($pidPath)
$process = Get-Process -Id $processId -ErrorAction SilentlyContinue
if ($process) {
    Stop-Process -Id $processId
    Wait-Process -Id $processId -Timeout 10 -ErrorAction SilentlyContinue
}

Write-Output "Pixel Investment Office application server stopped."
