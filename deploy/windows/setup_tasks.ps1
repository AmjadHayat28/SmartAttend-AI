<#
.SYNOPSIS
  Registers the SmartClass production processes as Windows Task Scheduler tasks (no administrator
  rights needed): PostgreSQL, the FastAPI backend (uvicorn) and the Caddy reverse proxy.

.DESCRIPTION
  Each task starts at logon of the current user and runs deploy\windows\supervise.py with
  pythonw.exe (no console window). The supervisor restarts its process on any exit (backoff
  1 s … 30 s), writes rotated logs to <DeployRoot>\logs and stops cleanly via a stop file
  (see control.ps1). Task Scheduler itself restarts a failed supervisor every minute.

  Limitation (no admin rights): tasks run only while this user is logged on. With admin rights,
  register the same supervisor command lines as Windows services (e.g. NSSM/WinSW) or set the
  tasks to "run whether the user is logged on or not" so they start at boot.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File deploy\windows\setup_tasks.ps1
  powershell -ExecutionPolicy Bypass -File deploy\windows\setup_tasks.ps1 -Unregister
#>
param(
    [string]$DeployRoot = "D:\SmartClassDeploy",
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    # Measured on Windows (Phase 11): 1 worker ≈ 1.3 GB private memory; 2 workers ≈ 2.1 GB with no
    # throughput gain (uvicorn workers do not share load evenly on Windows and one recognition
    # already uses ~4 CPU threads). Use more workers only on Linux and with RAM to spare.
    [ValidateRange(1, 8)][int]$Workers = 1,
    [int]$BackendPort = 8001,
    [string]$Site = "localhost",
    [switch]$Unregister
)
$ErrorActionPreference = "Stop"
if ($DeployRoot -match "\s") { throw "DeployRoot must not contain spaces (stop commands run through cmd.exe unquoted)." }
$TaskPath = "\SmartClass\"
$names = @("SmartClass PostgreSQL", "SmartClass Backend", "SmartClass Proxy")

if ($Unregister) {
    foreach ($n in $names) { Unregister-ScheduledTask -TaskName $n -TaskPath $TaskPath -Confirm:$false -ErrorAction SilentlyContinue }
    Write-Output "Unregistered SmartClass tasks."
    return
}

$pythonw = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$supervise = Join-Path $ProjectRoot "deploy\windows\supervise.py"
$caddyfile = Join-Path $ProjectRoot "deploy\windows\Caddyfile"
$envFile = Join-Path $DeployRoot "config\production.env"
$pgBin = Join-Path $DeployRoot "bin\pgsql\bin"
$pgData = Join-Path $DeployRoot "pgdata"
$caddy = Join-Path $DeployRoot "bin\caddy.exe"
foreach ($p in @($pythonw, $supervise, $caddyfile, $envFile, (Join-Path $pgBin "postgres.exe"), $pgData, $caddy)) {
    if (-not (Test-Path $p)) { throw "Missing: $p" }
}
$run = Join-Path $DeployRoot "run"; $logs = Join-Path $DeployRoot "logs"
New-Item -ItemType Directory -Force $run, $logs | Out-Null

function Sup([string]$name, [string]$cwd, [string[]]$envs, [string]$stop, [string]$command) {
    $a = "`"$supervise`" --name $name --run-dir `"$run`" --log-dir `"$logs`" --cwd `"$cwd`""
    foreach ($e in $envs) { $a += " --env `"$e`"" }
    if ($stop) { $a += " --stop-command `"$stop`"" }
    return "$a -- $command"
}

$tasks = [ordered]@{
    "SmartClass PostgreSQL" = Sup "postgres" $DeployRoot @() "$pgBin\pg_ctl.exe stop -D $pgData -m fast" `
        "`"$pgBin\postgres.exe`" -D `"$pgData`""
    "SmartClass Backend"    = Sup "backend" $ProjectRoot @("SMARTCLASS_ENV_FILE=$envFile") $null `
        ("`"$python`" -m uvicorn backend.app.main:app --host 127.0.0.1 --port $BackendPort --workers $Workers " +
         "--proxy-headers --forwarded-allow-ips 127.0.0.1 --no-server-header --timeout-graceful-shutdown 10")
    "SmartClass Proxy"      = Sup "caddy" $DeployRoot @("SMARTCLASS_SITE=$Site", "SMARTCLASS_WWW=$DeployRoot\www",
        "SMARTCLASS_BACKEND=127.0.0.1:$BackendPort", "SMARTCLASS_LOGS=$logs", "SMARTCLASS_CADDY_DATA=$DeployRoot\caddy-data") `
        "$caddy stop" "`"$caddy`" run --config `"$caddyfile`" --adapter caddyfile"
}

$user = "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew -Hidden
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
foreach ($name in $tasks.Keys) {
    $action = New-ScheduledTaskAction -Execute $pythonw -Argument $tasks[$name] -WorkingDirectory $DeployRoot
    Register-ScheduledTask -TaskName $name -TaskPath $TaskPath -Action $action -Trigger $trigger -Settings $settings `
        -Principal $principal -Description "SmartClass (supervised; logs in $logs)" -Force | Out-Null
    Write-Output "Registered $TaskPath$name"
}
Write-Output "Start now with: powershell -File `"$PSScriptRoot\control.ps1`" start"
