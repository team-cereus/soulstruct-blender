<#
    One-shot installer for Soulstruct for Blender (Team Cereus fork) + Stan's Tools, with auto-update.

    Run in PowerShell (no admin needed):
        irm https://raw.githubusercontent.com/team-cereus/soulstruct-blender/main/installer/install.ps1 | iex

    Running it again repairs / updates the install. What it does:
      1. Installs Git (via winget) if it is missing.
      2. Clones this repo + its two library submodules into %LOCALAPPDATA%\StanTools\soulstruct-blender
         (or fast-forwards an existing clone).
      3. Links `io_soulstruct` + `io_soulstruct_lib` into every Blender (5.1+) add-ons folder it finds
         (directory junctions, so a `git pull` updates Blender too).
      4. Drops a small startup script into each Blender that pulls published updates and enables the
         add-on on first launch (see installer/stan_tools_updater.py).
      5. Copies `oo2core_6_win64.dll` from an Elden Ring / Nightreign install so DCX_KRAK files open.

    Options (environment variables, set before running):
        $env:STAN_TOOLS_BRANCH = "main"    # branch to install and follow for updates
        $env:STAN_TOOLS_DIR    = "D:\..."  # where to keep the clone
        $env:STAN_TOOLS_UNINSTALL = "1"    # remove the Blender links + startup script (keeps the clone)
#>

$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/team-cereus/soulstruct-blender.git"
$Branch = if ($env:STAN_TOOLS_BRANCH) { $env:STAN_TOOLS_BRANCH } else { "main" }
$InstallDir = if ($env:STAN_TOOLS_DIR) { $env:STAN_TOOLS_DIR } else { Join-Path $env:LOCALAPPDATA "StanTools\soulstruct-blender" }
$Uninstall = [bool]$env:STAN_TOOLS_UNINSTALL
$MinBlender = [version]"5.1"
$AddonFolders = @("io_soulstruct", "io_soulstruct_lib")
$StartupStubName = "stan_tools_updater_stub.py"

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Note([string]$Message) { Write-Host "    $Message" -ForegroundColor DarkGray }

