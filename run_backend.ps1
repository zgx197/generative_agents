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
$BackendRuntimeLog = Join-Path $LogsDir "backend.runtime.log"

New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null
New-Item -ItemType File -Force -Path $BackendLog | Out-Null
New-Item -ItemType File -Force -Path $BackendRuntimeLog | Out-Null
Set-Location -LiteralPath $BackendDir
$env:GA_BACKEND_LOG_PATH = $BackendRuntimeLog

Add-Content -Path $BackendLog -Value ("`r`n===== [{0}] backend start =====" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Add-Content -Path $BackendRuntimeLog -Value ("`r`n===== [{0}] backend runtime start =====" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Start-Transcript -Path $BackendLog -Append | Out-Null
try {
  & $PythonExe -u reverie.py --forked-sim $ForkedSimulation --new-sim $NewSimulation
}
finally {
  Stop-Transcript | Out-Null
}

exit $LASTEXITCODE
