[CmdletBinding()]
param(
  [string]$PythonExe = "python",
  [Parameter(Mandatory = $true)]
  [string]$BackendDir,
  [Parameter(Mandatory = $true)]
  [string]$LogsDir,
  [Parameter(Mandatory = $true)]
  [string]$ForkedSimulation,
  [Parameter(Mandatory = $true)]
  [string]$NewSimulation
)

$ErrorActionPreference = "Continue"
$BackendLog = Join-Path $LogsDir "backend.log"

New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null
New-Item -ItemType File -Force -Path $BackendLog | Out-Null
Set-Location -LiteralPath $BackendDir
$env:GA_BACKEND_LOG_PATH = $BackendLog

Add-Content -Path $BackendLog -Value ("`r`n===== [{0}] backend start =====" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Start-Transcript -Path $BackendLog -Append | Out-Null
try {
  & $PythonExe -u reverie.py --forked-sim $ForkedSimulation --new-sim $NewSimulation
}
finally {
  Stop-Transcript | Out-Null
}

exit $LASTEXITCODE
