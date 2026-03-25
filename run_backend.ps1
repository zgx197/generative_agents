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
$LogMaxLines = 2000
if ($env:GA_LOG_MAX_LINES) {
  $LogMaxLines = [int]$env:GA_LOG_MAX_LINES
}

function Trim-LogFile {
  param(
    [string]$Path,
    [int]$MaxLines
  )

  try {
    if (-not (Test-Path $Path)) {
      return
    }

    $lines = Get-Content -Path $Path -Tail $MaxLines -ErrorAction SilentlyContinue
    if ($null -eq $lines) {
      return
    }

    Set-Content -Path $Path -Value $lines -Encoding utf8
  }
  catch {
  }
}

New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null
New-Item -ItemType File -Force -Path $BackendLog | Out-Null
New-Item -ItemType File -Force -Path $BackendRuntimeLog | Out-Null
Trim-LogFile -Path $BackendLog -MaxLines $LogMaxLines
Trim-LogFile -Path $BackendRuntimeLog -MaxLines $LogMaxLines
Set-Location -LiteralPath $BackendDir
$env:GA_BACKEND_LOG_PATH = $BackendRuntimeLog
$env:GA_BACKEND_RUNTIME_LOG_MAX_LINES = "$LogMaxLines"

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
