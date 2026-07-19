"""Blender operators for Nightreign POI marker import."""

from __future__ import annotations



__all__ = [

    "StanRefreshMapSeedList",

    "StanImportPoiMarkers",

    "StanClearPoiMarkers",

    "StanFramePoiMarkers",

    "StanImportSelectedPoiMapTile",

    "StanPoiCatalogPrev",

    "StanPoiCatalogNext",

    "StanPoiCatalogFrame",

    "StanPoiCatalogBrowseModal",

]



import bpy



from soulstruct.blender.general.properties import SoulstructSettings

from soulstruct.blender.utilities import LoggingOperator



from .nr_poi import get_seed_pois, load_attach_points, load_map_seeds, load_map_variation_tile_ids, load_poi_defines, parse_int

from .poi_catalog import advance_catalog_index, catalog_tile_count, find_catalog_tile_object, frame_catalog_tile

from .poi_map_tiles import has_map_tile_data, import_map_tile_at_empty, import_map_tiles_for_pois, import_poi_tile_catalog, show_poi_catalog_tile

from .poi_markers import (

    POI_ROOT_COLLECTION,

    clear_poi_markers,

    frame_poi_collection,

    import_attach_points,

    import_poi_defines,

    import_poi_tile_catalog_markers,

    import_seed_layout,

)

from .regulation_bin import auto_set_regulation_bin_dir, resolve_regulation_bin_dir





def _seed_layout_collection_name(seed_id: int, pattern_id: int) -> str:

    return f"Seed {seed_id} (pattern {pattern_id})"





def _pois_with_tile_empties(context, collection_name: str) -> list[tuple]:

    sub = bpy.data.collections.get(collection_name)

    if sub is None:

        return []

    return [

        (obj, obj.get("map_tile_str", ""))

        for obj in sub.all_objects

        if obj.get("stan_poi_marker") and obj.get("map_tile_str") and obj.get("map_tile_str") != "-"

    ]





def _catalog_poll(context) -> bool:

    return catalog_tile_count(context.scene.stan_tools_settings) > 0





class StanRefreshMapSeedList(LoggingOperator):

    """Rebuild map seed enum from LotResultPlayAreaParam."""



    bl_idname = "stan_tools.refresh_map_seed_list"

    bl_label = "Refresh Map Seed List"

    bl_description = "Reload map seeds from regulation-bin LotResultPlayAreaParam.param.xml"



    def execute(self, context):

        settings = SoulstructSettings.from_context(context)

        stan = context.scene.stan_tools_settings

        if not stan.regulation_bin_dir:

            auto_set_regulation_bin_dir(stan, settings)

        reg_dir = resolve_regulation_bin_dir(settings, stan)

        if reg_dir is None:

            return self.warning(

                "regulation-bin not found. Set Regulation Bin Dir in Setup or point Project Root at "

                "param-nightreign/regulation-bin."

            )

        if stan.refresh_map_seed_list(context, reg_dir):

            self.info("Loaded map seed list.")

            return {"FINISHED"}

        return self.warning("LotResultPlayAreaParam.param.xml not found or empty.")





