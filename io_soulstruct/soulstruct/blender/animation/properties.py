from __future__ import annotations

__all__ = [
    "AnimationExportSettings",
]

import bpy

from ..base.register import io_soulstruct_properties, io_soulstruct_pointer_property
from .skeleton import HKX_SKELETON_BONE_SOURCE_ITEMS, HKXSkeletonBoneSource


@io_soulstruct_properties
@io_soulstruct_pointer_property(bpy.types.Scene, "animation_export_settings")
class AnimationExportSettings(bpy.types.PropertyGroup):

    selected_frames_only: bpy.props.BoolProperty(
        name="Selected Frames Only",
        description="Export only frames between current start and end (inclusive) of Blender timeline. Otherwise, "
                    "first to last keyframe times will be exported",
        default=False,
    )

    bake_constraints: bpy.props.BoolProperty(
        name="Bake Constraints",
        description="Export the pose you see in the viewport for bones moved by constraints (IK, Copy Transforms, "
                    "Child Of, etc.), including the bones in each IK chain. Without this, export reads only keyframed "
                    "channel values and every constraint is ignored",
        default=True,
    )

    auto_repack_to_mod: bpy.props.BoolProperty(
        name="Auto-Repack to Mod Folder",
        description="After exporting a character animation, copy the full repacked ANIBND into the Mod Folder's chr\\ "
                    "directory (set in Soulstruct Settings) for ModEngine and DS Anim Studio",
        default=True,
    )

    skeleton_bone_source: bpy.props.EnumProperty(
        name="Skeleton Bone Source",
        description="Which FLVER Armature bones to write to a newly generated HKX skeleton",
        items=HKX_SKELETON_BONE_SOURCE_ITEMS,
        default=HKXSkeletonBoneSource.TEMPLATE,
    )

    skeleton_include_ancestor_bones: bpy.props.BoolProperty(
        name="Include Ancestor Bones",
        description="Also export all ancestors of every sourced bone in a newly generated HKX skeleton. If disabled, "
                    "each bone is parented to its nearest exported ancestor instead",
        default=True,
    )
