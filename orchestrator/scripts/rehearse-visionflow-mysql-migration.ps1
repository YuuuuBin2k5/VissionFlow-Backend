param(
    [string]$Image = 'mysql:8.0'
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$container = "visionflow-mysql-d2-rehearsal-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
$migration = Join-Path $PSScriptRoot '..\prisma\migrations\20260716093000_add_visionflow_legacy_intake\migration.sql'

if (-not (Test-Path $migration)) {
    throw "Migration file was not found: $migration"
}

$null = docker run -d --rm --name $container `
    -e MYSQL_ROOT_PASSWORD=visionflow_root_rehearsal `
    -e MYSQL_DATABASE=visionflow_rehearsal `
    -e MYSQL_USER=visionflow_rehearsal `
    -e MYSQL_PASSWORD=visionflow_user_rehearsal `
    $Image

try {
    $ready = $false
    $ErrorActionPreference = 'Continue'
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        docker exec -e MYSQL_PWD=visionflow_user_rehearsal $container `
            mysql -uvisionflow_rehearsal -Dvisionflow_rehearsal -e 'SELECT 1' 2>$null
        if ($LASTEXITCODE -eq 0) {
            $ready = $true
            break
        }
        Start-Sleep -Milliseconds 1000
    }
    $ErrorActionPreference = 'Stop'
    if (-not $ready) { throw 'Disposable MySQL did not become ready.' }

    $bootstrap = @'
CREATE TABLE video_pipeline_jobs (
  id INTEGER NOT NULL AUTO_INCREMENT,
  PRIMARY KEY (id)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
'@
    ($bootstrap + "`n" + (Get-Content $migration -Raw)) |
        docker exec -i -e MYSQL_PWD=visionflow_user_rehearsal $container `
            mysql -uvisionflow_rehearsal -Dvisionflow_rehearsal
    if ($LASTEXITCODE -ne 0) { throw 'Migration rehearsal failed.' }

    @'
SHOW TABLES;
SHOW CREATE TABLE visionflow_job_links;
SHOW CREATE TABLE legacy_outbox;
'@ | docker exec -i -e MYSQL_PWD=visionflow_user_rehearsal $container `
        mysql -uvisionflow_rehearsal -Dvisionflow_rehearsal
    if ($LASTEXITCODE -ne 0) { throw 'Migration verification failed.' }
    Write-Output 'VisionFlow MySQL migration rehearsal passed.'
}
finally {
    docker rm -f $container | Out-Null
}
