from __future__ import annotations

__all__ = [
    "ExportAnyHKXAnimation",
    "ExportHKXAnimationIntoAnyBinder",
    "ExportCharacterHKXAnimation",
    "ExportObjectHKXAnimation",
]

import re
import subprocess
import traceback
import typing as tp
from pathlib import Path

import bpy

from soulstruct.containers import Binder, EntryNotFoundError
from soulstruct.games import ELDEN_RING
from soulstruct.dcx import DCXType
from soulstruct.havok.fromsoft.base import BaseSkeletonHKX, BaseAnimationHKX

from ..base.operators import *
from ..base.register import io_soulstruct_operator
from ..exceptions import *
from ..flver.models import BlenderFLVER
from ..types import *
from .utilities import *
from .types import SoulstructAnimation


SKELETON_ENTRY_RE = re.compile(r"skeleton\.hkx", re.IGNORECASE)


def _resolve_animation_hkx_dcx_type(settings, dcx_type_name: str) -> DCXType:
    """HKX clips inside ANIBND are never DCX-wrapped; only the outer binder uses KRAK."""
    if dcx_type_name == "AUTO":
        game_anim_info = SoulstructAnimation.GAME_ANIMATION_INFO_CHR.get(settings.game_type)
        if game_anim_info is not None:
            return game_anim_info.dcx_type
        return settings.resolve_dcx_type(dcx_type_name, "hkx")
    return DCXType.from_member_name(dcx_type_name)


def _format_export_exception(ex: BaseException) -> str:
    """Blender often shows `str(RuntimeError())` as empty when the real detail is on `__cause__`."""
    if str(ex):
        text = f"{type(ex).__name__}: {ex}"
    else:
        text = f"{type(ex).__name__} (no message — see System Console for traceback)"
    cause = ex.__cause__
    if cause is not None:
        if isinstance(cause, subprocess.CalledProcessError):
            text += (
                f" | CompressAnim exit {cause.returncode} ({cause.returncode:#x})"
            )
            if cause.output:
                text += f" | {cause.output.decode(errors='replace').strip()[:300]}"
        elif str(cause):
            text += f" | caused by {type(cause).__name__}: {cause}"
        else:
            text += f" | caused by {type(cause).__name__}"
    return text


def _is_bl_flver_with_animation_data(obj: bpy.types.Object) -> tp.TypeGuard[MeshObject]:
    if not obj:
        return False
    try:
        bl_flver = BlenderFLVER.from_armature_or_mesh(obj)
    except SoulstructTypeError:
        return False
    return bool(bl_flver.armature and bl_flver.armature.animation_data and bl_flver.armature.animation_data.action)


