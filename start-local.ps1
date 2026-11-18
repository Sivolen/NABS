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
