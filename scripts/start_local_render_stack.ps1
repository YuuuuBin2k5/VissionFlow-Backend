param(
    [string]$ApiBaseUrl = $env:VISIONFLOW_API_BASE_URL,
    [string]$PostgresEnvFile = '',
    [switch]$Check,
    [int]$SoakSeconds = 0
)

$ErrorActionPreference = 'Stop'
$backendDir = Split-Path -Parent $PSScriptRoot

# Guard: prevent running two stacks simultaneously
$alreadyRunning = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'start_render_worker\.py' -or $_.CommandLine -match 'remote_render_worker' })
if ($alreadyRunning.Count -gt 0) {
    Write-Warning "Stack da dang chay ($(($alreadyRunning | Select-Object -ExpandProperty ProcessId) -join ', ')). Dung stack cu truoc khi khoi dong lai."
    Write-Warning "De dung stack cu: Stop-Process -Id $($alreadyRunning[0].ProcessId) -Force"
    exit 1
}
if (-not $PostgresEnvFile) {
    $PostgresEnvFile = Join-Path $backendDir 'deploy\postgres\.env'
}
if (-not $ApiBaseUrl) {
    $ApiBaseUrl = 'https://visionflow-control-plane-free.onrender.com'
}

$pythonExe = Join-Path $backendDir 'venv\Scripts\python.exe'
$remoteLauncher = Join-Path $PSScriptRoot 'start_remote_worker.ps1'
$databaseBootstrap = Join-Path $PSScriptRoot 'ensure_local_database.ps1'
$dbCheckScript = Join-Path $PSScriptRoot 'check_local_database.py'
$pipelineScript = Join-Path $backendDir 'start_render_worker.py'
foreach ($requiredPath in @($pythonExe, $remoteLauncher, $databaseBootstrap, $dbCheckScript, $pipelineScript, $PostgresEnvFile)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required local render file is missing: $requiredPath"
    }
}

& $databaseBootstrap -PostgresEnvFile $PostgresEnvFile
if ($LASTEXITCODE -ne 0) { throw 'Local PostgreSQL/Tailscale bootstrap failed.' }

function Read-DotEnvFile([string]$Path) {
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#') -or -not $trimmed.Contains('=')) { continue }
        $name, $value = $trimmed.Split('=', 2)
        $values[$name.Trim()] = $value.Trim().Trim('"').Trim("'")
    }
    return $values
}

$postgres = Read-DotEnvFile $PostgresEnvFile
$dbPassword = $postgres['VISIONFLOW_APP_PASSWORD']
$dbPort = $postgres['VISIONFLOW_POSTGRES_PORT']
if (-not $dbPassword) { throw 'VISIONFLOW_APP_PASSWORD is missing from deploy/postgres/.env.' }
if (-not $dbPort) { throw 'VISIONFLOW_POSTGRES_PORT is missing from deploy/postgres/.env.' }
if ($dbPort -notmatch '^\d{1,5}$' -or [int]$dbPort -lt 1 -or [int]$dbPort -gt 65535) {
    throw 'VISIONFLOW_POSTGRES_PORT must be a valid TCP port.'
}

$encodedPassword = [Uri]::EscapeDataString($dbPassword)
$env:DATABASE_URL = "postgresql+psycopg://visionflow_app:${encodedPassword}@127.0.0.1:${dbPort}/visionflow?sslmode=disable"
$env:DIRECT_DATABASE_URL = $env:DATABASE_URL
$env:MIGRATION_DATABASE_URL = ''
$env:VISIONFLOW_TRUST_LOCAL_DB_PROXY = 'true'
$env:VISIONFLOW_SKIP_DIRECT_RENDER_JOBS = '1'
$env:VISIONFLOW_API_BASE_URL = $ApiBaseUrl
$env:PYTHONUTF8 = '1'

Write-Host '[*] Local pipeline queue: PostgreSQL Docker on 127.0.0.1 (credentials hidden)'
Write-Host '[*] Final render queue: Production Backend over HTTPS'

& $pythonExe $dbCheckScript
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL Docker preflight failed.' }

if ($Check) {
    & $remoteLauncher -ApiBaseUrl $ApiBaseUrl -Check
    exit $LASTEXITCODE
}

$pipeline = $null
$remote = $null
try {
    $pipeline = Start-Process -FilePath $pythonExe -ArgumentList @($pipelineScript, '--loop') -WorkingDirectory $backendDir -NoNewWindow -PassThru

    $remoteArgs = @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $remoteLauncher, '-ApiBaseUrl', $ApiBaseUrl)
    if ($SoakSeconds -gt 0) { $remoteArgs += @('-SoakSeconds', "$SoakSeconds") }
    $remote = Start-Process -FilePath 'powershell.exe' -ArgumentList $remoteArgs -WorkingDirectory $backendDir -NoNewWindow -PassThru

    Write-Host "[*] Pipeline worker PID=$($pipeline.Id)"
    Write-Host "[*] Remote render worker PID=$($remote.Id)"
    Write-Host '[*] Press Ctrl+C to stop the complete local render stack.'

    while (-not $pipeline.HasExited -and -not $remote.HasExited) {
        Start-Sleep -Seconds 1
        $pipeline.Refresh()
        $remote.Refresh()
    }
    if ($pipeline.HasExited -and $pipeline.ExitCode -ne 0) {
        throw "Pipeline worker stopped with exit code $($pipeline.ExitCode)."
    }
    if ($remote.HasExited -and $remote.ExitCode -ne 0) {
        throw "Remote render worker stopped with exit code $($remote.ExitCode)."
    }
} finally {
    foreach ($process in @($pipeline, $remote)) {
        if ($null -ne $process) {
            $process.Refresh()
            if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
        }
    }
    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:DIRECT_DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:MIGRATION_DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:VISIONFLOW_TRUST_LOCAL_DB_PROXY -ErrorAction SilentlyContinue
    Remove-Item Env:VISIONFLOW_SKIP_DIRECT_RENDER_JOBS -ErrorAction SilentlyContinue
}
