param(
    [int]$RetentionDays = 14
)

$ErrorActionPreference = 'Stop'
$timestamp = Get-Date -Format 'yyyy-MM-dd-HHmmss'
$backupName = "visionflow-$timestamp.dump"

docker exec visionflow-postgres pg_dump `
    --username=postgres `
    --dbname=visionflow `
    --format=custom `
    --no-owner `
    --no-acl `
    --file="/backups/$backupName"

$backupRoot = (Get-Content "$PSScriptRoot/.env" | Where-Object { $_ -match '^VISIONFLOW_POSTGRES_BACKUPS=' } | Select-Object -First 1) -replace '^VISIONFLOW_POSTGRES_BACKUPS=', ''
if (-not $backupRoot) {
    throw 'VISIONFLOW_POSTGRES_BACKUPS is missing from deploy/postgres/.env'
}

$cutoff = (Get-Date).AddDays(-$RetentionDays)
Get-ChildItem -LiteralPath $backupRoot -Filter 'visionflow-*.dump' -File |
    Where-Object LastWriteTime -lt $cutoff |
    Remove-Item -Force

Write-Output "Backup created: $backupRoot/$backupName"
