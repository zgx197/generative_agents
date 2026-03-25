[CmdletBinding()]
param(
  [int]$TailLines = 200,
  [int]$Context = 20,
  [int]$MaxBlocks = 8,
  [string]$OutputPath
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSCommandPath
$LogsDir = Join-Path $RepoRoot "logs"

if (-not $OutputPath) {
  $OutputPath = Join-Path $LogsDir "error_summary.txt"
}

New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

$ErrorPatterns = @(
  'Traceback \(most recent call last\):',
  '\b[A-Za-z]+Error:',
  '\bException:',
  '\bCRITICAL\b',
  '\bERROR\b',
  'TemplateSyntaxError',
  'TOKEN LIMIT EXCEEDED'
)

function Test-ErrorLine {
  param([string]$Line)
  foreach ($Pattern in $ErrorPatterns) {
    if ($Line -match $Pattern) {
      return $true
    }
  }
  return $false
}

function Merge-Ranges {
  param([System.Collections.Generic.List[object]]$Ranges)

  if ($Ranges.Count -eq 0) {
    return @()
  }

  $Sorted = $Ranges | Sort-Object Start, End
  $Merged = New-Object System.Collections.Generic.List[object]
  $Current = [pscustomobject]@{ Start = $Sorted[0].Start; End = $Sorted[0].End }

  for ($i = 1; $i -lt $Sorted.Count; $i++) {
    $Item = $Sorted[$i]
    if ($Item.Start -le ($Current.End + 1)) {
      if ($Item.End -gt $Current.End) {
        $Current.End = $Item.End
      }
    } else {
      $Merged.Add([pscustomobject]@{ Start = $Current.Start; End = $Current.End })
      $Current = [pscustomobject]@{ Start = $Item.Start; End = $Item.End }
    }
  }

  $Merged.Add([pscustomobject]@{ Start = $Current.Start; End = $Current.End })
  return $Merged
}

function Build-LogSummary {
  param(
    [string]$Name,
    [string]$Path
  )

  $Section = New-Object System.Collections.Generic.List[string]
  $Section.Add(("===== {0} =====" -f $Name))
  $Section.Add(("Path: {0}" -f $Path))

  if (-not (Test-Path $Path)) {
    $Section.Add("Status: log file not found")
    $Section.Add("")
    return $Section
  }

  $Lines = @(Get-Content -Path $Path -Tail $TailLines)
  $Section.Add(("Tail lines scanned: {0}" -f $Lines.Count))

  if ($Lines.Count -eq 0) {
    $Section.Add("Status: log file is empty")
    $Section.Add("")
    return $Section
  }

  $HitRanges = New-Object System.Collections.Generic.List[object]
  for ($i = 0; $i -lt $Lines.Count; $i++) {
    if (Test-ErrorLine -Line $Lines[$i]) {
      $Start = [Math]::Max(0, $i - $Context)
      $End = [Math]::Min($Lines.Count - 1, $i + $Context)
      $HitRanges.Add([pscustomobject]@{ Start = $Start; End = $End })
    }
  }

  $MergedRanges = @(Merge-Ranges -Ranges $HitRanges)
  if ($MergedRanges.Count -gt $MaxBlocks) {
    $MergedRanges = @($MergedRanges | Select-Object -Last $MaxBlocks)
  }

  if ($MergedRanges.Count -eq 0) {
    $Section.Add("No error-like lines found. Recent tail:")
    foreach ($Line in ($Lines | Select-Object -Last ([Math]::Min(40, $Lines.Count)))) {
      $Section.Add($Line)
    }
    $Section.Add("")
    return $Section
  }

  for ($RangeIndex = 0; $RangeIndex -lt $MergedRanges.Count; $RangeIndex++) {
    $Range = $MergedRanges[$RangeIndex]
    $Section.Add(("Block {0} (lines {1}-{2})" -f ($RangeIndex + 1), ($Range.Start + 1), ($Range.End + 1)))
    for ($LineIndex = $Range.Start; $LineIndex -le $Range.End; $LineIndex++) {
      $Section.Add($Lines[$LineIndex])
    }
    $Section.Add("")
  }

  return $Section
}

$ReportLines = New-Object System.Collections.Generic.List[string]
$ReportLines.Add(("Generated: {0}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss")))
$ReportLines.Add(("Logs dir: {0}" -f $LogsDir))
$ReportLines.Add("")

$FrontendPath = Join-Path $LogsDir "frontend.log"
$BackendPath = Join-Path $LogsDir "backend.log"
$BackendRuntimePath = Join-Path $LogsDir "backend.runtime.log"

foreach ($Line in (Build-LogSummary -Name "frontend.log" -Path $FrontendPath)) {
  $ReportLines.Add($Line)
}

foreach ($Line in (Build-LogSummary -Name "backend.log" -Path $BackendPath)) {
  $ReportLines.Add($Line)
}

foreach ($Line in (Build-LogSummary -Name "backend.runtime.log" -Path $BackendRuntimePath)) {
  $ReportLines.Add($Line)
}

$ReportText = $ReportLines -join [Environment]::NewLine
Set-Content -Path $OutputPath -Value $ReportText -Encoding utf8
$ReportText
