# MariaDB와 픽셀 투자 사무실 웹 서버를 백그라운드로 실행한다.
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$workspace = Split-Path -Parent $PSScriptRoot
$python = Join-Path $workspace ".venv\Scripts\python.exe"
$logDirectory = Join-Path $workspace "var\logs"
$runDirectory = Join-Path $workspace "var\run"
$pidPath = Join-Path $runDirectory "investment-office.pid"
$healthUrl = "http://127.0.0.1:8765/api/state"

Set-Location $workspace
& (Join-Path $PSScriptRoot "install_mariadb.ps1")

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment is missing. Run uv sync first."
}
if (-not (Test-Path -LiteralPath (Join-Path $workspace ".env"))) {
    & $python (Join-Path $PSScriptRoot "bootstrap_database.py")
    if ($LASTEXITCODE -ne 0) {
        throw "Database bootstrap failed with exit code $LASTEXITCODE"
    }
}

$listener = Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue
if ($listener) {
    try {
        $state = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 5
        if ($state.provider) {
            Write-Output "Pixel Investment Office is already running at http://127.0.0.1:8765"
            exit 0
        }
    } catch {
        throw "Port 8765 is occupied by another process."
    }
}

New-Item -ItemType Directory -Path $logDirectory, $runDirectory -Force | Out-Null
$stdoutPath = Join-Path $logDirectory "app.stdout.log"
$stderrPath = Join-Path $logDirectory "app.stderr.log"
$launcherProcess = Start-Process -FilePath $python `
    -ArgumentList "-m", "uvicorn", "investment_office.main:app", "--host", "127.0.0.1", "--port", "8765" `
    -WorkingDirectory $workspace `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -PassThru

$deadline = (Get-Date).AddSeconds(30)
do {
    Start-Sleep -Milliseconds 400
    if ($launcherProcess.HasExited -and -not (Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue)) {
        $errorTail = if (Test-Path -LiteralPath $stderrPath) { Get-Content -LiteralPath $stderrPath -Tail 50 } else { @() }
        throw "Application server exited. $($errorTail -join [Environment]::NewLine)"
    }
    try {
        $state = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
    } catch {
        $state = $null
    }
} until ($state -or (Get-Date) -gt $deadline)

if (-not $state) {
    throw "Application health check timed out."
}

$serverListener = Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction Stop | Select-Object -First 1
[System.IO.File]::WriteAllText($pidPath, $serverListener.OwningProcess.ToString())
Write-Output "Pixel Investment Office is running at http://127.0.0.1:8765"