@io_soulstruct_operator
class ExportAnyHKXAnimation(LoggingExportOperator):
    """Export loose HKX animation file from an Action attached to active FLVER Armature."""
    bl_idname = "export_scene.hkx_animation"
    bl_label = "Export Any HKX Animation"
    bl_description = "Export a Blender action to a standalone HKX animation file with manual HKX skeleton source"


    filename_ext = ".hkx"

    filter_glob: bpy.props.StringProperty(
        default="*.hkx",
        options={'HIDDEN'},
        maxlen=255,  # Max internal buffer length, longer would be clamped.
    )

    hkx_skeleton_path: bpy.props.StringProperty(
        name="HKX Skeleton Path",
        description="Path to matching HKX skeleton or character ANIBND (auto-filled from imported FLVER model name)",
        default="",
        subtype="FILE_PATH",
    )

    dcx_type: get_dcx_enum_property(
        default=DCXType.Null.name,
        description=(
            "DCX compression for the loose file. Use None for Elden Ring / Nightreign animation HKX "
            "(game ANIBND entries are uncompressed .hkx; only the outer .anibnd.dcx is KRAK)."
        ),
    )

    force_interleaved: bpy.props.BoolProperty(
        name="Force Interleaved",
        description="Force exported animation format to be interleaved for manual inspection/usage",
        default=False,
    )

    @classmethod
    def poll(cls, context) -> bool:
        if not context.scene.soulstruct_settings.game_config.supports_animation:
            return False
        if not context.active_object:
            return False
        return _is_bl_flver_with_animation_data(context.active_object)

    def invoke(self, context, _event):
        """Default output name and ANIBND skeleton source from imported FLVER/action."""
        settings = self.settings(context)
        bl_flver = BlenderFLVER.from_armature_or_mesh(context.active_object)
        bl_animation = SoulstructAnimation(bl_flver.armature.animation_data.action)

        self.filepath = f"{bl_animation.animation_stem}.hkx"
        anibnd_path = resolve_character_anibnd_path(settings, bl_flver.game_name)
        if anibnd_path is not None:
            self.hkx_skeleton_path = str(anibnd_path)
        elif not self.hkx_skeleton_path:
            self.info(
                f"Could not find ANIBND for '{bl_flver.game_name}' in Game/Project roots. "
                f"Set HKX Skeleton Path manually in the export dialog."
            )

        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        self.info("Executing HKX animation export...")

        settings = self.settings(context)
        bl_flver = BlenderFLVER.from_armature_or_mesh(context.active_object)
        bl_animation = SoulstructAnimation.from_armature_animation_data(bl_flver.armature)

        skeleton_hkx_class = settings.game_config.skeleton_hkx_class  # type: type[BaseSkeletonHKX]
        if skeleton_hkx_class is None:
            return self.error(f"No skeleton HKX class defined for game {settings.game.name}.")
        animation_hkx_class = settings.game_config.animation_hkx_class  # type: type[BaseAnimationHKX]
        if animation_hkx_class is None:
            return self.error(f"No animation HKX class defined for game {settings.game.name}.")

        animation_file_path = Path(self.filepath)

        if not self.hkx_skeleton_path:
            anibnd_path = resolve_character_anibnd_path(settings, bl_flver.game_name)
            if anibnd_path is not None:
                self.hkx_skeleton_path = str(anibnd_path)
                self.info(f"Using character ANIBND: {anibnd_path}")

        skeleton_path = Path(self.hkx_skeleton_path)
        if not skeleton_path.is_file():
            return self.error(
                f"Invalid HKX skeleton path: {skeleton_path}. "
                f"For Elden Ring characters, use chr\\{{model}}.anibnd.dcx (e.g. chr\\c7720.anibnd.dcx)."
            )

        try:
            skeleton_hkx = load_skeleton_hkx_from_path(skeleton_path, settings.game)
        except EntryNotFoundError:
            return self.error(f"Could not find `skeleton.hkx` in binder: '{skeleton_path}'")
        except ValueError:
            return self.error(f"Could not load file as a `SkeletonHKX` or `Binder`: {skeleton_path}")
        except Exception as ex:
            if "compendium" in str(ex).lower() or ex.__class__.__name__ == "MissingCompendiumError":
                return self.error(
                    f"Elden Ring skeleton HKX requires its ANIBND compendium. "
                    f"Set HKX Skeleton Path to the character's `.anibnd.dcx` (e.g. chr\\c7720.anibnd.dcx), "
                    f"not a loose skeleton file. Error: {ex}"
                )
            raise

        current_frame = context.scene.frame_current  # store for resetting after export
        try:
            animation_hkx = bl_animation.to_game_compressed_animation(
                self,
                context,
                settings.game,
                bl_flver.armature,
                skeleton_hkx,
                animation_hkx_class,
                self.force_interleaved,
            )
        except Exception as ex:
            traceback.print_exc()
            return self.error(f"Failed to create animation HKX. {_format_export_exception(ex)}")
        finally:
            context.scene.frame_set(current_frame)

        dcx_type = _resolve_animation_hkx_dcx_type(settings, self.dcx_type)
        animation_hkx.dcx_type = dcx_type
        if animation_file_path.suffix == ".dcx" and dcx_type == DCXType.Null:
            animation_file_path = animation_file_path.with_suffix("")  # user picked .hkx.dcx in dialog
        animation_hkx.write(animation_file_path)
        if dcx_type != DCXType.Null:
            self.warning(
                f"Wrote DCX-compressed animation at '{animation_file_path}'. "
                f"ANIBND entries must be uncompressed .hkx (Compression = None). "
                f"Use Export Character Anim or re-export with Compression = None."
            )

        return {"FINISHED"}


