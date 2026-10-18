<#
.SYNOPSIS
  Start, stop or inspect the SmartClass production processes registered by setup_tasks.ps1.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File deploy\windows\control.ps1 status
  powershell -ExecutionPolicy Bypass -File deploy\windows\control.ps1 stop
  powershell -ExecutionPolicy Bypass -File deploy\windows\control.ps1 start
#>
param(
    [Parameter(Mandatory)][ValidateSet("start", "stop", "status")][string]$Action,
    [string]$DeployRoot = "D:\SmartClassDeploy",
    [int]$BackendPort = 8001,
    [string]$Site = "localhost"
)
$ErrorActionPreference = "Stop"
$TaskPath = "\SmartClass\"
$run = Join-Path $DeployRoot "run"
# Start order: database, backend, proxy. Stop order: the reverse.
$services = @(
    @{ Task = "SmartClass PostgreSQL"; Name = "postgres" },
    @{ Task = "SmartClass Backend"; Name = "backend" },
    @{ Task = "SmartClass Proxy"; Name = "caddy" }
)

function Get-Supervised([string]$name) {
    $pidFile = Join-Path $run "$name.pid"
    if (-not (Test-Path $pidFile)) { return $null }
    $info = Get-Content $pidFile -Raw | ConvertFrom-Json
    if (-not (Get-Process -Id $info.supervisor -ErrorAction SilentlyContinue)) { return $null }
    return $info
}

switch ($Action) {
    "start" {
        foreach ($s in $services) {
            if (Get-Supervised $s.Name) { Write-Output "$($s.Name): already running"; continue }
            Start-ScheduledTask -TaskName $s.Task -TaskPath $TaskPath
            Write-Output "$($s.Name): started"
            Start-Sleep -Seconds 2
        }
    }
    "stop" {
        [array]::Reverse($services)
        foreach ($s in $services) {
            if (-not (Get-Supervised $s.Name)) { Write-Output "$($s.Name): not running"; continue }
            Set-Content -Path (Join-Path $run "$($s.Name).stop") -Value "stop"
            $deadline = (Get-Date).AddSeconds(60)
            while ((Get-Supervised $s.Name) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
            Write-Output "$($s.Name): $(if (Get-Supervised $s.Name) { 'STILL RUNNING' } else { 'stopped' })"
        }
    }
    "status" {
        foreach ($s in $services) {
            $info = Get-Supervised $s.Name
            $task = Get-ScheduledTask -TaskName $s.Task -TaskPath $TaskPath -ErrorAction SilentlyContinue
            $state = if ($task) { $task.State } else { "not registered" }
            if ($info) { Write-Output ("{0,-9} running  supervisor {1}, child {2}, restarts {3}, task {4}" -f $s.Name, $info.supervisor, $info.child, $info.restarts, $state) }
            else { Write-Output ("{0,-9} stopped  task {1}" -f $s.Name, $state) }
        }
        try { $r = Invoke-WebRequest "http://127.0.0.1:$BackendPort/health/ready" -UseBasicParsing -TimeoutSec 5; Write-Output "backend ready: $($r.Content)" }
        catch { Write-Output "backend ready: NOT READY ($($_.Exception.Message))" }
    }
}
