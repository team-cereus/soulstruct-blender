from __future__ import annotations

__all__ = [
    "AnimationImportExportPanel",
    "AnimationToolsPanel",
]

from ..base.register import io_soulstruct_panel
from ..bpy_base.panel import SoulstructPanel
from .import_operators import *
from .export_operators import *
from .misc_operators import *
from .skeleton_operators import *
from .control_rig import AddControlRig, RemoveControlRig, MatchControlsToPose


@io_soulstruct_panel
class AnimationImportExportPanel(SoulstructPanel):
    bl_label = "Animation Import/Export"
    bl_idname = "HKX_ANIMATION_PT_animation_import_export"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Animation"
    bl_options = {"DEFAULT_CLOSED"}

    # noinspection PyUnusedLocal
    def draw(self, context):
        settings = context.scene.soulstruct_settings
        if not settings.game_config.supports_animation:
            self.layout.label(text="Not supported for game.")
            return

        header, panel = self.layout.panel("Import", default_closed=False)
        header.label(text="Import")
        if panel:
            if settings.import_roots != (None, None):
                panel.label(text="Import from Game/Project")
                panel.operator(ImportCharacterHKXAnimation.bl_idname)
                if settings.is_er_family():
                    panel.operator(ImportAssetHKXAnimation.bl_idname)
                else:
                    panel.operator(ImportObjectHKXAnimation.bl_idname)
            else:
                panel.label(text="No game root path set.")
            panel.label(text="Generic Import:")
            panel.operator(ImportAnyHKXAnimation.bl_idname, text="Import Any Animation")

        header, panel = self.layout.panel("Export", default_closed=False)
        header.label(text="Export")
        if panel:
            export_settings = context.scene.animation_export_settings
            header2, settings_panel = panel.panel("Animation Export Settings", default_closed=True)
            header2.label(text="Animation Export Settings")
            if settings_panel:
                settings_panel.prop(export_settings, "selected_frames_only")
                settings_panel.prop(export_settings, "bake_constraints")
                settings_panel.prop(export_settings, "auto_repack_to_mod")
                if settings.game:
                    settings_panel.label(text="Mod Folder:")
                    settings_panel.prop(settings, settings.get_mod_root_prop_name(), text="")
            panel.label(text="Export to Project/Game")
            panel.operator(ExportCharacterHKXAnimation.bl_idname)
            if settings.is_er_family():
                panel.label(text="Asset animation export not ready!")
            else:
                panel.operator(ExportObjectHKXAnimation.bl_idname)
            panel.label(text="Generic Export:")
            panel.operator(ExportAnyHKXAnimation.bl_idname)
            panel.operator(ExportHKXAnimationIntoAnyBinder.bl_idname)

        header, panel = self.layout.panel("Skeleton Export", default_closed=True)
        header.label(text="Skeleton Export")
        if panel:
            export_settings = context.scene.animation_export_settings
            panel.label(text="Generate HKX skeleton from FLVER Armature.")
            panel.prop(export_settings, "skeleton_bone_source")
            panel.prop(export_settings, "skeleton_include_ancestor_bones")
            panel.label(text="Export to Project/Game")
            panel.operator(ExportCharacterHKXSkeleton.bl_idname)
            panel.operator(ExportObjectHKXSkeleton.bl_idname)
            panel.label(text="Generic Export:")
            panel.operator(ExportHKXSkeletonIntoAnyBinder.bl_idname)


@io_soulstruct_panel
class AnimationToolsPanel(SoulstructPanel):
    bl_label = "Animation Tools"
    bl_idname = "HKX_ANIMATION_PT_animation_tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Animation"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        self.layout.operator(SelectArmatureActionOperator.bl_idname)

        header, panel = self.layout.panel("Control Rig", default_closed=False)
        header.label(text="Control Rig (humanoids)")
        if panel:
            panel.operator(AddControlRig.bl_idname)
            panel.operator(MatchControlsToPose.bl_idname)
            panel.operator(RemoveControlRig.bl_idname)
            pose_bone = context.active_pose_bone
            if pose_bone is not None and pose_bone.name.startswith("ctrl_") and "ik" in pose_bone:
                panel.prop(pose_bone, '["ik"]', text=f"IK/FK ({pose_bone.name})", slider=True)
            panel.label(text="Export animations with 'Bake Constraints' on.")
        # TODO: decimate operator with ratio field
