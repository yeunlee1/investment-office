# 픽셀 투자 사무실 전용 MariaDB 인스턴스를 사용자 권한으로 설치하고 실행한다.
[CmdletBinding()]
param(
    [int]$Port = 3307,
    [string]$Version = "11.8.2",
    [string]$Sha256 = "e93ae57c8b5dc424778ba428a762a4cd4ec62f8ffd15db0bbd9e01660ce06416"
)

$ErrorActionPreference = "Stop"
$workspace = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $workspace "var\runtime"
$runtimeDirectory = Join-Path $runtimeRoot "mariadb-$Version-winx64"
$cacheDirectory = Join-Path $workspace "var\cache"
$archivePath = Join-Path $cacheDirectory "mariadb-$Version-winx64.zip"
$dataDirectory = Join-Path $workspace "var\mariadb-data"
$logDirectory = Join-Path $workspace "var\logs"
$secretDirectory = Join-Path $workspace "var\secrets"
$secretPath = Join-Path $secretDirectory "mariadb-root.txt"
$pidPath = Join-Path $workspace "var\run\mariadb.pid"
$downloadUrl = "https://archive.mariadb.org/mariadb-$Version/winx64-packages/mariadb-$Version-winx64.zip"

New-Item -ItemType Directory -Path $runtimeRoot, $cacheDirectory, $logDirectory, $secretDirectory, (Split-Path -Parent $pidPath) -Force | Out-Null

if (-not (Test-Path -LiteralPath (Join-Path $runtimeDirectory "bin\mariadbd.exe"))) {
    if (-not (Test-Path -LiteralPath $archivePath)) {
        Invoke-WebRequest -Uri $downloadUrl -OutFile $archivePath -TimeoutSec 300
    }

    $actualHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $Sha256) {
        throw "MariaDB archive checksum mismatch"
    }

    Expand-Archive -LiteralPath $archivePath -DestinationPath $runtimeRoot -Force
}

$installDatabase = Join-Path $runtimeDirectory "bin\mariadb-install-db.exe"
$server = Join-Path $runtimeDirectory "bin\mariadbd.exe"
$configPath = Join-Path $dataDirectory "my.ini"

if (-not (Test-Path -LiteralPath (Join-Path $dataDirectory "mysql"))) {
    $alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    $random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $bytes = New-Object byte[] 48
    $random.GetBytes($bytes)
    $rootPassword = -join ($bytes | ForEach-Object { $alphabet[$_ % $alphabet.Length] })
    $random.Dispose()

    [System.IO.File]::WriteAllText($secretPath, $rootPassword)
    & icacls.exe $secretPath /inheritance:r /grant:r "${env:USERNAME}:(R,W)" | Out-Null

    & $installDatabase --datadir=$dataDirectory --password=$rootPassword --port=$Port
    if ($LASTEXITCODE -ne 0) {
        throw "MariaDB data directory initialization failed with exit code $LASTEXITCODE"
    }

    Add-Content -LiteralPath $configPath -Value @"

[mariadb]
bind-address=127.0.0.1
skip-name-resolve
character-set-server=utf8mb4
collation-server=utf8mb4_unicode_ci
"@
}

$listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if (-not $listener) {
    $stdoutPath = Join-Path $logDirectory "mariadb.stdout.log"
    $stderrPath = Join-Path $logDirectory "mariadb.stderr.log"
    $process = Start-Process -FilePath $server `
        -ArgumentList "--defaults-file=`"$configPath`"", "--console" `
        -WorkingDirectory $runtimeDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -PassThru
    [System.IO.File]::WriteAllText($pidPath, $process.Id.ToString())

    $deadline = (Get-Date).AddSeconds(30)
    do {
        Start-Sleep -Milliseconds 250
        $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    } until ($listener -or (Get-Date) -gt $deadline -or $process.HasExited)

    if (-not $listener) {
        $errorTail = if (Test-Path -LiteralPath $stderrPath) { Get-Content -LiteralPath $stderrPath -Tail 40 } else { @() }
        throw "MariaDB failed to listen on port $Port. $($errorTail -join [Environment]::NewLine)"
    }
}

Write-Output "MariaDB portable instance is listening on 127.0.0.1:$Port"
Write-Output "Root credential is stored in the workspace-local protected secrets directory"
