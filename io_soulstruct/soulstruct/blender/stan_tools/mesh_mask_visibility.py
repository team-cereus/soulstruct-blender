"""NpcParam draw-mask visibility without breaking armature deformation.



DSAS keeps one rigged mesh and only skips drawing masked submeshes. Blender's

``mesh.separate(MATERIAL)`` duplicates geometry but often breaks skinning, so we

extract face islands grouped by display mask and copy bone vertex groups.

"""

from __future__ import annotations



from collections import defaultdict

import bmesh



import bpy



from ..types import SoulstructType

from soulstruct.flver.material import Material



from .npc_param import DRAW_MASK_COUNT



_MESH_SPLIT_PROP = "stan_mesh_mask_split"

_SPLIT_VERSION_PROP = "stan_mesh_mask_split_version"

_SPLIT_VERSION = 5  # 5: parts keep UVs, vertex colors and normals

_SOURCE_MESH_PROP = "stan_source_mesh"

_DISPLAY_MASK_PROP = "stan_display_mask"





def material_display_mask_id(material: bpy.types.Material | None) -> int | None:

    if material is None:

        return None

    if match := Material.DISPLAY_MASK_RE.match(material.name):

        return int(match.group(1))

    return None





def _face_mask_id(mesh: bpy.types.Mesh, material_index: int) -> int:

    if material_index >= len(mesh.materials):

        return -1

    mid = material_display_mask_id(mesh.materials[material_index])

    return mid if mid is not None else -1





def _flver_mesh_children(armature_obj: bpy.types.Object) -> list[bpy.types.Object]:

    meshes = []

    for child in armature_obj.children:

        if child.type != "MESH":

            continue

        st = getattr(child, "soulstruct_type", None)

        if st is not None and st != SoulstructType.FLVER:

            continue

        meshes.append(child)

    return meshes





def _find_source_mesh(armature_obj: bpy.types.Object) -> bpy.types.Object | None:

    for child in _flver_mesh_children(armature_obj):

        if child.get(_SOURCE_MESH_PROP):

            return child

    meshes = [c for c in _flver_mesh_children(armature_obj) if _DISPLAY_MASK_PROP not in c]

    if len(meshes) == 1:

        return meshes[0]

    meshes = _flver_mesh_children(armature_obj)

    return meshes[0] if len(meshes) == 1 else None





def _clear_mask_split_children(armature_obj: bpy.types.Object) -> None:

    for child in list(armature_obj.children):

        if child.type != "MESH":

            continue

        if child.get(_SOURCE_MESH_PROP):

            child.hide_viewport = False

            child.hide_render = False

            child.hide_set(False)

            for mod in child.modifiers:

                mod.show_viewport = True

                mod.show_render = True

            continue

        if _DISPLAY_MASK_PROP in child:

            bpy.data.objects.remove(child, do_unlink=True)

    armature_obj[_MESH_SPLIT_PROP] = False

    armature_obj[_SPLIT_VERSION_PROP] = 0





def _polygons_by_mask(mesh: bpy.types.Mesh) -> dict[int, list[int]]:

    by_mask: dict[int, list[int]] = defaultdict(list)

    for poly in mesh.polygons:

        by_mask[_face_mask_id(mesh, poly.material_index)].append(poly.index)

    return by_mask





def _extract_mask_submesh(
    source_obj: bpy.types.Object,
    target_mask: int,
    poly_indices: list[int],
) -> bpy.types.Object | None:
    """Create one skinned copy of `source_obj` with only the faces for ``target_mask`` (-1 = unmasked).

    Copies the mesh and deletes the other faces, so UVs, vertex colors, normals and vertex groups all survive.
    """
    keep = set(poly_indices)
    new_mesh = source_obj.data.copy()
    bm = bmesh.new()
    bm.from_mesh(new_mesh)
    bmesh.ops.delete(bm, geom=[face for face in bm.faces if face.index not in keep], context="FACES")
    bm.to_mesh(new_mesh)
    bm.free()

    suffix = "base" if target_mask < 0 else f"mask{target_mask:02d}"
    new_obj = source_obj.copy()  # keeps parent, transform, vertex groups, Armature modifier and Soulstruct properties
    new_obj.data = new_mesh
    new_obj.name = new_mesh.name = f"{source_obj.name}_{suffix}"
    for collection in source_obj.users_collection:
        collection.objects.link(new_obj)
    new_obj[_DISPLAY_MASK_PROP] = target_mask
    return new_obj


