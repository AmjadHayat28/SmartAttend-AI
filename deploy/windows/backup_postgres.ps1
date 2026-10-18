<#
.SYNOPSIS
  Back up the SmartClass PostgreSQL database (custom-format pg_dump), verify it, apply retention.

.DESCRIPTION
  - Writes <BackupDir>\<Database>_<yyyyMMdd_HHmmss>.dump (pg_dump -Fc, compressed).
  - The password is read from a file (ACL-restricted) into PGPASSWORD for pg_dump only; it is never
    printed or logged, and is removed from the environment afterwards.
  - Verifies: pg_dump exit code 0, the file exists and is non-empty, and pg_restore can read its
    table of contents. A failed or empty dump is deleted and the script exits with code 1.
  - Optional: -IncludeUploads also zips UPLOAD_DIR (face + classroom photos) next to the dump —
    a database backup without the photos is incomplete.
  - Retention: dumps/zips older than -RetentionDays are deleted (0 = keep everything).
  - Appends one line per run to <LogDir>\backup.log.
  Schedule it (no admin rights needed), e.g. daily at 02:00:
    $a = New-ScheduledTaskAction -Execute powershell.exe -Argument '-NoProfile -ExecutionPolicy Bypass -File D:\Projects\smartclass-attendance\deploy\windows\backup_postgres.ps1 -IncludeUploads'
    Register-ScheduledTask -TaskName 'SmartClass Backup' -TaskPath '\SmartClass\' -Action $a -Trigger (New-ScheduledTaskTrigger -Daily -At 2am)
#>
param(
    [string]$DeployRoot = "D:\SmartClassDeploy",
    [string]$Database = "smartclass_phase11",
    [string]$DbUser = "smartclass_app",
    [string]$DbHost = "127.0.0.1",
    [int]$Port = 5432,
    [string]$PasswordFile = "",
    [string]$BackupDir = "",
    [string]$UploadDir = "",
    [int]$RetentionDays = 14,
    [switch]$IncludeUploads
)
$ErrorActionPreference = "Stop"
if (-not $PasswordFile) { $PasswordFile = Join-Path $DeployRoot "config\postgres-app.secret" }
if (-not $BackupDir) { $BackupDir = Join-Path $DeployRoot "backups" }
if (-not $UploadDir) { $UploadDir = Join-Path $DeployRoot "uploads" }
$pgBin = Join-Path $DeployRoot "bin\pgsql\bin"
$logDir = Join-Path $DeployRoot "logs"
New-Item -ItemType Directory -Force $BackupDir, $logDir | Out-Null
$log = Join-Path $logDir "backup.log"
function Log([string]$msg) { "$(Get-Date -Format o) $msg" | Add-Content -Path $log -Encoding utf8; Write-Output $msg }

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$dump = Join-Path $BackupDir "${Database}_$stamp.dump"
$started = Get-Date
try {
    if (-not (Test-Path $PasswordFile)) { throw "password file not found" }
    $env:PGPASSWORD = (Get-Content $PasswordFile -Raw).Trim()
    & (Join-Path $pgBin "pg_dump.exe") -h $DbHost -p $Port -U $DbUser -d $Database -Fc --no-owner -f $dump 2>&1 |
        ForEach-Object { if ($_ -is [System.Management.Automation.ErrorRecord]) { Log "pg_dump: $_" } }
    if ($LASTEXITCODE -ne 0) { throw "pg_dump exited with code $LASTEXITCODE" }
    if (-not (Test-Path $dump) -or (Get-Item $dump).Length -eq 0) { throw "dump file missing or empty" }
    $toc = & (Join-Path $pgBin "pg_restore.exe") --list $dump 2>$null
    if ($LASTEXITCODE -ne 0 -or -not ($toc -match "TABLE DATA")) { throw "pg_restore cannot read the dump" }
    $tables = ($toc | Select-String "TABLE DATA").Count
    $size = (Get-Item $dump).Length
    $hash = (Get-FileHash $dump -Algorithm SHA256).Hash
    Log ("OK database={0} file={1} size={2:N0} bytes tables={3} sha256={4} seconds={5:N1}" -f $Database, (Split-Path $dump -Leaf), $size, $tables, $hash, ((Get-Date) - $started).TotalSeconds)
    if ($IncludeUploads) {
        $zip = Join-Path $BackupDir "uploads_$stamp.zip"
        Compress-Archive -Path (Join-Path $UploadDir "*") -DestinationPath $zip -CompressionLevel Optimal
        Log ("OK uploads file={0} size={1:N0} bytes files={2}" -f (Split-Path $zip -Leaf), (Get-Item $zip).Length, (Get-ChildItem $UploadDir -Recurse -File).Count)
    }
} catch {
    Remove-Item $dump -ErrorAction SilentlyContinue
    Log "FAILED database=$Database error=$($_.Exception.Message)"
    exit 1
} finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}

if ($RetentionDays -gt 0) {
    $cutoff = (Get-Date).AddDays(-$RetentionDays)
    Get-ChildItem $BackupDir -File | Where-Object { $_.Extension -in ".dump", ".zip" -and $_.LastWriteTime -lt $cutoff } | ForEach-Object {
        Remove-Item $_.FullName
        Log "retention: deleted $($_.Name)"
    }
}
exit 0
