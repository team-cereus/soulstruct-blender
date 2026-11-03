# Soulstruct for Blender — Elden Ring / Nightreign Animation Dev Notes

Working notes for the `team-cereus` fork setup. Covers (1) what actually works today, (2) the
single-PyCharm-project layout with submodules, (3) hot-reload workflow, (4) the
quickest path to "full mesh + anim + skeleton", export roadmap, and (5) **Stan's Tools**
animator workflow.

> **Animator workflow (full tool map, DSAS, NPC params, troubleshooting):**
> [`docs/STAN_TOOLS_WORKFLOW.md`](docs/STAN_TOOLS_WORKFLOW.md)

> **TL;DR.** In this **team-cereus fork**, ER/NR **mesh + skeleton (FLVER)**, **animation
> import**, and **character ANIBND export** (HK2018 + `CompressAnim.exe`) work — see
> §7. Upstream Grimrukh still lists ER animation export as incomplete. Verified on NR
> `chr/c7720.anibnd.dcx`: 137-bone skeleton, spline decode to 71 interleaved frames via
> `hk2018` classes without HavokMax.

---

## 1. What works today (verified)

| Capability (Elden Ring / Nightreign) | Status | Where |
|---|---|---|
| FLVER mesh import | ✅ Works | `flver/models/...` (`Sekiro_EldenRing` FLVER version) |
| Skeleton / armature import (from FLVER) | ✅ Works | same as above |
| Animation **import** (ANIBND → Blender action) | ✅ Works | `animation/import_operators.py` → `eldenring.AnimationHKX`/`SkeletonHKX` |
| HK2018 tagfile (`20180100`) + `.compendium` read | ✅ Works | `soulstruct.havok` tagfile unpacker + `DivBinder` |
| Spline-compressed → interleaved decode | ✅ Works | `soulstruct.havok` `spline_compression.py` |
| Animation **export** (Blender → game ANIBND) | ✅ Works | `animation/export_operators.py` (see §7) |
| Asset (`aeg`) animation export | ❌ Missing | TODO in `export_operators.py` |

Nightreign uses the **same HK2018 tagfile format** as Elden Ring, so the ER classes parse
NR `chr` data directly. The only thing that was broken on the stock path was a binder API
name skew between the two libraries (now fixed — see §3).

---

## 2. Project layout (one PyCharm project, submodules)

