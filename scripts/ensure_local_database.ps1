param(
    [string]$PostgresEnvFile = '',
    [int]$DockerWaitSeconds = 180
)

$ErrorActionPreference = 'Stop'
$backendDir = Split-Path -Parent $PSScriptRoot
if (-not $PostgresEnvFile) { $PostgresEnvFile = Join-Path $backendDir 'deploy\postgres\.env' }
$composeFile = Join-Path $backendDir 'deploy\postgres\compose.yaml'
$tailscaleExe = 'C:\Program Files\Tailscale\tailscale.exe'

foreach ($path in @($PostgresEnvFile, $composeFile, $tailscaleExe)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required database bootstrap file is missing: $path" }
}

$values = @{}
foreach ($line in Get-Content -LiteralPath $PostgresEnvFile) {
    if ($line -match '^([^#=]+)=(.*)$') {
        $values[$Matches[1].Trim()] = $Matches[2].Trim().Trim('"').Trim("'")
    }
}
$portText = $values['VISIONFLOW_POSTGRES_PORT']
if ($portText -notmatch '^\d{1,5}$') { throw 'VISIONFLOW_POSTGRES_PORT must be numeric.' }
$postgresPort = [int]$portText

function Invoke-NativeQuiet([string]$Command, [string[]]$Arguments) {
    # Windows PowerShell 5.1 promotes any native stderr output to a
    # NativeCommandError when ErrorActionPreference is Stop. Docker Desktop
    # legitimately writes capability warnings (for example missing blkio
    # throttling support) to stderr even when `docker info` exits with 0.
    # Suppress probe output and decide success exclusively from the native
    # process exit code; PowerShell/cmdlet errors remain terminating elsewhere.
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $Command @Arguments *> $null
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

$deadline = [DateTime]::UtcNow.AddSeconds($DockerWaitSeconds)
do {
    $dockerInfoExitCode = Invoke-NativeQuiet 'docker' @('info')
    if ($dockerInfoExitCode -eq 0) { break }
    if ([DateTime]::UtcNow -ge $deadline) { throw 'Docker Desktop did not become ready before timeout.' }
    Start-Sleep -Seconds 3
} while ($true)

& docker compose --env-file $PostgresEnvFile -f $composeFile up -d
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose could not start PostgreSQL.' }

do {
    $containerHealth = (& docker inspect visionflow-postgres --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' 2>$null).Trim()
    $portReady = Test-NetConnection 127.0.0.1 -Port $postgresPort -InformationLevel Quiet -WarningAction SilentlyContinue
    if ($containerHealth -eq 'healthy' -and $portReady) { break }
    if ([DateTime]::UtcNow -ge $deadline) {
        throw "PostgreSQL did not become healthy on 127.0.0.1:$postgresPort before timeout."
    }
    Start-Sleep -Seconds 2
} while ($true)

& $tailscaleExe serve --bg --tcp=5432 "tcp://127.0.0.1:$postgresPort" *> $null
if ($LASTEXITCODE -ne 0) { throw 'Tailscale Serve could not expose PostgreSQL to the tailnet.' }

Write-Host "PostgreSQL healthy on loopback port $postgresPort; Tailscale Serve TCP 5432 configured."
