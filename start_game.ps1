[CmdletBinding()]
param(
  [string]$PythonExe = "python",
  [string]$ForkedSimulation = "base_the_ville_isabella_maria_klaus",
  [string]$NewSimulation,
  [int]$Port = 8000,
  [switch]$SkipMigrate,
  [switch]$NoBrowser,
  [switch]$NoWindowsTerminal
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSCommandPath
$FrontendDir = Join-Path $RepoRoot "environment\frontend_server"
$BackendDir = Join-Path $RepoRoot "reverie\backend_server"
$StorageDir = Join-Path $FrontendDir "storage"
$LogsDir = Join-Path $RepoRoot "logs"
$AiConfigPath = Join-Path $RepoRoot "config\ai_config.local.json"
$FrontendLog = Join-Path $LogsDir "frontend.log"
$BackendLog = Join-Path $LogsDir "backend.log"
$RunFrontendScript = Join-Path $RepoRoot "run_frontend.ps1"
$RunBackendScript = Join-Path $RepoRoot "run_backend.ps1"
$WindowsPowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$WindowsTerminal = Get-Command wt -ErrorAction SilentlyContinue

if (-not (Test-Path $FrontendDir)) {
  throw "Frontend directory not found: $FrontendDir"
}

if (-not (Test-Path $BackendDir)) {
  throw "Backend directory not found: $BackendDir"
}

if (-not (Test-Path $WindowsPowerShell)) {
  throw "powershell.exe not found: $WindowsPowerShell"
}

function ConvertTo-ProcessArgumentString {
  param(
    [Parameter(Mandatory = $true)]
    [object[]]$Arguments
  )

  $escaped = foreach ($arg in $Arguments) {
    if ($null -eq $arg) {
      '""'
      continue
    }

    $text = [string]$arg
    if ($text.Length -eq 0) {
      '""'
      continue
    }

    if ($text -match '[\s"]') {
      '"' + ($text -replace '(\\*)"', '$1$1\"') + '"'
    } else {
      $text
    }
  }

  return ($escaped -join " ")
}

function Start-GameHosts {
  if ($WindowsTerminal -and -not $NoWindowsTerminal) {
    Write-Host "Starting frontend and backend in Windows Terminal..."
    $frontendWtArgs = @(
      "-w", "new",
      "new-tab",
      "--title", "AgentTown Frontend",
      "--startingDirectory", $FrontendDir,
      $WindowsPowerShell,
      "-NoExit",
      "-ExecutionPolicy", "Bypass",
      "-File", $RunFrontendScript,
      "-PythonExe", $PythonExe,
      "-FrontendDir", $FrontendDir,
      "-LogsDir", $LogsDir,
      "-Port", $Port
    )
    $backendWtArgs = @(
      "-w", "last",
      "new-tab",
      "--title", "AgentTown Backend",
      "--startingDirectory", $BackendDir,
      $WindowsPowerShell,
      "-NoExit",
      "-ExecutionPolicy", "Bypass",
      "-File", $RunBackendScript,
      "-PythonExe", $PythonExe,
      "-BackendDir", $BackendDir,
      "-LogsDir", $LogsDir,
      "-ForkedSimulation", $ForkedSimulation,
      "-NewSimulation", $NewSimulation
    )

    Start-Process -FilePath $WindowsTerminal.Source -ArgumentList (ConvertTo-ProcessArgumentString -Arguments $frontendWtArgs) | Out-Null
    Start-Sleep -Milliseconds 800
    Start-Process -FilePath $WindowsTerminal.Source -ArgumentList (ConvertTo-ProcessArgumentString -Arguments $backendWtArgs) | Out-Null
    return "Windows Terminal"
  }

  if (-not $NoWindowsTerminal) {
    Write-Warning "wt.exe not found. Falling back to classic PowerShell windows."
  }

  Write-Host "Starting frontend server window..."
  Start-Process -FilePath $WindowsPowerShell `
    -WorkingDirectory $FrontendDir `
    -ArgumentList @(
      "-NoExit",
      "-ExecutionPolicy", "Bypass",
      "-File", $RunFrontendScript,
      "-PythonExe", $PythonExe,
      "-FrontendDir", $FrontendDir,
      "-LogsDir", $LogsDir,
      "-Port", $Port
    ) | Out-Null

  Start-Sleep -Seconds 2

  Write-Host "Starting backend server window..."
  Start-Process -FilePath $WindowsPowerShell `
    -WorkingDirectory $BackendDir `
    -ArgumentList @(
      "-NoExit",
      "-ExecutionPolicy", "Bypass",
      "-File", $RunBackendScript,
      "-PythonExe", $PythonExe,
      "-BackendDir", $BackendDir,
      "-LogsDir", $LogsDir,
      "-ForkedSimulation", $ForkedSimulation,
      "-NewSimulation", $NewSimulation
    ) | Out-Null

  return "Classic PowerShell"
}

$null = Get-Command $PythonExe -ErrorAction Stop
New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null
New-Item -ItemType File -Force -Path $FrontendLog | Out-Null
New-Item -ItemType File -Force -Path $BackendLog | Out-Null

if (-not $NewSimulation) {
  $NewSimulation = "local-" + (Get-Date -Format "yyyyMMdd-HHmmss")
}

$ForkedSimPath = Join-Path $StorageDir $ForkedSimulation
$NewSimPath = Join-Path $StorageDir $NewSimulation

if (-not (Test-Path $ForkedSimPath)) {
  throw "Forked simulation does not exist: $ForkedSimulation"
}

if (Test-Path $NewSimPath) {
  throw "New simulation already exists: $NewSimulation"
}

if (-not $SkipMigrate) {
  Push-Location $FrontendDir
  try {
    Write-Host "Running Django migrations..."
    Add-Content -Path $FrontendLog -Value ("`r`n===== [{0}] migrate start =====" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
    $migrateOutput = & $PythonExe manage.py migrate 2>&1
    if ($migrateOutput) {
      $migrateOutput | ForEach-Object {
        $line = $_.ToString()
        Write-Host $line
        Add-Content -Path $FrontendLog -Value $line
      }
    }
    if ($LASTEXITCODE -ne 0) {
      throw "manage.py migrate failed with exit code $LASTEXITCODE"
    }
  }
  finally {
    Pop-Location
  }
}

$TerminalHost = Start-GameHosts

if (-not $NoBrowser) {
  Start-Sleep -Seconds 3
  Start-Process "http://127.0.0.1:$Port/simulator_home" | Out-Null
}

Write-Host ""
Write-Host "Startup complete."
Write-Host "Forked simulation : $ForkedSimulation"
Write-Host "New simulation    : $NewSimulation"
Write-Host "Frontend URL      : http://127.0.0.1:$Port/simulator_home"
Write-Host "Terminal host     : $TerminalHost"
Write-Host "Frontend log      : $FrontendLog"
Write-Host "Backend log       : $BackendLog"
Write-Host "AI config         : $AiConfigPath"
Write-Host ""
Write-Host "Next step: in the backend window, run a command like 'run 100' to advance the simulation."