The add-on repo is now the single project root. The two libraries are git **submodules**
under `io_soulstruct_lib/` (this matches the add-on author's stated intent):

```
S:\_modding\tools\soulstruct-blender\        ← open THIS in PyCharm
├── io_soulstruct\                            ← Blender add-on (UI/operators only)
│   └── soulstruct\blender\                   ← the `soulstruct.blender` package
├── io_soulstruct_lib\
│   ├── soulstruct\                           ← submodule: https://github.com/team-cereus/soulstruct.git (main, 2.4.0)
│   └── soulstruct-havok\                      ← submodule: team-cereus/soulstruct-havok (upstream Grimrukh, 1.3.0)
├── .gitmodules
└── DEV_ER_ANIMATION.md                       ← this file
```

`.gitmodules`:

```ini
[submodule "io_soulstruct_lib/soulstruct"]
	path = io_soulstruct_lib/soulstruct
	url = https://github.com/team-cereus/soulstruct.git
[submodule "io_soulstruct_lib/soulstruct-havok"]
	path = io_soulstruct_lib/soulstruct-havok
	url = https://github.com/team-cereus/soulstruct-havok.git
```

Clone-from-scratch on another machine:

```bash
git clone --recurse-submodules <soulstruct-blender remote>
# or, after a plain clone:
git submodule update --init --recursive
```

### Blender wiring (junctions, already created on this machine)

The add-on's `io_soulstruct/__init__.py` looks for `io_soulstruct_lib` **next to**
`io_soulstruct` in Blender's `scripts/addons`. We link both to the repo:

```
%APPDATA%\Blender Foundation\Blender\5.1\scripts\addons\
├── io_soulstruct       --> S:\_modding\tools\soulstruct-blender\io_soulstruct        (junction)
├── io_soulstruct_lib   --> S:\_modding\tools\soulstruct-blender\io_soulstruct_lib    (junction)
└── modules\            ← editable installs of soulstruct + soulstruct-havok land here
```

Recreate if needed (no admin required):

```powershell
$addons = "$env:APPDATA\Blender Foundation\Blender\5.1\scripts\addons"
cmd /c mklink /J "$addons\io_soulstruct"     "S:\_modding\tools\soulstruct-blender\io_soulstruct"
cmd /c mklink /J "$addons\io_soulstruct_lib" "S:\_modding\tools\soulstruct-blender\io_soulstruct_lib"
```

On first **interactive** enable (`Edit > Preferences > Add-ons > Soulstruct`), the add-on
pip-installs the two libs editable into `addons\modules`. Open **Window > Toggle System
Console** first to watch for errors.

> Headless enable (`blender --background`) fails with a GPU-draw error from the MSB module
> — that's expected; it is **not** an import/registration failure. Validate in the GUI.

---

## 3. The compat fix (lives in the `team-cereus/soulstruct` fork)

`soulstruct-havok` 1.3.0 calls `binder.find_entries_matching_name(...)`
(`soulstruct-havok/src/soulstruct/havok/core.py:189`, on the ER ANIBND `load_from_entries`
path), but `soulstruct` 2.4.0 only implements `find_entries_by_name_regex(...)`. Fix =
two alias methods in the fork:

`io_soulstruct_lib/soulstruct/src/soulstruct/containers/core.py` (class `Binder`, after
`find_entries_by_name_regex`):

```python
# Compatibility alias for soulstruct-havok (expects *_matching_name).
def find_entry_matching_name(
    self, pattern: str | re.Pattern, flags=0, escape=False,
) -> BinderEntry:
    return self.find_entry_by_name_regex(pattern, flags=flags, escape=escape)

# Compatibility alias for soulstruct-havok (expects *_matching_name).
def find_entries_matching_name(
    self, pattern: str | re.Pattern, flags=0, escape=False,
) -> list[BinderEntry]:
    return self.find_entries_by_name_regex(pattern, flags=flags, escape=escape)

# Compatibility alias for io_soulstruct Blender operators (expects find_entry_id).
def find_entry_id(self, entry_id: int) -> BinderEntry:
    return self.find_entry_by_id(entry_id)
```

```bash
cd io_soulstruct_lib/soulstruct
git checkout -b fix/binder-matching-name-alias
git commit -am "Add find_(entry|entries)_matching_name aliases for soulstruct-havok compat"
git push -u origin fix/binder-matching-name-alias
```

Verification (passes from the fork via the test venv):

```
soulstruct.__path__ -> ...\io_soulstruct_lib\soulstruct\src\soulstruct
bones: 137
animation count: 80
sample animation id: 20  (spline -> 71 interleaved frames)  OK
```

---

## 4. PyCharm setup

- **Interpreter:** use Blender's embedded Python for runtime parity:
  `C:\Program Files\Blender Foundation\Blender 5.1\5.1\python\bin\python.exe`
  (Python 3.13). Or a venv on the same Python; the test venv at
  `S:\_modding\tools\_research\.venv` already has both libs editable-installed.
- **Sources roots** (Settings > Project Structure):
  - `io_soulstruct` (the add-on)
  - `io_soulstruct_lib/soulstruct/src`
  - `io_soulstruct_lib/soulstruct-havok/src`
- **`bpy` autocomplete:** `pip install fake-bpy-module` into the interpreter, then run
  `blender-stubs/split_bpy_types.py` (chunks the huge stub so PyCharm can index it; it
  also injects Soulstruct property types via `blender-stubs/soulstruct_extra_stubs.py`).
  `File > Invalidate Caches` afterward.
- Submodules appear as normal subfolders; edits to `soulstruct` go to your `team-cereus` fork,
  edits to `soulstruct-havok` track upstream (fork it too if you need to push Havok fixes).

---

## 5. Hot reload (two different things)

### A. Blender addon reload (development)

This add-on is built for Blender's built-in reload and pre-reloads its own
`soulstruct.blender.*` modules in `io_soulstruct/__init__.py` to avoid partial-import
`isinstance` bugs.

| You changed… | Reload method |
|---|---|
| `soulstruct.blender.*` (the add-on UI/operators) | **F3 → `Reload Scripts`** (fast loop) |
| `io_soulstruct/__init__.py` (class/menu registration) | Reload Scripts; restart if it errors |
| `soulstruct` / `soulstruct-havok` core libs (the submodules) | **Restart Blender** — the auto-reloader only re-imports `soulstruct.blender` |
| First-time pip bootstrap / new dependency | **Restart Blender** |

So for day-to-day work in `soulstruct.blender` operators you stay in Blender and hit
Reload Scripts. When you change the Havok/core libs (which is where ER **export** work
happens), restart Blender (or reload those modules manually).

### B. DSAS in-game live reload (not in Blender)

**DS Anim Studio** can ask a **running** Elden Ring / Nightreign process to reload a
character's on-disk files (`LiveRefreshOnSave` or **File → Force Ingame Entity Reload
Now**). That uses Win32 memory injection + per-game AOB signatures (`install\Res\IngameReload_ER.ini`), not file watching.

