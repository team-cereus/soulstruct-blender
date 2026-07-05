<#
    Build a shareable Soulstruct-Blender (Team Cereus) add-on package.

    Produces dist/soulstruct-blender-cereus-<version>-<date>.zip containing the two folders
    the add-on needs side-by-side:
        io_soulstruct/        (the Blender add-on, bl_info entry point)
        io_soulstruct_lib/    (soulstruct + soulstruct-havok libraries, pip-installed on first enable)
    plus INSTALL.txt.

    Usage (from the soulstruct-blender repo root):
        powershell -ExecutionPolicy Bypass -File .\build_cereus_addon.ps1
#>
[CmdletBinding()]
param(
    [string]$Version = "2.6.0"
)

$ErrorActionPreference = "Stop"
$base = $PSScriptRoot
$date = Get-Date -Format "yyyyMMdd"
$pkgName = "soulstruct-blender-cereus-$Version-$date"
$dist = Join-Path $base "dist"
$stage = Join-Path $dist $pkgName

Write-Host "Building $pkgName ..." -ForegroundColor Cyan

if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stage | Out-Null

# Directory names (matched anywhere in tree) and file patterns to exclude from the package.
$excludeDirs = @("__pycache__", ".pytest_cache", ".mypy_cache", ".idea", ".vscode", "build", "dist", ".git", "*.egg-info")
$excludeFiles = @("*.pyc", "*.pyo", "*.pyd.lock", "_tmp_*")

foreach ($folder in @("io_soulstruct", "io_soulstruct_lib")) {
    $src = Join-Path $base $folder
    if (-not (Test-Path $src)) { throw "Source folder not found: $src" }
    $dst = Join-Path $stage $folder
    Write-Host "  Copying $folder ..." -ForegroundColor DarkGray
    robocopy $src $dst /E /XD $excludeDirs /XF $excludeFiles /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed for $folder (exit $LASTEXITCODE)" }
}

$installText = @"
Soulstruct (Team Cereus build) - Blender add-on
================================================

Version: $Version (Cereus packaging $date)
Requires: Blender 4.5 or newer (tested on 5.1).
First-time enable downloads Python dependencies from PyPI -> INTERNET REQUIRED on first enable.

This archive contains TWO folders that MUST sit side-by-side:
    io_soulstruct/        (the add-on)
    io_soulstruct_lib/    (the soulstruct libraries it installs on first enable)

------------------------------------------------------------
INSTALL (recommended - manual copy)
------------------------------------------------------------
1. Fully close Blender.
2. Open your Blender user add-ons folder. On Windows this is typically:
       %APPDATA%\Blender Foundation\Blender\<VERSION>\scripts\addons\
   e.g. for Blender 5.1:
       C:\Users\<you>\AppData\Roaming\Blender Foundation\Blender\5.1\scripts\addons\
   (Create the 'addons' folder if it does not exist.)
3. Copy BOTH 'io_soulstruct' and 'io_soulstruct_lib' from this archive into that 'addons' folder,
   so you end up with:
       ...\scripts\addons\io_soulstruct\
       ...\scripts\addons\io_soulstruct_lib\
4. Start Blender. Open Edit > Preferences > Add-ons, search for "Soulstruct", and enable it.
5. The FIRST enable installs dependencies (numpy, scipy, constrata, rich, typer, zstandard, ...)
   into Blender's local modules folder. This needs internet and may take a minute.
   Tip: open Window > Toggle System Console (Windows) to watch progress.
6. If prompted or if panels do not appear, restart Blender once. Done.

------------------------------------------------------------
INSTALL (alternative - Install from Disk)
------------------------------------------------------------
Edit > Preferences > Add-ons > the v dropdown (top-right) > "Install from Disk..." and pick the .zip.
This is less reliable for this add-on because it must place TWO folders side-by-side; if the add-on
fails to find 'io_soulstruct_lib', use the manual method above.

------------------------------------------------------------
TROUBLESHOOTING
------------------------------------------------------------
- "Cannot find io_soulstruct_lib directory": the two folders are not siblings in 'addons'. Re-do step 3.
- Dependency install errors: ensure Blender has internet access and try enabling again, then restart.
- Find the add-on UI in the 3D Viewport sidebar (press N) under the Soulstruct / Stan's Tools tabs,
  and under File > Import/Export.
"@

Set-Content -Path (Join-Path $stage "INSTALL.txt") -Value $installText -Encoding UTF8

$zipPath = Join-Path $dist "$pkgName.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Write-Host "  Compressing -> $zipPath ..." -ForegroundColor DarkGray
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zipPath -CompressionLevel Optimal

$zipMB = (Get-Item $zipPath).Length / 1MB
Write-Host ("Done: {0} ({1:N1} MB)" -f $zipPath, $zipMB) -ForegroundColor Green
Write-Host "Staging folder kept at: $stage" -ForegroundColor DarkGray