class StanImportPoiMarkers(LoggingOperator):

    """Import Nightreign POI markers as Empty objects."""



    bl_idname = "stan_tools.import_poi_markers"

    bl_label = "Import POI Markers"

    bl_description = "Create Empty markers for attach points or a selected map seed layout"



    def execute(self, context):

        settings = SoulstructSettings.from_context(context)

        stan = context.scene.stan_tools_settings

        if not stan.regulation_bin_dir:

            auto_set_regulation_bin_dir(stan, settings)

        reg_dir = resolve_regulation_bin_dir(settings, stan)

        if reg_dir is None:

            return self.warning(

                "regulation-bin not found. Set Regulation Bin Dir in Setup or point Project Root at "

                "param-nightreign/regulation-bin."

            )



        mode = stan.poi_display_mode

        apply_offset = stan.poi_apply_grid_offset

        frame_view = stan.poi_frame_on_import



        if mode == "ATTACH_POINTS":

            attach_points = load_attach_points(reg_dir)

            if not attach_points:

                return self.warning("SmallBaseAndSpotAttachPoint.param.xml not found or empty.")

            defines = load_poi_defines(reg_dir)

            count = import_attach_points(

                context,

                attach_points,

                defines,

                apply_grid_offset=apply_offset,

                frame_view=frame_view,

            )

            self.info(f"Imported {count} attach point marker(s).")

            return {"FINISHED"}



        if mode == "SEED_LAYOUT":

            if not stan.map_seed_id:

                return self.warning("Select a map seed first (Refresh Map Seed List).")

            seed_id = parse_int(stan.map_seed_id, -1)

            seeds = load_map_seeds(reg_dir)

            seed = next((s for s in seeds if s.seed_id == seed_id), None)

            if seed is None:

                return self.warning(f"Map seed {seed_id} not found.")

            pois = get_seed_pois(reg_dir, seeds, seed_id)

            attach_points = load_attach_points(reg_dir)

            count = import_seed_layout(

                context,

                seed_id,

                seed.pattern_id,

                pois,

                apply_grid_offset=apply_offset,

                attach_points=attach_points,

                frame_view=frame_view,

            )

            self.info(f"Imported {count} POI marker(s) for seed {seed_id}.")



            if stan.poi_import_map_tiles:

                pois_with_empties = _pois_with_tile_empties(

                    context,

                    _seed_layout_collection_name(seed_id, seed.pattern_id),

                )

                imported, tiles_with_files, unique_tiles = import_map_tiles_for_pois(

                    self,

                    context,

                    settings,

                    pois_with_empties,

                    lookup="poi_tile",

                )

                if unique_tiles and tiles_with_files == 0:

                    return self.warning(
                        "No map tile data found — unpack map/ or set Unpack Staging with mapstudio MSBs"
                    )

                if imported:

                    self.info(f"Imported {imported} map tile piece(s).")

            return {"FINISHED"}



        if mode == "POI_TILE_CATALOG":

            tile_ids = load_map_variation_tile_ids(reg_dir)

            if not tile_ids:

                return self.warning("SmallBaseMapVariationParam.param.xml not found or empty.")



            if stan.poi_import_map_tiles:

                imported, tiles_with_files, total = import_poi_tile_catalog(

                    self,

                    context,

                    settings,

                    tile_ids,

                )

                msg = (

                    f"POI tile catalog: {total} variation tile(s), "

                    f"{tiles_with_files} with map files, {imported} mesh(es) imported."

                )

                if total and tiles_with_files == 0:

                    return self.warning(
                        f"{msg} No map tile data — unpack map/ or set Unpack Staging with mapstudio MSBs."
                    )

                self.info(msg)

            else:

                count = import_poi_tile_catalog_markers(

                    context,

                    tile_ids,

                    frame_view=frame_view,

                )

                self.info(f"POI tile catalog: {count} variation tile(s) (meshes disabled).")

            return {"FINISHED"}



        if mode == "DEFINES_ONLY":

            defines = load_poi_defines(reg_dir)

            if not defines:

                return self.warning("SmallBaseAndSpotDefine.param.xml not found or empty.")

            count = import_poi_defines(context, defines, frame_view=frame_view)

            self.info(f"Imported {count} POI define marker(s) at origin strip.")

            return {"FINISHED"}



        return self.warning(f"Unknown POI display mode: {mode}")





class StanClearPoiMarkers(LoggingOperator):

    """Remove all Nightreign POI marker collections and objects."""



    bl_idname = "stan_tools.clear_poi_markers"

    bl_label = "Clear POI Markers"

    bl_description = "Delete the Nightreign POIs collection and all marker empties"



    def execute(self, context):

        stan = context.scene.stan_tools_settings

        stan.poi_catalog_tile_ids = ""

        stan.poi_catalog_index = 0

        count = clear_poi_markers(context)

        if count:

            self.info(f"Removed {count} POI marker object(s).")

        else:

            self.info("No POI markers to remove.")

        return {"FINISHED"}





class StanFramePoiMarkers(LoggingOperator):

    """Frame the 3D viewport on Nightreign POI markers."""



    bl_idname = "stan_tools.frame_poi_markers"

    bl_label = "Frame POI View"

    bl_description = "Select all POI markers and frame the 3D viewport (clip end extended for overworld coords)"



    @classmethod

    def poll(cls, context):

        return bpy.data.collections.get(POI_ROOT_COLLECTION) is not None



    def execute(self, context):

        if frame_poi_collection(context):

            self.info("Framed viewport on POI markers.")

            return {"FINISHED"}

        return self.warning("No POI markers to frame.")





