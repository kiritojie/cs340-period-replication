<#
.SYNOPSIS
  Host-side orchestration guide/driver for WSL2 true root-domain core-count experiments.
.DESCRIPTION
  Switches %USERPROFILE%\.wslconfig processors=N, shuts down WSL2, restarts Docker Desktop,
  waits for the Docker engine, and invokes scripts/extension_wsl_cores.sh inside
  wcventure/period:stable (--privileged) without taskset.
.EXAMPLE
  .\scripts\extension_wsl_cores_driver.ps1 -CoreCounts @(8,4,2) -R5Rounds 5 -R10Rounds 3
#>
param(
    [int[]]$CoreCounts = @(8, 4, 2),
    [int]$R5Rounds = 5,
    [int]$R10Rounds = 3,
    [string]$OutBase = "/repo/docs/results/extension-wsl-cores",
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"
$wslConfig = Join-Path $env:USERPROFILE ".wslconfig"
$hadOriginal = Test-Path $wslConfig
$origBackup = $null
if ($hadOriginal) {
    $origBackup = Get-Content $wslConfig -Raw
}

function Wait-DockerReady {
    param([int]$TimeoutSec = 120)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { return }
        Start-Sleep -Seconds 3
    }
    throw "Docker engine did not become ready within $TimeoutSec seconds."
}

try {
    foreach ($n in $CoreCounts) {
        Write-Host "=== Configuring WSL2 processors=$n ==="
        Set-Content -Path $wslConfig -Value "[wsl2]`nprocessors=$n" -Encoding Ascii
        wsl --shutdown
        Start-Sleep -Seconds 3
        Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
        Wait-DockerReady

        Write-Host "=== Running extension_wsl_cores.sh under $n logical CPUs ==="
        docker run --rm --privileged `
            -e "R5_ROUNDS=$R5Rounds" `
            -e "R10_ROUNDS=$R10Rounds" `
            -e "OUT_BASE=$OutBase" `
            -v "${RepoRoot}:/repo" `
            wcventure/period:stable `
            bash -c "tr -d '\r' < /repo/scripts/extension_wsl_cores.sh > /tmp/run.sh && bash /tmp/run.sh"
    }
}
finally {
    Write-Host "=== Restoring original .wslconfig ==="
    if ($hadOriginal) {
        Set-Content -Path $wslConfig -Value $origBackup -Encoding Ascii
    } elseif (Test-Path $wslConfig) {
        Remove-Item -Path $wslConfig -Force
    }
    wsl --shutdown
}
