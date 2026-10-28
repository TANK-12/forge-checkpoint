# Install a checked checkpoint zip without replacing an existing Forge.
param(
    [Parameter(Mandatory=$true)][string]$Archive,
    [string]$Destination = (Join-Path $env:LOCALAPPDATA 'Programs\Forge-checkpoint')
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Run this installer on Windows.' }
$archivePath = (Resolve-Path -LiteralPath $Archive).Path
$name = [IO.Path]::GetFileName($archivePath)
if ($name -ne 'forge-0.2.0-windows-x64.zip') { throw 'Choose the Windows x64 checkpoint zip.' }
$Destination = [IO.Path]::GetFullPath($Destination).TrimEnd([char[]]"\/")
if (Test-Path -LiteralPath $Destination) { throw 'Destination already exists; keep it or choose a new folder.' }
$manifest = Join-Path ([IO.Path]::GetDirectoryName($archivePath)) 'SHA256SUMS'
if (!(Test-Path -LiteralPath $manifest)) { throw 'Put SHA256SUMS beside the archive first.' }
$expected = @((Get-Content -LiteralPath $manifest) | Where-Object { $_ -match ('^[a-fA-F0-9]{64}  ' + [regex]::Escape($name) + '$') })
$actual = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash
if ($expected.Count -ne 1 -or $actual -ne $expected[0].Substring(0,64)) { throw 'Checksum does not match. Download the archive again.' }
$stage = Join-Path ([IO.Path]::GetTempPath()) ('forge-install-' + [guid]::NewGuid().ToString('N'))
try {
    Expand-Archive -LiteralPath $archivePath -DestinationPath $stage
    $bundle = Join-Path $stage 'Forge'
    if (!(Test-Path -LiteralPath (Join-Path $bundle 'Forge.cmd'))) { throw 'The archive is incomplete.' }
    $parent = Split-Path -Parent ([IO.Path]::GetFullPath($Destination))
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    Copy-Item -LiteralPath $bundle -Destination $Destination -Recurse
    Write-Output "Installed: $Destination"
    Write-Output 'Double-click Forge.cmd there. Saves live in the data place you pick on first launch.'
} finally {
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
}
