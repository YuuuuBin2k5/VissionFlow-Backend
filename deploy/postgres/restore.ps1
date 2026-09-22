param(
    [Parameter(Mandatory = $true)]
    [string]$BackupFile
)

$ErrorActionPreference = 'Stop'
$resolvedBackup = (Resolve-Path -LiteralPath $BackupFile).Path
$backupName = Split-Path -Leaf $resolvedBackup

docker cp $resolvedBackup "visionflow-postgres:/tmp/$backupName"
docker exec visionflow-postgres pg_restore `
    --username=postgres `
    --dbname=visionflow `
    --clean `
    --if-exists `
    --no-owner `
    --no-acl `
    "/tmp/$backupName"

Write-Output 'Restore completed. Run Alembic upgrade head and application smoke tests before cutover.'
