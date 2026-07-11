# 이 프로젝트가 시작한 픽셀 투자 사무실 웹 서버만 종료한다.
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$workspace = Split-Path -Parent $PSScriptRoot
$pidPath = Join-Path $workspace "var\run\investment-office.pid"

if (-not (Test-Path -LiteralPath $pidPath)) {
    Write-Output "애플리케이션 프로세스 번호 파일이 없습니다."
    exit 0
}

$rawProcessId = [System.IO.File]::ReadAllText($pidPath).Trim()
$processId = 0
if (-not [int]::TryParse($rawProcessId, [ref]$processId) -or $processId -le 0) {
    Write-Warning "프로세스 번호 파일이 손상되어 제거합니다."
    Remove-Item -LiteralPath $pidPath -Force
    exit 0
}

$process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
if (-not $process) {
    Write-Output "이미 종료된 서버의 오래된 프로세스 번호 파일을 제거합니다."
    Remove-Item -LiteralPath $pidPath -Force
    exit 0
}

$listeners = @(
    Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue |
        Where-Object { $_.OwningProcess -eq $processId -and $_.LocalAddress -eq "127.0.0.1" }
)
$commandLine = [string]$process.CommandLine
$isExpectedCommand = (
    $commandLine -match '(?i)-m\s+uvicorn' -and
    $commandLine -match '(?i)investment_office\.main:app' -and
    $commandLine -match '(?i)--host\s+127\.0\.0\.1' -and
    $commandLine -match '(?i)--port\s+8765'
)

if ($listeners.Count -eq 0 -or -not $isExpectedCommand) {
    Write-Warning "저장된 번호의 프로세스가 이 프로젝트 서버인지 확인되지 않아 종료하지 않습니다."
    Remove-Item -LiteralPath $pidPath -Force
    exit 0
}

Stop-Process -Id $processId
Wait-Process -Id $processId -Timeout 10 -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $pidPath -Force
Write-Output "픽셀 투자 사무실 애플리케이션 서버를 종료했습니다."
