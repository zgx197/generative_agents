[CmdletBinding()]
param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$ArgsList
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSCommandPath
$CheckScript = Join-Path $RepoRoot "check_startup.ps1"
$StartScript = Join-Path $RepoRoot "start_game.ps1"

function Get-OptionValue {
  param(
    [string[]]$Tokens,
    [string]$OptionName
  )

  for ($i = 0; $i -lt $Tokens.Count; $i++) {
    if ($Tokens[$i] -ieq $OptionName) {
      if ($i + 1 -lt $Tokens.Count) {
        return $Tokens[$i + 1]
      }
      throw "Option $OptionName requires a value."
    }
  }

  return $null
}

$Mode = "start"
$ForwardArgs = @($ArgsList)

if ($ForwardArgs.Count -gt 0 -and $ForwardArgs[0] -ieq "--check") {
  $Mode = "check_and_start"
  if ($ForwardArgs.Count -gt 1) {
    $ForwardArgs = @($ForwardArgs[1..($ForwardArgs.Count - 1)])
  } else {
    $ForwardArgs = @()
  }
} elseif ($ForwardArgs.Count -gt 0 -and $ForwardArgs[0] -ieq "--check-only") {
  $Mode = "check_only"
  if ($ForwardArgs.Count -gt 1) {
    $ForwardArgs = @($ForwardArgs[1..($ForwardArgs.Count - 1)])
  } else {
    $ForwardArgs = @()
  }
}

if ($Mode -ne "start") {
  $CheckArgs = @()
  $PythonExe = Get-OptionValue -Tokens $ForwardArgs -OptionName "-PythonExe"
  $ForkedSimulation = Get-OptionValue -Tokens $ForwardArgs -OptionName "-ForkedSimulation"

  if ($PythonExe) {
    $CheckArgs += @("-PythonExe", $PythonExe)
  }
  if ($ForkedSimulation) {
    $CheckArgs += @("-ForkedSimulation", $ForkedSimulation)
  }

  & $CheckScript @CheckArgs
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
}

if ($Mode -eq "check_only") {
  exit 0
}

& $StartScript @ForwardArgs
exit $LASTEXITCODE