def ensure_mesh_parts_split(context: bpy.types.Context, armature_obj: bpy.types.Object) -> None:

    """Split merged FLVER mesh by display-mask group (DSAS-style visibility, skinning-safe)."""

    if armature_obj.get(_MESH_SPLIT_PROP) and armature_obj.get(_SPLIT_VERSION_PROP, 0) >= _SPLIT_VERSION:

        return



    if armature_obj.get(_MESH_SPLIT_PROP):

        _clear_mask_split_children(armature_obj)



    source = _find_source_mesh(armature_obj)

    if source is None:

        armature_obj[_MESH_SPLIT_PROP] = True

        armature_obj[_SPLIT_VERSION_PROP] = _SPLIT_VERSION

        return



    mesh = source.data

    if not isinstance(mesh, bpy.types.Mesh):

        armature_obj[_MESH_SPLIT_PROP] = True

        armature_obj[_SPLIT_VERSION_PROP] = _SPLIT_VERSION

        return



    polys_by_mask = _polygons_by_mask(mesh)
    if not polys_by_mask.keys() - {-1}:
        return  # nothing is masked, so there is nothing to split

    wm = context.window_manager

    mask_ids = sorted(polys_by_mask.keys())

    use_progress = bool(wm and len(mask_ids) > 4)

    if use_progress:

        wm.progress_begin(0, len(mask_ids))



    created = 0

    try:

        for step, mask_id in enumerate(mask_ids):

            if use_progress:

                wm.progress_update(step)

            if _extract_mask_submesh(source, mask_id, polys_by_mask[mask_id]) is not None:

                created += 1

    finally:

        if use_progress:

            wm.progress_end()



    if created == 0:

        armature_obj[_MESH_SPLIT_PROP] = True

        armature_obj[_SPLIT_VERSION_PROP] = _SPLIT_VERSION

        return



    source.hide_viewport = True

    source.hide_render = True

    source.hide_set(True)

    source[_SOURCE_MESH_PROP] = True

    for mod in source.modifiers:

        mod.show_viewport = False

        mod.show_render = False



    armature_obj[_MESH_SPLIT_PROP] = True

    armature_obj[_SPLIT_VERSION_PROP] = _SPLIT_VERSION



    if context.view_layer:

        context.view_layer.update()





def apply_draw_mask_to_character(

    armature_obj: bpy.types.Object,

    draw_mask: tuple[bool, ...],

    context: bpy.types.Context,

) -> tuple[int, int]:

    """Show/hide mask-group mesh children; rigging stays on the armature."""

    ensure_mesh_parts_split(context, armature_obj)



    shown = hidden = 0

    for child in armature_obj.children:

        if child.type != "MESH" or child.get(_SOURCE_MESH_PROP):

            continue

        if _DISPLAY_MASK_PROP not in child:

            continue



        mask_id = int(child[_DISPLAY_MASK_PROP])

        if mask_id < 0:

            visible = True

        else:

            visible = mask_id < DRAW_MASK_COUNT and draw_mask[mask_id]



        child.hide_set(not visible)

        child.hide_viewport = not visible

        child.hide_render = not visible

        if visible:

            shown += 1

        else:

            hidden += 1

    return shown, hidden





def show_all_character_meshes(armature_obj: bpy.types.Object) -> int:

    count = 0

    for child in armature_obj.children:

        if child.type != "MESH" or child.get(_SOURCE_MESH_PROP):

            continue

        if _DISPLAY_MASK_PROP not in child:

            continue

        child.hide_set(False)

        child.hide_viewport = False

        child.hide_render = False

        count += 1

    return count