@io_soulstruct_operator
class ExportHKXAnimationIntoAnyBinder(LoggingImportOperator):
    """Export HKX animation from an Action attached to a FLVER armature, into an existing BND."""
    bl_idname = "export_scene.hkx_animation_binder"
    bl_label = "Export HKX Animation Into Any Binder"
    bl_description = "Export a Blender action to a HKX animation file inside a FromSoftware Binder (BND/BHD)"

    filter_glob: bpy.props.StringProperty(
        default="*.anibnd;*.anibnd.dcx;*.objbnd;*.objbnd.dcx",
        options={'HIDDEN'},
        maxlen=255,
    )

    dcx_type: get_dcx_enum_property()

    animation_id: bpy.props.IntProperty(
        name="Animation ID",
        description="Animation ID for name and Binder entry ID to use",
        default=0,
        min=0,
    )

    overwrite_existing: bpy.props.BoolProperty(
        name="Overwrite Existing",
        description="Allow existing animation with this ID to be overwritten",
        default=True,
    )

    default_entry_path: bpy.props.StringProperty(
        name="Default Path",
        description="Path to use for Binder entry if it needs to be created. Default is for DS1R `anibnd.dcx` files",
        default="N:\\FRPG\\data\\Model\\chr\\{name}\\hkxx64\\",
    )

    name_template: bpy.props.StringProperty(
        name="Animation Name Template",
        description="Template for converting animation ID to entry name",
        default="a##_####",  # default for DS1
    )

    force_interleaved: bpy.props.BoolProperty(
        name="Force Interleaved",
        description="Force exported animation format to be interleaved for manual inspection/usage",
        default=False,
    )

    @classmethod
    def poll(cls, context) -> bool:
        if not context.scene.soulstruct_settings.game_config.supports_animation:
            return False
        if not context.active_object:
            return False
        try:
            bl_flver = BlenderFLVER.from_armature_or_mesh(context.active_object)
        except SoulstructTypeError:
            return False
        return bool(bl_flver.armature and bl_flver.armature.animation_data and bl_flver.armature.animation_data.action)

    def execute(self, context):
        settings = self.settings(context)
        bl_flver = BlenderFLVER.from_armature_or_mesh(context.active_object)
        bl_animation = SoulstructAnimation.from_armature_animation_data(bl_flver.armature)

        skeleton_hkx_class = settings.game_config.skeleton_hkx_class  # type: type[BaseSkeletonHKX]
        if skeleton_hkx_class is None:
            return self.error(f"No skeleton HKX class defined for game {settings.game.name}.")
        animation_hkx_class = settings.game_config.animation_hkx_class  # type: type[BaseAnimationHKX]
        if animation_hkx_class is None:
            return self.error(f"No animation HKX class defined for game {settings.game.name}.")

        binder_path = Path(self.filepath)
        binder = Binder.from_path(binder_path)

        if not self.overwrite_existing and self.animation_id in binder.get_entry_ids():
            return self.error(f"Animation ID {self.animation_id} already exists in Binder and overwrite is disabled")

        try:
            skeleton_entry = binder[SKELETON_ENTRY_RE]
        except EntryNotFoundError:
            return self.error("Could not find 'skeleton.hkx' in binder.")
        compendium = (
            load_anibnd_compendium(binder, hkx_entry_path=skeleton_entry.path)
            if settings.is_er_family()
            else None
        )
        skeleton_hkx = read_skeleton_hkx_entry(skeleton_entry, compendium)

        animation_name = get_animation_name(self.animation_id, self.name_template[1:], prefix=self.name_template[0])
        self.info(f"Exporting animation '{animation_name}' into binder {binder_path.name}...")

        current_frame = context.scene.frame_current
        try:
            animation_hkx = bl_animation.to_game_compressed_animation(
                self,
                context,
                settings.game,
                bl_flver.armature,
                skeleton_hkx,
                animation_hkx_class,
                self.force_interleaved,
            )
        except Exception as ex:
            traceback.print_exc()
            return self.error(f"Failed to create animation HKX. {_format_export_exception(ex)}")
        finally:
            context.scene.frame_set(current_frame)

        dcx_type = _resolve_animation_hkx_dcx_type(settings, self.dcx_type)
        animation_hkx.dcx_type = dcx_type
        entry_path = self.default_entry_path + animation_name + (".hkx" if dcx_type == DCXType.Null else ".hkx.dcx")
        # Update or create binder entry.
        binder.set_default_entry(self.animation_id, new_path=entry_path).set_from_binary_file(animation_hkx)

        # Write modified binder back.
        binder.write()

        return {"FINISHED"}