**Stan's Tools does not implement this.** After Blender export, use **Auto-Repack to Mod
Folder** so `Game\mod\chr\c####.anibnd.dcx` is current, then trigger reload from DSAS
(EAC off, admin, entity spawned). See [`docs/STAN_TOOLS_WORKFLOW.md`](docs/STAN_TOOLS_WORKFLOW.md) §6.

---

## 6. Quickest path to "full mesh + anim + skeleton" in Blender

**Loading (import): essentially done.** All Soulstruct operators live in the **3D Viewport
sidebar** (not the top menu bar). Prerequisite: add-on enabled under
`Edit > Preferences > Add-ons`, search **Soulstruct**.

### Where "General Settings" actually is

**General Settings** is a **collapsible panel inside the right-hand sidebar** of the 3D
View. The same controls are duplicated on several sidebar **tabs** (one copy per tab):

| How to open the sidebar | |
|---|---|
| Press **`N`** in the 3D View, **or** | |
| Click the **`<` / `>` arrow** on the right edge of the 3D Viewport | |

At the **top of that sidebar**, you will see Soulstruct tabs such as **`FLVER`**,
**`Animation`**, **`Collision`**, **`MSB`**, etc. (added by the add-on when it loads.)

On **any** of those tabs, scroll if needed and expand the panel named **`General Settings`**
(it is **collapsed by default** — click the panel header to open it). The **`Animation`**
tab is the most convenient when you are doing animation work; **`FLVER`** works too for
step 1.

**Alternative (same data, different place):** open the **Properties** editor (usually the
vertical panel on the right of the Blender window) → select the **Scene** context (tab
with the **render / scene** icon, not the camera/object icons) → expand **`Soulstruct
Settings`**. That panel is the Scene-properties copy of the same settings (`SCENE_PT_soulstruct_settings`).

There is **no** top-level `General Settings` menu under `Edit` or `Window`.

### Step-by-step (e.g. Artorias / `c7720`)

**0. Unpack game files first.** Soulstruct reads unpacked binders on disk (e.g. WitchyBND).
You need at least:

- `chr\c7720.chrbnd.dcx` (mesh)
- `chr\c7720.anibnd.dcx` (animations + skeleton HKX)

**1. General Settings — game + folders**

In the 3D View sidebar → **`FLVER`** or **`Animation`** tab → expand **`General Settings`**:

1. **`Game`** dropdown (top of panel) → choose **`Elden Ring`**.  
   (Nightreign uses the same Havok classes and a newer FLVER revision `0x20021`; keep
   **Elden Ring** selected in Soulstruct — the fork adds `FLVERVersion.Nightreign` for
   mesh import.)
