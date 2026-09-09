param(
    [string]$ApiBaseUrl = $env:VISIONFLOW_API_BASE_URL,
    [string]$TokenFile = 'D:\VisionFlow\.media_cache\desktop-main.worker-token.dpapi',
    [string]$WorkDir = 'D:\VisionFlowWorker',
    [string]$WorkerId = 'desktop-main',
    [switch]$Check,
    [int]$SoakSeconds = 0
)
$ErrorActionPreference = 'Stop'
if (-not $ApiBaseUrl) { throw 'Provide -ApiBaseUrl or VISIONFLOW_API_BASE_URL (HTTPS backend origin).' }
$backendDir = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $backendDir 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Backend virtualenv Python is missing.' }
$workerSecure = ConvertTo-SecureString -String ((Get-Content -Raw -LiteralPath $TokenFile).Trim())
$env:VISIONFLOW_WORKER_TOKEN = [System.Net.NetworkCredential]::new('', $workerSecure).Password
$env:VISIONFLOW_API_BASE_URL = $ApiBaseUrl
$env:VISIONFLOW_WORKER_ID = $WorkerId
$env:VISIONFLOW_WORKER_WORK_DIR = $WorkDir
$env:PYTHONUTF8 = '1'
$workerArgs = @('-m', 'worker.remote_render_worker')
if ($Check) { $workerArgs += '--check' }
if ($SoakSeconds -gt 0) { $workerArgs += @('--soak-seconds', "$SoakSeconds") }
Push-Location $backendDir
try {
    & $pythonExe @workerArgs
    $workerExit = $LASTEXITCODE
} finally {
    Remove-Item Env:VISIONFLOW_WORKER_TOKEN -ErrorAction SilentlyContinue
    Remove-Variable workerSecure -ErrorAction SilentlyContinue
    Pop-Location
}
exit $workerExit
