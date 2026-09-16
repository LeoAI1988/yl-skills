[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)] [string]$VideoPath,
  [int]$ExpectedWidth = 1080,
  [int]$ExpectedHeight = 1920,
  [double]$ExpectedFps = 30,
  [Nullable[double]]$MaxDurationSec = $null,
  [Nullable[double]]$MaxSilenceSec = $null,
  [switch]$AllowLongSilence,
  [switch]$SkipDecode,
  [switch]$SkipSilenceCheck,
  [string]$FfmpegPath,
  [string]$FfprobePath,
  [string]$PythonPath,
  [int]$ExpectedFrames = 0,
  [Nullable[double]]$ExpectedDurationSec = $null,
  [double]$DurationToleranceSec = 0.005,
  [switch]$ExpectBt709,
  [double]$SilenceThresholdDb = -32,
  [string]$ReferenceAudioPath,
  [string]$ProtectionManifest,
  [string]$ReportPath
)

# Local-only launcher. Existing parameter names remain supported; no npx download.
# Exit 0 = no failed checks (inspect status for PASS versus PARTIAL); exit 1 = FAIL.
$ErrorActionPreference = 'Stop'
try {
  if ($null -eq $MaxSilenceSec) {
    $pausePolicyPath = Join-Path $PSScriptRoot '../references/pause-policy.json'
    $pausePolicy = Get-Content -LiteralPath $pausePolicyPath -Raw -Encoding utf8 | ConvertFrom-Json
    if ($pausePolicy.coordinate -ne 'final_output_seconds') { throw 'pause-policy coordinate must be final_output_seconds' }
    $MaxSilenceSec = [double]$pausePolicy.technicalCandidateSeconds
  }
  if ([double]::IsNaN($MaxSilenceSec) -or [double]::IsInfinity($MaxSilenceSec) -or $MaxSilenceSec -le 0) {
    throw 'MaxSilenceSec must be positive and finite'
  }
  $implementation = Join-Path $PSScriptRoot 'validate-video.py'
  if (-not (Test-Path -LiteralPath $implementation -PathType Leaf)) { throw "Missing validator: $implementation" }
  $pythonPrefix = @()
  if ($PythonPath) {
    if (Test-Path -LiteralPath $PythonPath -PathType Leaf) { $pythonExe = (Resolve-Path -LiteralPath $PythonPath).Path }
    else { $pythonExe = (Get-Command $PythonPath -CommandType Application -ErrorAction Stop).Source }
  } else {
    $pythonCommand = Get-Command python, python3 -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pythonCommand) { $pythonExe = $pythonCommand.Source }
    else {
      $pythonCommand = Get-Command py -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
      if (-not $pythonCommand) { throw 'Python was not found locally. Pass -PythonPath; nothing was installed.' }
      $pythonExe = $pythonCommand.Source
      $pythonPrefix = @('-3')
    }
  }
  $invariant = [System.Globalization.CultureInfo]::InvariantCulture
  $cli = @($implementation, '--video', $VideoPath,
    '--width', [string]$ExpectedWidth, '--height', [string]$ExpectedHeight,
    '--fps', $ExpectedFps.ToString($invariant), '--max-silence', $MaxSilenceSec.ToString($invariant),
    '--silence-db', $SilenceThresholdDb.ToString($invariant),
    '--duration-tolerance', $DurationToleranceSec.ToString($invariant))
  if ($null -ne $MaxDurationSec) { $cli += @('--max-duration', $MaxDurationSec.ToString($invariant)) }
  if ($ExpectedFrames -ne 0) { $cli += @('--frames', [string]$ExpectedFrames) }
  if ($null -ne $ExpectedDurationSec) { $cli += @('--duration', $ExpectedDurationSec.ToString($invariant)) }
  if ($FfmpegPath) { $cli += @('--ffmpeg', $FfmpegPath) }
  if ($FfprobePath) { $cli += @('--ffprobe', $FfprobePath) }
  if ($ReferenceAudioPath) { $cli += @('--reference-audio', $ReferenceAudioPath) }
  if ($ProtectionManifest) { $cli += @('--protection-manifest', $ProtectionManifest) }
  if ($ReportPath) { $cli += @('--report', $ReportPath) }
  if ($AllowLongSilence) { $cli += '--allow-long-silence' }
  if ($SkipDecode) { $cli += '--skip-decode' }
  if ($SkipSilenceCheck) { $cli += '--skip-silence' }
  if ($ExpectBt709) { $cli += '--expect-bt709' }
  & $pythonExe @pythonPrefix @cli
  $validatorExitCode = $LASTEXITCODE
  exit $validatorExitCode
} catch {
  $failure = [ordered]@{ ok = $false; status = 'FAIL'; verificationComplete = $false; videoPath = $VideoPath; errors = @($_.Exception.Message) }
  $failureJson = $failure | ConvertTo-Json -Depth 5
  # The Python implementation owns collision checks and exclusive report creation.
  # A launcher failure is stdout-only; never overwrite an input via ReportPath.
  $failureJson
  exit 1
}