function Update-PathFromRegistry {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Find-Git {
    $cmd = Get-Command git -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($candidate in @("$env:ProgramFiles\Git\cmd\git.exe", "$env:LOCALAPPDATA\Programs\Git\cmd\git.exe")) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

function Install-GitIfMissing {
    $git = Find-Git
    if ($git) { return $git }
    Write-Step "Git not found - installing it with winget"
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget is not available. Install Git from https://git-scm.com/download/win and run this again."
    }
    winget install --id Git.Git -e --silent --accept-package-agreements --accept-source-agreements
    Update-PathFromRegistry
    $git = Find-Git
    if (-not $git) { throw "Git install did not finish. Install it from https://git-scm.com/download/win and run this again." }
    return $git
}

# soulstruct-havok has generated type modules with ~105-char names; under %LOCALAPPDATA% they need long path support.
function Invoke-Git([string[]]$GitArgs) {
    & $script:Git -c core.longpaths=true @GitArgs
    if ($LASTEXITCODE -ne 0) { throw "git $($GitArgs -join ' ') failed (exit $LASTEXITCODE)" }
}

# Blender versions = user config folders that exist + installed Blender builds that were never launched.
function Get-BlenderVersions {
    $versions = @{}
    $configRoot = Join-Path $env:APPDATA "Blender Foundation\Blender"
    if (Test-Path $configRoot) {
        Get-ChildItem $configRoot -Directory | Where-Object { $_.Name -match '^\d+\.\d+$' } |
            ForEach-Object { $versions[$_.Name] = $true }
    }
    $installRoots = @("$env:ProgramFiles\Blender Foundation", "${env:ProgramFiles(x86)}\Blender Foundation")
    foreach ($root in $installRoots) {
        if (-not (Test-Path $root)) { continue }
        Get-ChildItem $root -Directory | ForEach-Object {
            if ($_.Name -match '(\d+\.\d+)') { $versions[$Matches[1]] = $true }
        }
    }
    # Steam / Microsoft Store builds: read the version from blender.exe next to the install.
    foreach ($exe in @(
            "${env:ProgramFiles(x86)}\Steam\steamapps\common\Blender\blender.exe",
            "$env:ProgramFiles\Steam\steamapps\common\Blender\blender.exe")) {
        if (Test-Path $exe) {
            $v = (Get-Item $exe).VersionInfo.ProductVersion
            if ($v -match '^(\d+\.\d+)') { $versions[$Matches[1]] = $true }
        }
    }
    return $versions.Keys | Where-Object { [version]$_ -ge $MinBlender } | Sort-Object { [version]$_ }
}

function Get-SteamLibraries {
    $libraries = New-Object System.Collections.Generic.List[string]
    try {
        $steam = (Get-ItemProperty "HKCU:\Software\Valve\Steam" -ErrorAction Stop).SteamPath
        if ($steam) {
            $libraries.Add($steam)
            $vdf = Join-Path $steam "steamapps\libraryfolders.vdf"
            if (Test-Path $vdf) {
                foreach ($m in [regex]::Matches((Get-Content $vdf -Raw), '"path"\s*"([^"]+)"')) {
                    $libraries.Add($m.Groups[1].Value.Replace("\\", "\"))
                }
            }
        }
    } catch { }
    return $libraries | Select-Object -Unique
}

# soulstruct looks for the Oodle DLL next to its package; Nightreign's own path is not in its search list.
function Copy-OodleDll {
    $target = Join-Path $InstallDir "io_soulstruct_lib\soulstruct\src\soulstruct\oo2core_6_win64.dll"
    if (Test-Path $target) { return }
    foreach ($lib in Get-SteamLibraries) {
        foreach ($game in @("ELDEN RING\Game", "ELDEN RING NIGHTREIGN\Game", "Sekiro")) {
            $dll = Join-Path $lib "steamapps\common\$game\oo2core_6_win64.dll"
            if (Test-Path $dll) {
                Copy-Item $dll $target
                # Keep the copied DLL out of `git status` so the updater still sees a clean tree.
                # In a submodule `--git-path` is absolute (under the parent's .git\modules), so Join-Path would mangle it.
                $soulstructDir = Join-Path $InstallDir "io_soulstruct_lib\soulstruct"
                $exclude = & $script:Git -C $soulstructDir rev-parse --git-path info/exclude
                $exclude = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($soulstructDir, $exclude))
                if (-not (Select-String -Path $exclude -Pattern "oo2core_6_win64.dll" -SimpleMatch -Quiet -ErrorAction SilentlyContinue)) {
                    New-Item -ItemType Directory -Force -Path (Split-Path $exclude) | Out-Null
                    Add-Content -Path $exclude -Value "src/soulstruct/oo2core_6_win64.dll"
                }
                Write-Note "Copied Oodle DLL from $dll"
                return
            }
        }
    }
    Write-Host "    oo2core_6_win64.dll not found. It comes with Elden Ring or Sekiro, NOT Nightreign." -ForegroundColor Yellow
    Write-Host "    Elden Ring / Nightreign files will not open until you copy it to:" -ForegroundColor Yellow
    Write-Host "      $target" -ForegroundColor Yellow
}

# blender.exe is not long-path aware, so its Python cannot open a file whose full path is 260+ characters, even with
# Windows long paths enabled. Fail here with a clear fix instead of an ImportError on the add-on's first enable.
function Assert-PathsFitBlender {
    $longest = (& $script:Git -C $InstallDir ls-files --recurse-submodules | Measure-Object -Property Length -Maximum).Maximum
    if ($InstallDir.Length + 1 + $longest -ge 260) {
        throw ("The install folder path is too long for Blender ($InstallDir). Run this again with a shorter one, " +
            "for example: `$env:STAN_TOOLS_DIR = `"C:\StanTools`"")
    }
}

function Get-AddonsDir([string]$Version) {
    return Join-Path $env:APPDATA "Blender Foundation\Blender\$Version\scripts\addons"
}

function Get-StartupDir([string]$Version) {
    return Join-Path $env:APPDATA "Blender Foundation\Blender\$Version\scripts\startup"
}

function Remove-OldAddonFolder([string]$Path) {
    if (-not (Test-Path $Path)) { return }
    $item = Get-Item $Path -Force
    if ($item.LinkType) {
        # Our own (or a stale) junction: remove the link only, never the target's files.
        [System.IO.Directory]::Delete($Path)
    } else {
        $backup = "$Path.backup-$(Get-Date -Format yyyyMMdd-HHmmss)"
        Rename-Item $Path $backup
        Write-Note "Moved existing $(Split-Path $Path -Leaf) to $backup"
    }
}

function Write-StartupStub([string]$Version) {
    $startupDir = Get-StartupDir $Version
    New-Item -ItemType Directory -Force -Path $startupDir | Out-Null
    $stub = @"
# Installed by Stan's Tools installer (installer/install.ps1). Keeps the Soulstruct add-on up to date.
# The real logic lives in the git clone, so it updates itself; delete this file to turn auto-update off.
import sys
from pathlib import Path

_REPO = Path(r"$InstallDir")
_GIT = r"$script:Git"


def register():
    sys.path.insert(0, str(_REPO / "installer"))
    try:
        import stan_tools_updater
        stan_tools_updater.on_startup(_REPO, _GIT)
    except Exception as ex:
        print(f"[Stan's Tools updater] failed: {ex!r}")
    finally:
        sys.path.remove(str(_REPO / "installer"))


def unregister():
    pass
"@
    Set-Content -Path (Join-Path $startupDir $StartupStubName) -Value $stub -Encoding UTF8
}

# ------------------------------------------------------------------------------------------------

if ($env:OS -ne "Windows_NT") { throw "This installer is for Windows." }

if (Get-Process blender -ErrorAction SilentlyContinue) {
    throw "Blender is running. Close every Blender window, then run this again."
}

$versions = @(Get-BlenderVersions)

if ($Uninstall) {
    Write-Step "Removing Stan's Tools from Blender $($versions -join ', ')"
    foreach ($v in $versions) {
        foreach ($folder in $AddonFolders) {
            $path = Join-Path (Get-AddonsDir $v) $folder
            if ((Test-Path $path) -and (Get-Item $path -Force).LinkType) { [System.IO.Directory]::Delete($path) }
        }
        Remove-Item (Join-Path (Get-StartupDir $v) $StartupStubName) -ErrorAction SilentlyContinue
    }
    Write-Host "Done. The clone at $InstallDir was kept; delete it by hand if you want." -ForegroundColor Green
    return
}

if ($versions.Count -eq 0) {
    throw "No Blender $MinBlender or newer found. Install Blender from https://www.blender.org/download/ (or 'winget install BlenderFoundation.Blender'), then run this again."
}

$script:Git = Install-GitIfMissing

# A clone made by an installer run as Administrator is owned by Administrators; git refuses that for a normal user.
# Scoped to this PowerShell session's git calls, including submodules.
$env:GIT_CONFIG_COUNT = "1"
$env:GIT_CONFIG_KEY_0 = "safe.directory"
$env:GIT_CONFIG_VALUE_0 = "*"

if (Test-Path (Join-Path $InstallDir ".git")) {
    Write-Step "Updating existing install at $InstallDir"
    Invoke-Git @("-C", $InstallDir, "fetch", "--quiet", "origin", $Branch)
    Invoke-Git @("-C", $InstallDir, "checkout", "--quiet", $Branch)
    Invoke-Git @("-C", $InstallDir, "merge", "--ff-only", "--quiet", "origin/$Branch")
} else {
    Write-Step "Downloading Stan's Tools to $InstallDir"
    New-Item -ItemType Directory -Force -Path (Split-Path $InstallDir) | Out-Null
    Invoke-Git @("clone", "--quiet", "--branch", $Branch, $RepoUrl, $InstallDir)
}
Write-Step "Downloading the soulstruct libraries"
Invoke-Git @("-C", $InstallDir, "submodule", "sync", "--quiet", "--recursive")
Invoke-Git @("-C", $InstallDir, "submodule", "update", "--init", "--recursive", "--quiet")
Assert-PathsFitBlender

Copy-OodleDll

foreach ($v in $versions) {
    Write-Step "Linking into Blender $v"
    $addonsDir = Get-AddonsDir $v
    New-Item -ItemType Directory -Force -Path $addonsDir | Out-Null
    foreach ($folder in $AddonFolders) {
        $link = Join-Path $addonsDir $folder
        Remove-OldAddonFolder $link
        New-Item -ItemType Junction -Path $link -Target (Join-Path $InstallDir $folder) | Out-Null
    }
    Write-StartupStub $v
}

$version = (& $script:Git -C $InstallDir log -1 --format="%h %cs")
Write-Host ""
Write-Host "Stan's Tools installed ($Branch @ $version)." -ForegroundColor Green
Write-Host "Next: start Blender. The first launch enables the add-on and downloads its Python packages"
Write-Host "(about a minute, needs internet). Then press N in the 3D Viewport and open the 'Stan's Tools' tab."
Write-Host "Updates download in the background whenever Blender starts; restart Blender when it says so."
