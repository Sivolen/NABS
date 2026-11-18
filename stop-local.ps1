$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$pidFile = Join-Path $PSScriptRoot '.local\web.pid'
if (Test-Path $pidFile) {
    $process = Get-Process -Id ([int](Get-Content $pidFile)) -ErrorAction SilentlyContinue
    if ($process -and $process.Path -eq (Join-Path $PSScriptRoot 'venv\Scripts\python.exe')) {
        Stop-Process -Id $process.Id
    }
    Remove-Item -LiteralPath $pidFile
}
& "$PSScriptRoot\.local\pgsql\bin\pg_ctl.exe" -D "$PSScriptRoot\.local\pgdata" status *> $null
if ($LASTEXITCODE -eq 0) {
    & "$PSScriptRoot\.local\pgsql\bin\pg_ctl.exe" -D "$PSScriptRoot\.local\pgdata" -m fast -w stop
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL failed to stop.' }
}
Write-Host 'NABS stopped.'
