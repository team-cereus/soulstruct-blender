# Launch Blender 5.1 with stdout/stderr attached to this terminal.
# Useful for Soulstruct add-on debugging — enable Soulstruct Settings > Enable debug logging
# for verbose import/export traces in the console.

$BlenderExe = $env:BLENDER_EXE
if (-not $BlenderExe) {
    $BlenderExe = 'C:\Program Files\Blender Foundation\Blender 5.1\blender.exe'
}

if (-not (Test-Path -LiteralPath $BlenderExe)) {
    Write-Error "Blender not found at: $BlenderExe`nSet BLENDER_EXE to your blender.exe path."
    exit 1
}

Write-Host "Starting Blender (console attached): $BlenderExe"
& $BlenderExe @args
