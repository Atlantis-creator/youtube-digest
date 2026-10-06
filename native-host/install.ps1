<#
Registers the YouTube Digest vault host for Chrome (current user, no admin).

  powershell -ExecutionPolicy Bypass -File install.ps1 -ExtensionId <id> [-VaultRoot <path>]
  powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall

The extension ID is shown on chrome://extensions with Developer mode on.
Run it again after moving this folder: the registry points at this folder.
#>
param(
    [string]$ExtensionId,
    [string]$VaultRoot,
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$HostName = 'com.youtube_digest.vault'
$RegistryKey = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$HostName"
$HostDir = $PSScriptRoot
$Utf8 = New-Object System.Text.UTF8Encoding($false)

if ($Uninstall) {
    if (Test-Path $RegistryKey) { Remove-Item $RegistryKey -Force }
    Write-Output "Removed $RegistryKey"
    return
}

if ($ExtensionId -notmatch '^[a-p]{32}$') {
    throw 'Pass -ExtensionId: the 32-letter ID from chrome://extensions.'
}

$Python = $null
foreach ($candidate in @(@('py', '-3'), @('python'))) {
    try {
        $exe = $candidate[0]
        $rest = @($candidate | Select-Object -Skip 1) + @('-c', 'import sys; print(sys.executable)')
        $found = (& $exe @rest 2>$null | Select-Object -First 1)
        if ($found -and (Test-Path $found)) { $Python = $found.Trim(); break }
    } catch {}
}
if (-not $Python) { throw 'Python 3 was not found (tried py -3 and python).' }

$Launcher = Join-Path $HostDir 'ytd_vault_host.bat'
[IO.File]::WriteAllText($Launcher, "@echo off`r`n`"$Python`" -u `"%~dp0ytd_vault_host.py`" %*`r`n", [Text.Encoding]::ASCII)

$Manifest = Join-Path $HostDir "$HostName.json"
$manifestJson = [ordered]@{
    name            = $HostName
    description     = 'YouTube Digest: land captions in the Obsidian Wiki collection'
    path            = $Launcher
    type            = 'stdio'
    allowed_origins = @("chrome-extension://$ExtensionId/")
} | ConvertTo-Json
[IO.File]::WriteAllText($Manifest, $manifestJson, $Utf8)

if ($VaultRoot) {
    if (-not (Test-Path $VaultRoot -PathType Container)) { throw "Vault not found: $VaultRoot" }
    $config = @{ vaultRoot = $VaultRoot } | ConvertTo-Json
    [IO.File]::WriteAllText((Join-Path $HostDir 'config.json'), $config, $Utf8)
}

New-Item -Path $RegistryKey -Force | Out-Null
Set-Item -Path $RegistryKey -Value $Manifest

Write-Output "Registered $HostName"
Write-Output "  manifest: $Manifest"
Write-Output "  python:   $Python"
if ($VaultRoot) { Write-Output "  vault:    $VaultRoot" }