class _BaseExportTypedHKXAnimation(LoggingOperator):

    # Optional class variable for `SkeletonHKX` instance. Useful for tests.
    # If `None`, the skeleton must appear in the targeted Binder for export
    # (with special handling used for c0000 split ANIBNDs).
    SKELETON_HKX: tp.ClassVar[SKELETON_TYPING | None] = None

    @classmethod
    def poll(cls, context) -> bool:
        settings = cls.settings(context)
        if not settings.game_config.supports_animation:
            return False
        if not settings.can_auto_export:
            return False
        if not context.active_object:
            return False
        obj = context.active_object
        try:
            bl_flver = BlenderFLVER.from_armature_or_mesh(obj)
        except SoulstructTypeError:
            return False
        return bool(bl_flver.armature and bl_flver.armature.animation_data and bl_flver.armature.animation_data.action)


@io_soulstruct_operator
class ExportCharacterHKXAnimation(_BaseExportTypedHKXAnimation):
    """Export active animation from selected character Armature into that character's game ANIBND."""
    bl_idname = "export_scene.hkx_character_animation"
    bl_label = "Export Character Anim"
    bl_description = (
        "Export active Action into its character's ANIBND. For c0000, the best available sub-ANIBND will be chosen "
        "automatically based on animation ID. Use 'Export HKX Anim into Binder' for manual choice"
    )

    force_interleaved: bpy.props.BoolProperty(
        name="Force Interleaved",
        description="Force exported animation format to be interleaved for manual inspection/usage",
        default=False,
    )

    @classmethod
    def poll(cls, context) -> bool:
        return super().poll(context) and context.active_object.name[0] == "c"

    def execute(self, context):
        if not self.poll(context):
            return self.error("Must select a single Armature of a character (name starting with 'c') with an Action.")

        settings = self.settings(context)
        try:
            game_anim_info = SoulstructAnimation.GAME_ANIMATION_INFO_CHR[settings.game_type]
        except KeyError:
            return self.error(f"Automatic ANIBND export is not yet supported for game {settings.game.name}.")

        bl_flver = BlenderFLVER.from_armature_or_mesh(context.active_object)
        bl_animation = SoulstructAnimation.from_armature_animation_data(bl_flver.armature)

        skeleton_hkx_class = settings.game_config.skeleton_hkx_class  # type: type[BaseSkeletonHKX]
        if skeleton_hkx_class is None:
            return self.error(f"No skeleton HKX class defined for game {settings.game.name}.")
        animation_hkx_class = settings.game_config.animation_hkx_class  # type: type[BaseAnimationHKX]
        if animation_hkx_class is None:
            return self.error(f"No animation HKX class defined for game {settings.game.name}.")

        model_name = bl_flver.game_name

        relative_anibnd_path = Path(game_anim_info.relative_binder_path.format(model_name=model_name))
        try:
            # NOTE: We don't use the managed `ANIBND` class from `soulstruct-havok` here.
            anibnd = settings.get_initial_binder(self, relative_anibnd_path)
        except FileNotFoundError as ex:
            return self.error(f"Cannot find ANIBND for character {model_name}: {ex}")

        if self.SKELETON_HKX is not None:
            self.info(f"Using operator SKELETON_HKX for export: {self.SKELETON_HKX.path_name}")
            skeleton_hkx = self.SKELETON_HKX
        else:
            # Skeleton is in ANIBND.
            skeleton_anibnd = anibnd
            try:
                skeleton_entry = skeleton_anibnd[SKELETON_ENTRY_RE]
            except EntryNotFoundError:
                return self.error("Could not find 'skeleton.hkx' (case-insensitive) in ANIBND.")
            compendium = (
                load_anibnd_compendium(anibnd, hkx_entry_path=skeleton_entry.path, model_name=model_name)
                if settings.is_er_family()
                else None
            )
            skeleton_hkx = read_skeleton_hkx_entry(skeleton_entry, compendium)

        # Get animation stem from action name. We will re-format its ID in the selected game's known format (e.g. to
        # support cross-game conversion).
        animation_id = bl_animation.animation_id

        if model_name == "c0000":
            sub_anibnd_stems = [entry.stem for entry in anibnd.find_entries_by_name_regex(r"c0000_.*\.txt")]
            if not sub_anibnd_stems:
                return self.error("Could not find any sub-ANIBND definitions (e.g. 'c0000_a0x.txt') in c0000 ANIBND.")
            # For now, we keep it simple: load ALL sub-ANIBNDs, find the one with a matching animation ID to replace,
            # and fall back to using either `c0000_dlc` or `c0000_a9x` if no existing animation is found.
            for stem in sub_anibnd_stems:
                relative_sub_anibnd_path = Path(game_anim_info.relative_binder_path.format(model_name=stem))
                try:
                    sub_anibnd = settings.get_initial_binder(self, relative_sub_anibnd_path)
                except FileNotFoundError as ex:
                    return self.error(f"Cannot find sub-ANIBND for c0000: '{relative_sub_anibnd_path}'. Error: {ex}")
                if animation_id in sub_anibnd.get_entry_ids():
                    # Found matching animation. We export our new animation into this sub ANIBND.
                    self.info(f"Will replace existing animation ID {animation_id} in c0000 sub-ANIBND `{stem}`.")
                    anibnd = sub_anibnd
                    relative_anibnd_path = relative_sub_anibnd_path
                    break
            else:
                # Could not find existing animation ID in any sub-ANIBND. Fall back to DLC or a9x.
                for stem_option in ["c0000_dlc02", "c0000_dlc", "c0000_a9x"]:
                    if stem_option not in sub_anibnd_stems:
                        continue
                    relative_sub_anibnd_path = Path(game_anim_info.relative_binder_path.format(model_name=stem_option))
                    try:
                        anibnd = settings.get_initial_binder(self, relative_sub_anibnd_path)
                        relative_anibnd_path = relative_sub_anibnd_path
                    except FileNotFoundError:
                        continue  # try next option
                else:
                    return self.error(
                        f"Could not find any sub-ANIBND with existing animation ID {animation_id} for c0000, and could "
                        f"not find a backup sub-ANIBND ('c0000_dlc02', 'c0000_dlc', 'c0000_a9x') to export into."
                    )

        try:
            animation_name = get_animation_name(animation_id, game_anim_info.stem_template, prefix="a")
        except ValueError:
            max_digits = game_anim_info.stem_template.count("#")
            return self.error(
                f"Animation ID {animation_id} is too large for game {settings.game}. Max is {'9' * max_digits}."
            )

        if getattr(anibnd, "write_blf_division", False):
            return self.error(
                f"ANIBND '{anibnd.path_name}' uses BLF div split binders; writing modified ANIBNDs is not supported yet. "
                f"Use 'Export Any HKX Animation' to write a loose .hkx file instead."
            )

        self.info(f"Exporting animation '{animation_name}' into ANIBND '{anibnd.path_name}'...")

        current_frame = context.scene.frame_current
        try:
            animation_hkx = bl_animation.to_game_compressed_animation(
                self,
                context,
                settings.game,
                bl_flver.armature,
                skeleton_hkx,
                animation_hkx_class,
                self.force_interleaved,
            )
        except Exception as ex:
            traceback.print_exc()
            return self.error(f"Failed to create animation HKX. {_format_export_exception(ex)}")
        finally:
            context.scene.frame_set(current_frame)

        animation_hkx.dcx_type = _resolve_animation_hkx_dcx_type(settings, "AUTO")
        entry_path = get_chr_animation_hkx_entry_path(
            settings.game,
            game_anim_info,
            anibnd,
            model_name,
            animation_name,
            animation_id,
        )

        # Update or create binder entry.
        anibnd.set_default_entry(animation_id, new_path=entry_path).set_from_binary_file(animation_hkx)
        self.info(f"Successfully exported animation '{animation_name}' into ANIBND {anibnd.path_name}.")

        # Write modified ANIBND.
        exported_paths = settings.export_file(self, anibnd, relative_anibnd_path)
        if exported_paths:
            export_settings = context.scene.animation_export_settings
            if export_settings.auto_repack_to_mod:
                settings.copy_exported_file_to_mod_root(self, exported_paths, relative_anibnd_path)

        return {"FINISHED" if exported_paths else "CANCELLED"}


