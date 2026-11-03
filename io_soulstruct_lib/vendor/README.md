# Vendored wheels

`pyrelink` (Python bindings for Grimrukh's C++ [Firelink](https://github.com/Grimrukh/Firelink) library, MIT license)
is not published on PyPI. Upstream ships it inside its Blender Extension; this fork installs it from here instead
(see `_ensure_soulstruct_installed()` in `io_soulstruct/__init__.py` and `installer/stan_tools_updater.py`).

| File | Source | SHA-256 |
|------|--------|---------|
| `pyrelink-0.3.4-cp313-cp313-win_amd64.whl` | `wheels/` in [Grimrukh/soulstruct-blender v3.2.1](https://github.com/Grimrukh/soulstruct-blender/releases/tag/v3.2.1) `io_soulstruct-3.2.1.zip` | `9310691b62776119a27670c736e4cd96d92d62755f5f58050052044d09014959` |

Windows x64 / Python 3.13 (Blender 5.1+) only, like upstream. To update: copy the new wheel from the matching upstream
release, delete the old one, and update this table. The updater re-installs whenever the set of wheels here changes.