2. **`Game Root:`** → folder picker → directory that **contains** a `chr\` folder with your
   binders. For Nightreign on this machine, for example:  
   `s:\SteamLibrary\steamapps\common\ELDEN RING NIGHTREIGN\Game`  
   For vanilla Elden Ring, the folder that contains `Game\chr\` (often the install root
   with the `.exe`, depending on how you unpacked).
3. **`Project Root:`** (optional) → mod output tree mirroring `Game\`; leave empty if you
   only import from the game install.
4. Confirm the **Animation** tab’s **Import** section does **not** show *"No game root
   path set."* — that message means `Game Root` is still empty or wrong.

Optional: expand **`Import/Export Settings`** inside the same panel (`Prefer Import from
Project`, etc.).

**2. Import mesh + armature (FLVER)**

Still in the 3D View sidebar → **`FLVER`** tab → expand **`FLVER Import`** → click
**`Import Character`**.

- File browser opens filtered to `*.chrbnd` / `*.chrbnd.dcx`.
- Navigate to `chr\` under your Game Root and pick **`c7720.chrbnd.dcx`** (or unpacked
  `.chrbnd`).
- Follow the operator’s file-browser options (textures, merge submeshes, etc.) and confirm.

Result: a mesh object parented to an **Armature** (skeleton). Select the armature or mesh
before the next step.

**3. Import animation (HKX from ANIBND)**

3D View sidebar → **`Animation`** tab:

1. Expand **`General Settings`** if you have not set Game Root on this tab yet (same as
   step 1).
2. Expand **`Animation Import/Export`** → sub-panel **`Import`**.
3. Click **`Import Character Anim`** (only enabled when a character FLVER/armature is
   selected; character model names usually start with **`c`**).
4. In the popup list, choose an animation entry (e.g. `a000_000020.hkx` inside
   `c7720.anibnd`).

**4. Timing (30 Hz, 1:1 frames)**

Game animations are **30 Hz** (same as **DSAS**). Import places one Blender keyframe per
game sample and sets the scene to **30 fps**. Blender frame **N** = game sample **N**.
Re-import clips if you imported before this behavior was enforced.

Press **Space** with the armature selected to preview.

### Headless smoke tests (no UI)

From the repo root, with Blender 5.1 and Nightreign `Game` on disk:

```powershell
# Mesh + armature only
& 'C:\Program Files\Blender Foundation\Blender 5.1\blender.exe' `
    --background --factory-startup `
    --python 'S:\_modding\tools\soulstruct-blender\scripts\blender_test_nr_c7720.py'

# Mesh + armature + HKX animation (default a000_000020.hkx)
& 'C:\Program Files\Blender Foundation\Blender 5.1\blender.exe' `
    --background --factory-startup `
    --python 'S:\_modding\tools\soulstruct-blender\scripts\blender_test_nr_c7720_anim.py'
