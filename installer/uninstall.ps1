# Removes Orbitick (run by Settings > Apps > Uninstall). Your settings in %APPDATA%\Orbitick are kept.
param([switch]$Quiet)
$ErrorActionPreference = "SilentlyContinue"
$name = "Orbitick"
# Always the fixed install folder, never wherever this script happens to be.
$target = Join-Path $env:LOCALAPPDATA "Programs\$name"

Get-Process -Name $name | Stop-Process -Force
Get-Process -Name $name | Wait-Process -Timeout 10

Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name $name
Remove-Item (Join-Path ([Environment]::GetFolderPath("Programs")) "$name.lnk") -Force
Remove-Item (Join-Path ([Environment]::GetFolderPath("Desktop")) "$name.lnk") -Force
Remove-Item "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$name" -Recurse -Force
foreach ($ext in @(".orbitickpreset", ".cadencepreset")) { Remove-Item "HKCU:\Software\Classes\$ext" -Recurse -Force }
Remove-Item "HKCU:\Software\Classes\$name.Preset" -Recurse -Force

Set-Location $env:TEMP
if (Test-Path (Join-Path $target "$name.exe")) { Remove-Item $target -Recurse -Force }

if ($Quiet) { return }
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.MessageBox]::Show(
    "Orbitick has been uninstalled.`n`nYour settings remain in $env:APPDATA\$name and will be used if you reinstall.",
    $name) | Out-Null