class StanImportSelectedPoiMapTile(LoggingOperator):

    """Import map tile FLVER geometry at the active POI marker."""



    bl_idname = "stan_tools.import_selected_poi_map_tile"

    bl_label = "Import Selected POI Tile"

    bl_description = (
        "Import map piece FLVER/MSB for the active POI marker's tile "
        "(unpack map/ or set Unpack Staging with mapstudio MSBs)"
    )



    @classmethod

    def poll(cls, context):

        obj = context.active_object

        if obj is None or not obj.get("stan_poi_marker"):

            return False

        tile_str = obj.get("map_tile_str", "")

        msb_stem = obj.get("msb_stem", "")

        if not tile_str and not msb_stem:

            return False

        settings = SoulstructSettings.from_context(context)

        lookup = "poi_tile" if tile_str and tile_str != "-" else "attach_cell"

        return has_map_tile_data(settings, tile_str, msb_stem=msb_stem, lookup=lookup)



    def execute(self, context):

        settings = SoulstructSettings.from_context(context)

        obj = context.active_object

        if import_map_tile_at_empty(self, context, obj, settings):

            return {"FINISHED"}

        return self.warning(
            "No map tile data found — unpack map/ or set Unpack Staging with mapstudio MSBs"
        )





class StanPoiCatalogPrev(LoggingOperator):

    """Show the previous POI catalog tile."""



    bl_idname = "stan_tools.poi_catalog_prev"

    bl_label = "Prev Tile"

    bl_description = "Load the previous POI variation tile at origin"



    @classmethod

    def poll(cls, context):

        return _catalog_poll(context)



    def execute(self, context):

        settings = SoulstructSettings.from_context(context)

        stan = context.scene.stan_tools_settings

        advance_catalog_index(stan, settings, -1)

        show_poi_catalog_tile(self, context, settings, frame=True)

        return {"FINISHED"}





class StanPoiCatalogNext(LoggingOperator):

    """Show the next POI catalog tile."""



    bl_idname = "stan_tools.poi_catalog_next"

    bl_label = "Next Tile"

    bl_description = "Load the next POI variation tile at origin"



    @classmethod

    def poll(cls, context):

        return _catalog_poll(context)



    def execute(self, context):

        settings = SoulstructSettings.from_context(context)

        stan = context.scene.stan_tools_settings

        advance_catalog_index(stan, settings, 1)

        show_poi_catalog_tile(self, context, settings, frame=True)

        return {"FINISHED"}





class StanPoiCatalogFrame(LoggingOperator):

    """Re-frame the current POI catalog tile."""



    bl_idname = "stan_tools.poi_catalog_frame"

    bl_label = "Frame Tile"

    bl_description = "Frame the 3D viewport on the current catalog tile"



    @classmethod

    def poll(cls, context):

        return _catalog_poll(context)



    def execute(self, context):

        obj = find_catalog_tile_object(context)

        if frame_catalog_tile(context, obj):

            return {"FINISHED"}

        return self.warning("No catalog tile to frame.")





class StanPoiCatalogBrowseModal(bpy.types.Operator):

    """Browse POI catalog tiles with arrow keys."""



    bl_idname = "stan_tools.poi_catalog_browse_modal"

    bl_label = "Browse Tiles"

    bl_description = "LEFT/RIGHT or A/D: prev/next tile. ESC: finish"



    @classmethod

    def poll(cls, context):

        return _catalog_poll(context)



    def invoke(self, context, event):

        context.window_manager.modal_handler_add(self)

        self.report({"INFO"}, "Browse: LEFT/RIGHT or A/D prev/next, ESC finish")

        return {"RUNNING_MODAL"}



    def modal(self, context, event):

        if event.type == "ESC":

            return {"FINISHED"}

        if event.value != "PRESS":

            return {"RUNNING_MODAL"}



        settings = SoulstructSettings.from_context(context)

        stan = context.scene.stan_tools_settings

        direction = 0

        if event.type in {"LEFT_ARROW", "A"}:

            direction = -1

        elif event.type in {"RIGHT_ARROW", "D"}:

            direction = 1

        else:

            return {"RUNNING_MODAL"}



        advance_catalog_index(stan, settings, direction)

        show_poi_catalog_tile(None, context, settings, frame=True)

        return {"RUNNING_MODAL"}


