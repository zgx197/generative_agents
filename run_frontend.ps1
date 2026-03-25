[CmdletBinding()]
param(
  [string]$PythonExe = "python",
  [Parameter(Mandatory = $true)]
  [string]$FrontendDir,
  [Parameter(Mandatory = $true)]
  [string]$LogsDir,
  [int]$Port = 8000
)

$ErrorActionPreference = "Continue"
$FrontendLog = Join-Path $LogsDir "frontend.log"
$FrontendRuntimeLog = Join-Path $LogsDir "frontend.runtime.log"
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
New-Item -ItemType File -Force -Path $FrontendLog | Out-Null
New-Item -ItemType File -Force -Path $FrontendRuntimeLog | Out-Null
Trim-LogFile -Path $FrontendLog -MaxLines $LogMaxLines
Trim-LogFile -Path $FrontendRuntimeLog -MaxLines $LogMaxLines
Set-Location -LiteralPath $FrontendDir
$env:GA_FRONTEND_RUNTIME_LOG_MAX_LINES = "$LogMaxLines"

Add-Content -Path $FrontendLog -Value ("`r`n===== [{0}] frontend start =====" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Start-Transcript -Path $FrontendLog -Append | Out-Null
try {
  & $PythonExe manage.py runserver ("127.0.0.1:{0}" -f $Port)
}
finally {
  Stop-Transcript | Out-Null
}

exit $LASTEXITCODE
