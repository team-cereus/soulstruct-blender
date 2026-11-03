# Installing Stan's Tools (Soulstruct for Blender, Team Cereus fork)

Windows only. Takes about five minutes, and updates install themselves after that.

## Before you start

- **Blender 5.1 or newer**, from <https://www.blender.org/download/>. Start it once, then close it.
- **Nightreign or Elden Ring** installed through Steam. Nightreign does not need to be unpacked: Stan's Tools
  does that for you (step 5 below). Elden Ring still needs UXM, so `Game\chr\` holds `.chrbnd.dcx` files.
- Free disk space for Nightreign's unpacked files: about 6 GB for characters and weapons, 6 GB more for maps.
- Internet access for the install and for Blender's first launch afterwards.

You do not need Git or Python: the installer installs Git if it is missing, and Blender brings its own Python.

## Install

1. Close Blender.
2. Open **PowerShell** (Start menu → type `PowerShell`) and paste:

   ```powershell
   irm https://raw.githubusercontent.com/team-cereus/soulstruct-blender/main/installer/install.ps1 | iex
   ```

3. Start Blender. On the first launch it turns the add-on on and downloads its Python packages. Blender
   freezes for about a minute while this happens.
4. In the 3D Viewport press **N** and open the **Stan's Tools** tab. Set **Game** and click **Auto-Detect**.
5. Nightreign only: in **Setup → Unpacked Game Files**, tick what you want and click **Unpack Nightreign Files**.
   It copies those files out of the game (a few minutes; the game itself is not changed and stays playable
   online) and points Stan's Tools at them. Run it again after a game update to pick up new files.

If the add-on did not switch on (no internet on the first launch, for example), it tries again the next time
Blender starts. You can also enable it yourself in **Edit → Preferences → Add-ons**: search "Soulstruct".

## Updates

Every time Blender starts, it checks for a new version in the background. When one has downloaded you get a
"Restart Blender" popup, and the next launch uses it. Nothing to do on your side.

## Problems

- **Re-run the install command.** It is safe to run any number of times and repairs a broken install.
- **See what is going on:** in Blender, **Window → Toggle System Console**. Lines from the updater start with
  `[Stan's Tools updater]`.
- **"oo2core_6_win64.dll" errors:** the installer could not find Elden Ring / Nightreign. Copy
  `oo2core_6_win64.dll` from the game's `Game` folder to
  `%LOCALAPPDATA%\StanTools\soulstruct-blender\io_soulstruct_lib\soulstruct\src\soulstruct\`.

## Uninstall

```powershell
$env:STAN_TOOLS_UNINSTALL = "1"; irm https://raw.githubusercontent.com/team-cereus/soulstruct-blender/main/installer/install.ps1 | iex
```

This removes the add-on and the auto-updater from Blender. Delete `%LOCALAPPDATA%\StanTools` to remove the
files too.

## For maintainers

- Installs follow `main` by default. Every push to `main` reaches everyone on their next Blender launch. To
  keep work in progress away from users, publish from a `release` branch and give the one-liner
  `$env:STAN_TOOLS_BRANCH = "release";` in front.
- The install lives in a git clone at `%LOCALAPPDATA%\StanTools\soulstruct-blender`, linked into
  `%APPDATA%\Blender Foundation\Blender\<version>\scripts\addons` with directory junctions. A stub in
  `scripts\startup` runs `installer/stan_tools_updater.py` from the clone, so the updater updates itself too.
- Updates are fast-forward only. A clone with local commits or edits is never touched, so a dev checkout
  (`S:\_modding\tools\soulstruct-blender`) is safe even with the stub installed.
- A change to either library's `pyproject.toml` makes the updater re-run pip into Blender's `addons\modules`.
  Keep the two libraries' version requirements consistent before pushing a submodule bump.
