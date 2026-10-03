# Exercise the actual frozen launcher, installer, registry PATH and uninstaller.
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path "$PSScriptRoot\..").Path
$Python = (Get-Command python).Source
$Version = (& $Python -c "from vixl import __version__; print(__version__)").Trim()
$Install = Join-Path $env:RUNNER_TEMP 'Vixl installation with spaces'
$Installer = Join-Path $Root "dist\release\Vixl-Setup-$Version-windows-x64.exe"
$OriginalPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$env:VIXL_NO_UPDATE = '1'
try {
    $Process = Start-Process -FilePath $Installer -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=`"$Install`"") -Wait -PassThru
    if ($Process.ExitCode -ne 0) { throw "Installer failed: $($Process.ExitCode)" }
    $NewPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not $NewPath.StartsWith("$Install\bin", [StringComparison]::OrdinalIgnoreCase)) { throw 'Installer did not prepend its user PATH' }
    $env:PATH = "$NewPath;" + $env:PATH
    # Resolve vixl through PATH, as a newly opened terminal would.
    if ((Get-Command vixl).Source -ne "$Install\bin\vixl.exe") { throw 'PATH resolved the wrong Vixl command' }
    if ((vixl --version).Trim() -ne $Version) { throw 'Wrong installed version' }
    vixl new 120x80 -o "$Install\test-project.vixl"
    if ($LASTEXITCODE -ne 0) { throw 'Installed create failed' }
    vixl -p "$Install\test-project.vixl" text add 'Installed' --size 16
    if ($LASTEXITCODE -ne 0) { throw 'Installed font rendering failed' }
    vixl -p "$Install\test-project.vixl" export "$Install\test.png"
    if ($LASTEXITCODE -ne 0) { throw 'Installed export failed' }
    & $Python distribution/test_native_mcp.py "$Install\bin\vixl.exe"
    if ($LASTEXITCODE -ne 0) { throw 'Installed MCP verification failed' }
    vixl updates off
    if ($LASTEXITCODE -ne 0) { throw 'Update preferences failed' }
    $Status = (vixl updates status --json | ConvertFrom-Json)
    if ($Status.automatic -ne $false) { throw 'Preference did not persist' }
    vixl updates on
    & $Python distribution/test_native_update.py "$Install" "dist/release/vixl-$Version-windows-x64.zip"
    if ($LASTEXITCODE -ne 0) { throw 'Native update verification failed' }
    $Process = Start-Process "$Install\unins000.exe" -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') -Wait -PassThru
    if ($Process.ExitCode -ne 0) { throw 'Uninstaller failed' }
    if (Test-Path "$Install\bin\vixl.exe") { throw 'Launcher was not uninstalled' }
    if (-not (Test-Path "$Install\test-project.vixl")) { throw 'Uninstaller removed a user project' }
    if ([Environment]::GetEnvironmentVariable('Path', 'User') -ne $OriginalPath) { throw 'Uninstaller changed unrelated PATH entries' }
} finally {
    [Environment]::SetEnvironmentVariable('Path', $OriginalPath, 'User')
}
