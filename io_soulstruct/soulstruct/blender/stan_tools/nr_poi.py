"""Nightreign POI / map-seed param loading (NrWorld.buildSeeds parity)."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from soulstruct.blender.navmesh.nvmhkt.utilities import ER_GRID_ORIGIN
from soulstruct.utilities.maths import Vector3

from .regulation_bin import load_param_rows

TILE_WIDTH = 256
_GRID_ORIGIN_X, _GRID_ORIGIN_Z = ER_GRID_ORIGIN

_MAP_TILE_ID_FIELDS = ("mapTileId", "mapId", "mapTile", "mapTileID")


def parse_int(value: str | None, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def parse_float(value: str | None, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def map_id_str(tile_id: int) -> str:
    if tile_id < 0:
        return "-"
    return f"m{tile_id // 100}_{tile_id % 100:02d}"


def attach_msb_stem(area: int, grid_x: int, grid_z: int) -> str:
    return f"m{area}_{grid_x}_{grid_z}"


@dataclass(frozen=True, slots=True)
class AttachPoint:
    row_id: int
    area_no: int
    grid_x: int
    grid_z: int
    pos_x: float
    pos_y: float
    pos_z: float
    default_small_base: int


@dataclass(frozen=True, slots=True)
class PoiDefine:
    row_id: int
    icon_ids: tuple[int, ...]
    detail_icon_ids: tuple[int, ...]
    map_tile_pool: tuple[str, ...]
    invasion_icon: int
    invasion_weight: int


@dataclass(frozen=True, slots=True)
class MapSeedSummary:
    seed_id: int
    pattern_id: int
    boss_id1: int
    boss_id2: int
    boss_indices: tuple[int, ...]

    @property
    def label(self) -> str:
        bosses = ", ".join(str(b) for b in self.boss_indices) if self.boss_indices else "—"
        return f"Seed {self.seed_id} (pattern {self.pattern_id}, bosses {bosses})"


@dataclass(frozen=True, slots=True)
class SeedPoi:
    attach_point_id: int
    position: Vector3
    area_no: int
    grid_x: int
    grid_z: int
    map_tile_id: int
    map_tile_str: str
    define: PoiDefine | None
    map_index: int
    variation_id: int
    modifier: int


def game_world_position(attach: AttachPoint, apply_grid_offset: bool = True) -> Vector3:
    if apply_grid_offset:
        x = (attach.grid_x - _GRID_ORIGIN_X) * TILE_WIDTH + attach.pos_x
        z = (attach.grid_z - _GRID_ORIGIN_Z) * TILE_WIDTH + attach.pos_z
    else:
        x = attach.pos_x
        z = attach.pos_z
    return Vector3((x, attach.pos_y, z))


def _regulation_mtime(reg_dir: Path) -> int:
    try:
        return reg_dir.stat().st_mtime_ns
    except OSError:
        return 0


def _rows(reg_dir: Path, stem: str) -> dict[int, dict[str, str]]:
    return load_param_rows(str(reg_dir), stem, _regulation_mtime(reg_dir))


def _resolve_map_tile_id(small_base_map_id: int, variation_rows: dict[int, dict[str, str]]) -> int:
    row = variation_rows.get(small_base_map_id)
    if row:
        for key in _MAP_TILE_ID_FIELDS:
            if key in row:
                tile_id = parse_int(row[key], -1)
                if tile_id >= 0:
                    return tile_id
    return small_base_map_id


def _build_poi_define(row_id: int, define_rows: dict[int, dict[str, str]]) -> PoiDefine | None:
    if row_id < 0:
        return None
    row = define_rows.get(row_id)
    if row is None:
        return None

    map_ids: list[str] = []
    for i in range(1, 19):
        map_id = parse_int(row.get(f"mapId{i}"), -1)
        if map_id >= 0:
            map_ids.append(map_id_str(map_id))

    return PoiDefine(
        row_id=row_id,
        icon_ids=tuple(
            parse_int(row.get(f"worldMapPointIconId{i}"))
            for i in (1, 2, 3)
        ),
        detail_icon_ids=tuple(
            parse_int(row.get(f"detailIconId{i}"))
            for i in (1, 2, 3)
        ),
        map_tile_pool=tuple(map_ids),
        invasion_icon=parse_int(row.get("invasionIcon")),
        invasion_weight=parse_int(row.get("invasionWeight")),
    )


@lru_cache(maxsize=4)
def _cached_attach_points(reg_dir_str: str, mtime_ns: int) -> dict[int, AttachPoint]:
    del mtime_ns
    reg_dir = Path(reg_dir_str)
    attach_rows = _rows(reg_dir, "SmallBaseAndSpotAttachPoint")
    points: dict[int, AttachPoint] = {}
    for row_id, row in attach_rows.items():
        points[row_id] = AttachPoint(
            row_id=row_id,
            area_no=parse_int(row.get("areaNo"), 60),
            grid_x=parse_int(row.get("gridXNo")),
            grid_z=parse_int(row.get("gridZNo")),
            pos_x=parse_float(row.get("posX")),
            pos_y=parse_float(row.get("posY")),
            pos_z=parse_float(row.get("posZ")),
            default_small_base=parse_int(row.get("defaultSmallBase"), -1),
        )
    return points


@lru_cache(maxsize=4)
def _cached_poi_defines(reg_dir_str: str, mtime_ns: int) -> dict[int, PoiDefine]:
    del mtime_ns
    reg_dir = Path(reg_dir_str)
    define_rows = _rows(reg_dir, "SmallBaseAndSpotDefine")
    return {
        row_id: define
        for row_id in define_rows
        if (define := _build_poi_define(row_id, define_rows)) is not None
    }


@lru_cache(maxsize=4)
def _cached_map_seeds(reg_dir_str: str, mtime_ns: int) -> tuple[MapSeedSummary, ...]:
    del mtime_ns
    reg_dir = Path(reg_dir_str)
    play_rows = _rows(reg_dir, "LotResultPlayAreaParam")
    flag_rows = _rows(reg_dir, "LotResultMapPatternFlag")

    flags_by_pattern: dict[int, list[int]] = {}
    for row in flag_rows.values():
        pattern_id = parse_int(row.get("patternId"))
        target_boss = parse_int(row.get("targetBoss"))
        flags_by_pattern.setdefault(pattern_id, []).append(target_boss)

    seeds: list[MapSeedSummary] = []
    for seed_id in sorted(play_rows):
        row = play_rows[seed_id]
        pattern_id = parse_int(row.get("patternId"))
        boss_indices = tuple(sorted(set(flags_by_pattern.get(pattern_id, []))))
        seeds.append(
            MapSeedSummary(
                seed_id=seed_id,
                pattern_id=pattern_id,
                boss_id1=parse_int(row.get("bossId1"), -1),
                boss_id2=parse_int(row.get("bossId2"), -1),
                boss_indices=boss_indices,
            )
        )
    return tuple(seeds)


@lru_cache(maxsize=4)
def _cached_lot_pois_by_pattern(reg_dir_str: str, mtime_ns: int) -> dict[int, tuple[dict[str, str], ...]]:
    del mtime_ns
    reg_dir = Path(reg_dir_str)
    lot_rows = _rows(reg_dir, "LotResultSmallBaseAndSpot")
    by_pattern: dict[int, list[dict[str, str]]] = {}
    for row in lot_rows.values():
        pattern_id = parse_int(row.get("patternId"))
        by_pattern.setdefault(pattern_id, []).append(row)
    return {pid: tuple(rows) for pid, rows in by_pattern.items()}


@lru_cache(maxsize=4)
def _cached_variation_rows(reg_dir_str: str, mtime_ns: int) -> dict[int, dict[str, str]]:
    del mtime_ns
    return _rows(Path(reg_dir_str), "SmallBaseMapVariationParam")


def load_attach_points(reg_dir: Path) -> dict[int, AttachPoint]:
    mtime = _regulation_mtime(reg_dir)
    return _cached_attach_points(str(reg_dir), mtime)


def load_poi_defines(reg_dir: Path) -> dict[int, PoiDefine]:
    mtime = _regulation_mtime(reg_dir)
    return _cached_poi_defines(str(reg_dir), mtime)


def load_map_seeds(reg_dir: Path) -> list[MapSeedSummary]:
    mtime = _regulation_mtime(reg_dir)
    return list(_cached_map_seeds(str(reg_dir), mtime))


def load_map_variation_tile_ids(reg_dir: Path) -> list[int]:
    """Return sorted unique map tile ids from SmallBaseMapVariationParam row ids."""
    mtime = _regulation_mtime(reg_dir)
    variation_rows = _cached_variation_rows(str(reg_dir), mtime)
    return sorted(variation_rows.keys())


def get_seed_pois(
    reg_dir: Path,
    seeds: list[MapSeedSummary],
    seed_id: int,
) -> list[SeedPoi]:
    """Resolve POI placements for one map seed."""
    seed = next((s for s in seeds if s.seed_id == seed_id), None)
    if seed is None:
        return []

    mtime = _regulation_mtime(reg_dir)
    attach_points = _cached_attach_points(str(reg_dir), mtime)
    defines = _cached_poi_defines(str(reg_dir), mtime)
    variation_rows = _cached_variation_rows(str(reg_dir), mtime)
    lot_by_pattern = _cached_lot_pois_by_pattern(str(reg_dir), mtime)
    lot_rows = lot_by_pattern.get(seed.pattern_id, ())

    pois: list[SeedPoi] = []
    for row in lot_rows:
        attach_id = parse_int(row.get("attachId"))
        attach = attach_points.get(attach_id)
        if attach is None:
            pos = Vector3((0.0, 0.0, 0.0))
            area_no, grid_x, grid_z = 0, 0, 0
            define = None
        else:
            pos = game_world_position(attach)
            area_no, grid_x, grid_z = attach.area_no, attach.grid_x, attach.grid_z
            define = defines.get(attach.default_small_base)

        small_base_map_id = parse_int(row.get("smallBaseMapId"))
        map_tile_id = _resolve_map_tile_id(small_base_map_id, variation_rows)

        pois.append(
            SeedPoi(
                attach_point_id=attach_id,
                position=pos,
                area_no=area_no,
                grid_x=grid_x,
                grid_z=grid_z,
                map_tile_id=map_tile_id,
                map_tile_str=map_id_str(map_tile_id),
                define=define,
                map_index=parse_int(row.get("mapIndex")),
                variation_id=parse_int(row.get("variationId")),
                modifier=parse_int(row.get("modifier")),
            )
        )
    return pois
