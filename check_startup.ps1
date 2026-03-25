[CmdletBinding()]
param(
  [string]$PythonExe = "python",
  [string]$ForkedSimulation = "base_the_ville_isabella_maria_klaus"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSCommandPath
$FrontendDir = Join-Path $RepoRoot "environment\frontend_server"
$BackendDir = Join-Path $RepoRoot "reverie\backend_server"
$LogsDir = Join-Path $RepoRoot "logs"
$StorageDir = Join-Path $FrontendDir "storage"
$WindowsPowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$ScriptPaths = @(
  (Join-Path $RepoRoot "start_game.ps1"),
  (Join-Path $RepoRoot "run_frontend.ps1"),
  (Join-Path $RepoRoot "run_backend.ps1"),
  (Join-Path $RepoRoot "tail_logs.ps1"),
  (Join-Path $RepoRoot "collect_logs.ps1"),
  (Join-Path $RepoRoot "check_startup.ps1")
)

function Assert-Condition {
  param(
    [bool]$Condition,
    [string]$Message
  )

  if (-not $Condition) {
    throw $Message
  }
}

function Test-PowerShellSyntax {
  param([string]$Path)

  $tokens = $null
  $errors = $null
  [void][System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors)
  if ($errors.Count -gt 0) {
    $msg = ($errors | ForEach-Object { $_.ToString() }) -join "; "
    throw "PowerShell syntax invalid for $Path : $msg"
  }
}

Write-Host "[check] validating workspace paths"
Assert-Condition (Test-Path $FrontendDir) "Frontend directory not found: $FrontendDir"
Assert-Condition (Test-Path $BackendDir) "Backend directory not found: $BackendDir"
Assert-Condition (Test-Path $WindowsPowerShell) "powershell.exe not found: $WindowsPowerShell"

Write-Host "[check] validating startup scripts syntax"
foreach ($ScriptPath in $ScriptPaths) {
  Assert-Condition (Test-Path $ScriptPath) "Startup script not found: $ScriptPath"
  Test-PowerShellSyntax -Path $ScriptPath
}

Write-Host "[check] validating Python command"
$null = Get-Command $PythonExe -ErrorAction Stop

Write-Host "[check] validating logs directory write access"
New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null
$ProbeFile = Join-Path $LogsDir "startup_check_probe.tmp"
Set-Content -Path $ProbeFile -Value "ok" -Encoding utf8
Remove-Item -LiteralPath $ProbeFile -Force

Write-Host "[check] validating forked simulation"
$ForkedSimPath = Join-Path $StorageDir $ForkedSimulation
Assert-Condition (Test-Path $ForkedSimPath) "Forked simulation does not exist: $ForkedSimulation"

Push-Location $FrontendDir
try {
  Write-Host "[check] running Django system check"
  & $PythonExe manage.py check
  if ($LASTEXITCODE -ne 0) {
    throw "manage.py check failed with exit code $LASTEXITCODE"
  }
}
finally {
  Pop-Location
}

Push-Location $BackendDir
try {
  Write-Host "[check] validating Reverie CLI"
  & $PythonExe reverie.py --help | Out-Null
  if ($LASTEXITCODE -ne 0) {
    throw "reverie.py --help failed with exit code $LASTEXITCODE"
  }
}
finally {
  Pop-Location
}

Write-Host ""
Write-Host "Startup self-check passed."
Write-Host ("Python          : {0}" -f $PythonExe)
Write-Host ("Forked sim      : {0}" -f $ForkedSimulation)
Write-Host ("Frontend dir    : {0}" -f $FrontendDir)
Write-Host ("Backend dir     : {0}" -f $BackendDir)
Write-Host ("Logs dir        : {0}" -f $LogsDir)
