#Requires -Version 7.0
param(
    [ValidateSet('Plan','Prepare','Tasks','Resolve','Metadata','NativeX64','NativeArm64','Publish','PublishLocal','Verify')]
    [string] $Stage = 'Plan',
    [string] $Python = 'python',
    [int] $Attempt = 1,
    [switch] $Online,
    [Parameter(ValueFromRemainingArguments = $true)] [string[]] $PortArguments
)
$ErrorActionPreference = 'Stop'
$gridArguments = @('-B', (Join-Path $PSScriptRoot 'GridPort.py'), $Stage, '--attempt', $Attempt)
if ($Online) { $gridArguments += '--online' }
$gridArguments += $PortArguments
& $Python @gridArguments
if ($LASTEXITCODE -ne 0) { throw "Grid $Stage failed (exit $LASTEXITCODE)" }
