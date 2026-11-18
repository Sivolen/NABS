param([int]$Port = 5055)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot 'venv\Scripts\python.exe'
$pgCtl = Join-Path $PSScriptRoot '.local\pgsql\bin\pg_ctl.exe'
& $pgCtl -D "$PSScriptRoot\.local\pgdata" status *> $null
if ($LASTEXITCODE -ne 0) {
    & $pgCtl -D "$PSScriptRoot\.local\pgdata" -l "$PSScriptRoot\.local\postgresql.log" -w start
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL failed to start.' }
}
# Only read-only software inspections are started locally. Restore jobs cannot run.
& $python (Join-Path $PSScriptRoot 'scripts\prepare_restore_schema.py')
if ($LASTEXITCODE -ne 0) { throw 'Restore schema setup failed.' }
$inspectionPidFile = Join-Path $PSScriptRoot '.local\inspection-worker.pid'
$inspectionWorker = $null
if (Test-Path $inspectionPidFile) {
    $inspectionWorker = Get-Process -Id ([int](Get-Content $inspectionPidFile)) -ErrorAction SilentlyContinue
    if ($inspectionWorker -and $inspectionWorker.Path -ne $python) { $inspectionWorker = $null }
}
if (-not $inspectionWorker) {
    $inspectionWorker = Start-Process -FilePath $python -ArgumentList @('restore_worker.py', '--inspect-only') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput "$PSScriptRoot\.local\inspection-worker.stdout.log" -RedirectStandardError "$PSScriptRoot\.local\inspection-worker.stderr.log" -PassThru
    $inspectionWorker.Id | Set-Content $inspectionPidFile
    Start-Sleep -Seconds 1
    $inspectionWorker.Refresh()
    if ($inspectionWorker.HasExited) { throw 'Inspection worker exited. See .local\inspection-worker.stderr.log.' }
}
$pidFile = Join-Path $PSScriptRoot '.local\web.pid'
if (Test-Path $pidFile) {
    $existing = Get-Process -Id ([int](Get-Content $pidFile)) -ErrorAction SilentlyContinue
    if ($existing -and $existing.Path -eq $python) {
        Write-Host "NABS is already running: http://127.0.0.1:$Port"
        exit 0
    }
}
$process = Start-Process -FilePath $python -ArgumentList @('-m', 'flask', '--app', 'app', 'run', '--host', '127.0.0.1', '--port', "$Port", '--no-debugger', '--no-reload') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput "$PSScriptRoot\.local\web.stdout.log" -RedirectStandardError "$PSScriptRoot\.local\web.stderr.log" -PassThru
$process.Id | Set-Content $pidFile
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Seconds 1
    $process.Refresh()
    if ($process.HasExited) { throw 'NABS exited. See .local\web.stderr.log.' }
    try {
        $response = Invoke-WebRequest "http://127.0.0.1:$Port/login" -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) { Write-Host "NABS: http://127.0.0.1:$Port"; exit 0 }
    } catch {}
}
throw 'NABS did not become ready. See .local\web.stderr.log.'
