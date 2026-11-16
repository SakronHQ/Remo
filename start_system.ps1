<#
.SYNOPSIS
SmartVision One-Click System Launcher (PowerShell)
Phase 9: Production Packaging & Handover

.DESCRIPTION
Launches the SmartVision multi-tier stack (Backend Gateway + Operator Dashboard + Optional Mock Hardware).

.PARAMETER MockHardware
Starts emulated ESP32-S3 firmware client for zero-hardware workstation testing.

.PARAMETER Synthetic
Forces synthetic test video stream (no physical webcam required).

.PARAMETER CheckOnly
Runs preflight environment checks and exits cleanly.

.EXAMPLE
.\start_system.ps1 -MockHardware -Synthetic
#>
[CmdletBinding(PositionalBinding = $false)]
param(
    [switch]$MockHardware,
    [switch]$Synthetic,
    [switch]$CheckOnly,
    [switch]$NoFrontend,
    [string]$HostAddress = "0.0.0.0",
    [int]$Port = 8000,
    [int]$FrontendPort = 3000,
    [Alias("DetectorMode")][string]$Detector = "face",
    [int]$CameraIndex = -1,
    [switch]$DebugMode,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$SmartvisionDir = if (Test-Path "$ScriptDir\smartvision\run_system.py") { "$ScriptDir\smartvision" } else { $ScriptDir }
$VenvPy = "$SmartvisionDir\.venv\Scripts\python.exe"

$PyExe = if (Test-Path $VenvPy) { $VenvPy } else { "python" }

$ArgsList = @("$SmartvisionDir\run_system.py")

if ($MockHardware) { $ArgsList += "--mock-esp32" }
if ($Synthetic) { $ArgsList += "--synthetic" }
if ($CheckOnly) { $ArgsList += "--check-only" }
if ($NoFrontend) { $ArgsList += "--no-frontend" }
if ($HostAddress -ne "0.0.0.0") { $ArgsList += @("--host", $HostAddress) }
if ($Port -ne 8000) { $ArgsList += @("--port", $Port) }
if ($FrontendPort -ne 3000) { $ArgsList += @("--frontend-port", $FrontendPort) }
if ($Detector -and -not ($ExtraArgs -and ($ExtraArgs -contains "--detector" -or $ExtraArgs -contains "-Detector" -or $ExtraArgs -contains "--detector-mode"))) { 
    $ArgsList += @("--detector", $Detector) 
}
if ($CameraIndex -ge 0) { $ArgsList += @("--camera-index", $CameraIndex) }
if ($DebugMode) { $ArgsList += "--debug" }
if ($ExtraArgs) { $ArgsList += $ExtraArgs }

& $PyExe @ArgsList
