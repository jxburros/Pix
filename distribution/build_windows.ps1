$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $Root
$Version = (python -c "from pix import __version__; print(__version__)").Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot determine Pix version' }
python -m PyInstaller --noconfirm --clean --onefile --name pix --paths src/pix --distpath dist/launcher --workpath build/launcher --specpath build distribution/launcher.py
if ($LASTEXITCODE -ne 0) { throw 'Launcher build failed' }
python -m PyInstaller --noconfirm --clean --onedir --name pix-engine --collect-data pix --collect-all uvicorn --collect-submodules mcp.server --collect-data mcp --copy-metadata mcp --copy-metadata pix-engine --distpath dist/runtime --workpath build/engine --specpath build distribution/engine.py
if ($LASTEXITCODE -ne 0) { throw 'Engine build failed' }
& "$Root\dist\runtime\pix-engine\pix-engine.exe" --pix-healthcheck
if ($LASTEXITCODE -ne 0) { throw 'Frozen runtime health check failed' }
python distribution/package_release.py
if ($LASTEXITCODE -ne 0) { throw 'Release packaging failed' }
$Compiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $Compiler)) { throw 'Inno Setup 6 is required to build the installer' }
& $Compiler "/DPixVersion=$Version" "/DSourceRoot=$Root" distribution/windows/pix.iss
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
python distribution/package_release.py --checksums
if ($LASTEXITCODE -ne 0) { throw 'Checksum generation failed' }