@io_soulstruct_operator
class ExportObjectHKXAnimation(_BaseExportTypedHKXAnimation):
    """Export active animation from selected object Armature into that object's game OBJBND."""
    bl_idname = "export_scene.object_hkx_animation"
    bl_label = "Export Object Anim"
    bl_description = "Export active Action into its object's OBJBND"

    force_interleaved: bpy.props.BoolProperty(
        name="Force Interleaved",
        description="Force exported animation format to be interleaved for manual inspection/usage",
        default=False,
    )

    @classmethod
    def poll(cls, context) -> bool:
        return super().poll(context) and context.active_object.name[0] == "o"

    def execute(self, context):
        settings = self.settings(context)

        bl_flver = BlenderFLVER.from_armature_or_mesh(context.active_object)
        bl_animation = SoulstructAnimation.from_armature_animation_data(bl_flver.armature)
        model_name = bl_flver.game_name

        try:
            game_anim_info = SoulstructAnimation.GAME_ANIMATION_INFO_OBJ[settings.game_type]
        except KeyError:
            return self.error(f"Automatic OBJBND + ANIBND export is not yet supported for game {settings.game.name}.")

        skeleton_hkx_class = settings.game_config.skeleton_hkx_class  # type: type[BaseSkeletonHKX]
        if skeleton_hkx_class is None:
            return self.error(f"No skeleton HKX class defined for game {settings.game.name}.")
        animation_hkx_class = settings.game_config.animation_hkx_class  # type: type[BaseAnimationHKX]
        if animation_hkx_class is None:
            return self.error(f"No animation HKX class defined for game {settings.game.name}.")

        # Get OBJBND to modify from project (preferred) or game directory.
        relative_objbnd_path = Path(game_anim_info.relative_binder_path.format(model_name=model_name))
        try:
            objbnd = settings.get_initial_binder(self, relative_objbnd_path)  # don't need OBJBND class here
        except FileNotFoundError:
            return self.error(f"Cannot find OBJBND for object {model_name}.")

        # Find ANIBND entry inside OBJBND.
        try:
            anibnd_entry = objbnd[f"{model_name}.anibnd"]  # no DCX
        except EntryNotFoundError:
            return self.error(f"OBJBND for object {model_name} has no ANIBND entry.")
        skeleton_anibnd = anibnd = Binder.from_binder_entry(anibnd_entry)

        # Find skeleton entry.
        try:
            skeleton_entry = skeleton_anibnd[SKELETON_ENTRY_RE]
        except EntryNotFoundError:
            return self.error("Could not find 'skeleton.hkx' (case-insensitive) in ANIBND inside OBJBND.")
        skeleton_hkx = skeleton_hkx_class.from_binder_entry(skeleton_entry)

        # Get animation stem from action name. We will re-format its ID in the selected game's known format (e.g. to
        # support cross-game conversion).
        animation_id_str = bl_animation.animation_stem
        animation_id_str = animation_id_str.lstrip("a")
        try:
            animation_id = int(animation_id_str)
        except ValueError:
            return self.error(f"Could not parse animation ID from action name '{bl_animation.name}'.")

        try:
            animation_name = get_animation_name(animation_id, game_anim_info.stem_template, prefix="a")
        except ValueError:
            max_digits = game_anim_info.stem_template.count("#")
            return self.error(
                f"Animation ID {animation_id} is too large for game {settings.game}. Max is {'9' * max_digits}."
            )

        self.info(f"Exporting animation {animation_name} into OBJBND {objbnd.path_name}...")

        current_frame = context.scene.frame_current
        try:
            animation_hkx = bl_animation.to_game_compressed_animation(
                self,
                context,
                settings.game,
                bl_flver.armature,
                skeleton_hkx,
                animation_hkx_class,
                self.force_interleaved,
            )
        except Exception as ex:
            traceback.print_exc()
            return self.error(f"Failed to create animation HKX. {_format_export_exception(ex)}")
        finally:
            context.scene.frame_set(current_frame)

        animation_hkx.dcx_type = DCXType.Null  # no DCX inside OBJBND/ANIBND
        entry_path = animation_hkx.dcx_type.process_path(
            game_anim_info.hkx_entry_path.format(model_name=model_name, animation_stem=animation_name)
        )

        # Update or create binder entry.
        anibnd.set_default_entry(animation_id, new_path=entry_path).set_from_binary_file(animation_hkx)

        # Write modified ANIBND entry back into OBJBND.
        anibnd_entry.set_from_binary_file(anibnd)

        # Export modified OBJBND.
        exported_paths = settings.export_file(self, objbnd, relative_objbnd_path)
        return {"FINISHED" if exported_paths else "CANCELLED"}


# TODO: Export Asset animation. Requires general ER support, obviously.
