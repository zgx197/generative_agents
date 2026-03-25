[CmdletBinding()]
param(
  [ValidateSet("all", "frontend", "frontend-runtime", "backend", "backend-runtime")]
  [string]$Target = "all",
  [int]$Lines = 80,
  [switch]$Follow
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSCommandPath
$LogsDir = Join-Path $RepoRoot "logs"

function Show-LogTail {
  param(
    [string]$Name,
    [int]$TailCount,
    [switch]$WaitForChanges
  )

  $Path = Join-Path $LogsDir "$Name.log"
  Write-Host ("===== {0} =====" -f $Path)
  if (-not (Test-Path $Path)) {
    Write-Host "Log file not found."
    Write-Host ""
    return
  }

  if ($WaitForChanges) {
    Get-Content -Path $Path -Tail $TailCount -Wait
  } else {
    Get-Content -Path $Path -Tail $TailCount
    Write-Host ""
  }
}

if ($Follow -and $Target -eq "all") {
  throw "Use -Follow only with -Target frontend or -Target backend."
}

switch ($Target) {
  "all" {
    Show-LogTail -Name "frontend" -TailCount $Lines
    Show-LogTail -Name "frontend.runtime" -TailCount $Lines
    Show-LogTail -Name "backend" -TailCount $Lines
    Show-LogTail -Name "backend.runtime" -TailCount $Lines
  }
  "frontend" {
    Show-LogTail -Name "frontend" -TailCount $Lines -WaitForChanges:$Follow
  }
  "frontend-runtime" {
    Show-LogTail -Name "frontend.runtime" -TailCount $Lines -WaitForChanges:$Follow
  }
  "backend" {
    Show-LogTail -Name "backend" -TailCount $Lines -WaitForChanges:$Follow
  }
  "backend-runtime" {
    Show-LogTail -Name "backend.runtime" -TailCount $Lines -WaitForChanges:$Follow
  }
}
