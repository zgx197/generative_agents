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

New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null
New-Item -ItemType File -Force -Path $FrontendLog | Out-Null
Set-Location -LiteralPath $FrontendDir

Add-Content -Path $FrontendLog -Value ("`r`n===== [{0}] frontend start =====" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Start-Transcript -Path $FrontendLog -Append | Out-Null
try {
  & $PythonExe manage.py runserver ("127.0.0.1:{0}" -f $Port)
}
finally {
  Stop-Transcript | Out-Null
}

exit $LASTEXITCODE
