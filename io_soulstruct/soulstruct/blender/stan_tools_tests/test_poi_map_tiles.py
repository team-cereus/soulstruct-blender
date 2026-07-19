"""Path-resolution tests for POI map tiles (no Blender runtime)."""
from __future__ import annotations

from pathlib import Path
import unittest

from soulstruct.games import NIGHTREIGN
from soulstruct.nightreign.maps import poi_map_pieces

STAGING_ROOT = Path(r"S:/_modding/tools/soulstruct-blender/_tmp/nr-full-unpack")
STAGING_MSB = STAGING_ROOT / "map/mapstudio/m30_30_00_00.msb.dcx"


def _staging_available() -> bool:
    return STAGING_MSB.is_file()


def _tile_stem_to_map_stem(tile_str: str) -> str:
    if not tile_str or tile_str == "-":
        return ""
    parts = tile_str.split("_")
    if len(parts) >= 4:
        return tile_str
    if len(parts) == 2:
        return f"{tile_str}_00_00"
    return tile_str


def _map_lookup_stems(tile_str: str = "", msb_stem: str = "", *, lookup: str = "auto") -> list[str]:
    poi_stem = _tile_stem_to_map_stem(tile_str)
    attach_stem = msb_stem if msb_stem and msb_stem != "-" else ""
    if lookup == "poi_tile":
        return [poi_stem] if poi_stem else []
    if lookup == "attach_cell":
        return [attach_stem] if attach_stem else []
    if poi_stem:
        stems = [poi_stem]
        if attach_stem and attach_stem not in stems:
            stems.append(attach_stem)
        return stems
    if attach_stem:
        return [attach_stem]
    return []


def _poi_search_root_paths(settings) -> list[Path]:
    """Mirror of ``_poi_search_roots`` / ``all_import_roots`` path resolution."""
    paths: list[Path] = []
    for root in settings.import_roots:
        if root is not None:
            paths.append(root.root)
    if settings.is_game(NIGHTREIGN) and settings.nightreign_unpack_staging_path is not None:
        staging = settings.nightreign_unpack_staging_path
        if staging.is_dir():
            paths.append(staging)
    return paths


def _find_msb_for_tile(settings, tile_str: str = "", msb_stem: str = "") -> Path | None:
    """Mirror of ``find_msb_for_tile`` without Blender imports."""
    for stem in _map_lookup_stems(tile_str, msb_stem):
        for root_path in _poi_search_root_paths(settings):
            path = poi_map_pieces.find_msb_path(root_path, stem)
            if path is not None:
                return path
    return None


class _SettingsStub:
    """Minimal settings stand-in for path helper tests."""

    def __init__(
        self,
        *,
        game_root: Path | None = None,
        project_root: Path | None = None,
        staging: str = "",
        prefer_import_from_project: bool = True,
    ):
        self.game = NIGHTREIGN
        self.prefer_import_from_project = prefer_import_from_project
        self.nightreign_unpack_staging_str = staging
        self._game_root_path = game_root
        self._project_root_path = project_root

    @property
    def game_root_path(self) -> Path | None:
        return self._game_root_path

    @property
    def project_root_path(self) -> Path | None:
        return self._project_root_path

    @property
    def import_roots(self):
        game_root = _RootStub(self.game_root_path) if self.game_root_path else None
        project_root = _RootStub(self.project_root_path) if self.project_root_path else None
        if self.prefer_import_from_project:
            return (project_root, game_root)
        return (game_root, project_root)

    @property
    def nightreign_unpack_staging_path(self) -> Path | None:
        return Path(self.nightreign_unpack_staging_str) if self.nightreign_unpack_staging_str else None

    def is_game(self, *name_or_game) -> bool:
        for game in name_or_game:
            if game is NIGHTREIGN or getattr(game, "variable_name", None) == NIGHTREIGN.variable_name:
                return True
        return False


class _RootStub:
    def __init__(self, root: Path):
        self.root = root.resolve()


class TestPoiMapPieces(unittest.TestCase):
    def test_resolve_msb_stem(self):
        self.assertEqual(poi_map_pieces.resolve_msb_stem("m30_30"), "m30_30_00_00")
        self.assertEqual(poi_map_pieces.resolve_msb_stem("m30_30_00_00"), "m30_30_00_00")

    @unittest.skipUnless(_staging_available(), "staging MSB missing")
    def test_find_msb_path_on_staging(self):
        path = poi_map_pieces.find_msb_path(STAGING_ROOT, "m30_30")
        self.assertIsNotNone(path)
        assert path is not None
        self.assertEqual(path.name, "m30_30_00_00.msb.dcx")


class TestPoiSearchRoots(unittest.TestCase):
    @unittest.skipUnless(_staging_available(), "staging root missing")
    def test_poi_search_roots_includes_staging(self):
        stub = _SettingsStub(staging=str(STAGING_ROOT))
        root_paths = {path.resolve() for path in _poi_search_root_paths(stub)}
        self.assertIn(STAGING_ROOT.resolve(), root_paths)

    @unittest.skipUnless(_staging_available(), "staging root missing")
    def test_all_import_roots_includes_staging(self):
        stub = _SettingsStub(staging=str(STAGING_ROOT))
        root_paths = {path.resolve() for path in _poi_search_root_paths(stub)}
        self.assertIn(STAGING_ROOT.resolve(), root_paths)


class TestFindMsbForTile(unittest.TestCase):
    @unittest.skipUnless(_staging_available(), "staging MSB missing")
    def test_find_msb_for_tile_via_staging(self):
        stub = _SettingsStub(staging=str(STAGING_ROOT))
        path = _find_msb_for_tile(stub, "m30_30")
        self.assertIsNotNone(path)
        assert path is not None
        self.assertEqual(path.name, "m30_30_00_00.msb.dcx")

    @unittest.skipUnless(_staging_available(), "staging MSB missing")
    def test_has_map_tile_data_msb_only(self):
        stub = _SettingsStub(staging=str(STAGING_ROOT))
        self.assertIsNotNone(_find_msb_for_tile(stub, "m30_30"))


if __name__ == "__main__":
    unittest.main()