```

Override paths with `NR_GAME_ROOT`, `NR_CHRBND`, `NR_ANIM_STEM`. The animation script
stubs MSB modules so it does not hit the MSB GPU draw import (full add-on enable still
requires the GUI).

Verified on `c7720`: spline `a000_000020.hkx` → Blender action `c7720|a000_000020`,
scene frame end **70** at 30 fps (71 game frames, 1:1).

### Remaining "make import bulletproof" items (code, not UI)

The remaining "make import bulletproof" items are small and live in this fork:

- Confirm `ANIBND` is re-exported from `soulstruct.havok.fromsoft.eldenring.__init__`
  (currently import via `...eldenring.anibnd import ANIBND`).
- Exercise `tests/animations` `test_er()` against a real ER (not just NR) ANIBND.
- Validate end-to-end in the GUI (playback preview, action assignment on armature).

## 7. Export (character ANIBND)

**Implemented in this fork:**

- `div_id` derived from compendium stem (`c7720` → `hkx_compendium\\`, `cXXXX_div00` → `hkx_div00_compendium\\`).
- `get_initial_binder()` uses `DivBinder` for Elden Ring.
- Character export loads skeleton with **compendium** (same as import).
- Overwriting an existing animation reuses its Binder **entry path**.

**Still partial:**

- **BLF-split ANIBND write.** Characters like `c7720` (no `.blf` files) can be written back;
  binders that use BLF div splits will error until `DivBinder.write()` is implemented.
- **Tagfile / TCRF** round-trip (whether re-exported spline HKX load in-game without compendium refs).
- **Asset (`aeg`)** animation export (not implemented).

### Test export (Artorias `c7720`)

1. Finish your edit on action `c7720|a000_003023` (or whichever clip you modified).
2. **General Settings:** Game Root set; **Project Root** recommended (e.g. `...\NIGHTREIGN\Game\mod` mirroring `chr\`).
3. Enable **Also Export to Game** only if you intend to overwrite game files (back up first).
4. **Smoke test (loose HKX):** **Animation → Export → Export Any HKX Animation**
   - Skeleton path: `chr\c7720.anibnd.dcx` (binder) or leave default flow.
   - Pick output `a000_003023.hkx` on disk; confirms `CompressAnim.exe` + sampling work.
5. **ANIBND writeback:** select armature → **Export Character Anim**
   - Replaces the entry with the same ID as the action stem (`a000_003023` → id `1000003023`).
   - Writes to project (and copies to game if configured).
6. If export fails on **CompressAnim**, check console; `soulstruct-havok` ships `havok/resources/CompressAnim.exe`.
7. **Force Interleaved** (operator option): skip spline compression for debugging only (game may not load it).

Spline export uses `CompressAnim.exe` in `soulstruct-havok` (interleaved → hk2010 → spline → hk2018).

### Why HavokMax matters (and where it doesn't)

HavokMax/HavokLib confirm the format facts (HK2018 tagfile, `.compendium`, NURBS spline
decode, the FromSoft Y↔Z permutation) but HavokMax **only exports interleaved Havok XML**
— it does **not** write spline-compressed HKX or tagfiles either (it relies on Havok
Content Tools to recompress). So HavokMax is a **reference for reading**, which
`soulstruct-havok` already does. For game-ready **writeback**, `soulstruct-havok`'s
`CompressAnim.exe` bridge is actually further along than HavokMax. Conclusion: don't port
HavokMax — finish the export plumbing above.

## 8. Character search + mod-folder export (animator workflow)

Quick path for a friend who only edits animations (no manual `chr\` file browsing).

### Stan's Tools tab (recommended entry point)

In the **3D Viewport** sidebar (press **N**), open the **"Stan's Tools"** tab (not FLVER/Animation). Panels:

| Panel | What it does |
|-------|----------------|
| **Setup** | Game, **Auto-Detect Game Directory**, Game/Project/Mod folders, auto-repack toggle |
| **Characters** | **Search Character by Name**, **NPC Param Selection** (mesh visibility), **Load Character Animation** |
| **Animation** | Export settings + **Export Character Animation** |

Reload the addon after updating the fork (`Edit → Preferences → Add-ons → Soulstruct → refresh` or restart Blender).

### Settings (once per game)

1. **Stan's Tools → Setup** (or **Properties → Scene → Soulstruct Settings**):
   - **Game** = **Elden Ring: Nightreign** (dedicated entry; no need to fake Elden Ring).
   - **Game Root** = unpacked `...\ELDEN RING NIGHTREIGN\Game` (contains `chr\`, `msg\`, exe; use **Auto-Detect**).
   - **Project Root** (optional) — mod workspace mirroring game layout (e.g. `...\Game\mod`).
   - **Mod Folder** — ModEngine folder (e.g. `...\ELDEN RING NIGHTREIGN\Game\mod`). Repacked ANIBNDs are copied to `chr\` here when auto-repack is on.
2. **Animation → Export → Animation Export Settings**:
   - **Auto-Repack to Mod Folder** (default on) — after **Export Character Anim**, copies the full `cXXXX.anibnd.dcx` into the Mod Folder for DSAS / in-game.

### Load a character

1. **Stan's Tools → Characters** → **Search Character by Name** (magnifier icon).
2. Type a name (e.g. `Artorias`, `Margit`) or id (`c7720`), then pick an entry — imports the **CHRBND** model only.
3. **NPC Param Selection** — pick an **NpcParam** row (DSAS Entity-tab style). **Changing the row applies visibility immediately.** Import does not auto-split meshes (avoids freeze on large characters like Helstor); split runs when you pick a row or click **Apply NPC Param Visibility**. Materials tagged `#00#`–`#31#` map to `modelDispMask` fields. Requires Witchy **NpcParam.param.xml** (Setup path or `Project/regulation-bin/`).
4. Select the character **armature**, then **Load Character Animation** — search popup lists clips from that character's **ANIBND**. Multi-div binders (e.g. **Caligo `c4900`**) pick the correct `.compendium` per clip path.

Names come from bundled JSON under `soulstruct/blender/general/character_names/` (generated from Paramdex; NR names merged when using Elden Ring). Edit **`overrides.json`** in that folder to add or fix labels (e.g. DLC bosses missing from Paramdex):

```json
{ "7720": "Knight Artorias" }
```

Regenerate defaults from the repo:

```bash
python scripts/tools/gen-character-names.py
# (from souls-script-kt; writes into soulstruct-blender .../character_names/)
```

### Export to mod

1. Select the character armature, set the **Action** you edited.
2. **Animation → Export Character Anim** (writes project/game per existing rules).
3. With **Auto-Repack to Mod Folder** enabled, the repacked `chr\cXXXX.anibnd.dcx` is also copied to the **Mod Folder** — same path DSAS reads when ModEngine is configured.
