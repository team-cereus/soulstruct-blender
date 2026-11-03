"""NpcParam draw-mask visibility without breaking armature deformation.



DSAS keeps one rigged mesh and only skips drawing masked submeshes. Blender's

``mesh.separate(MATERIAL)`` duplicates geometry but often breaks skinning, so we

extract face islands grouped by display mask and copy bone vertex groups.

"""

from __future__ import annotations



from collections import defaultdict



import bpy



from ..types import SoulstructType

from soulstruct.flver.material import Material



from .npc_param import DRAW_MASK_COUNT



_MESH_SPLIT_PROP = "stan_mesh_mask_split"

_SPLIT_VERSION_PROP = "stan_mesh_mask_split_version"

_SPLIT_VERSION = 4

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





def _copy_vertex_groups_subset(

    source_obj: bpy.types.Object,

    target_obj: bpy.types.Object,

    source_vert_indices: list[int],

) -> None:

    """``source_vert_indices[new_vert_index]`` is the vertex index on ``source_obj``."""

    mesh = source_obj.data

    if not isinstance(mesh, bpy.types.Mesh) or not source_obj.vertex_groups:

        return



    new_groups = [target_obj.vertex_groups.new(name=vg.name) for vg in source_obj.vertex_groups]

    for new_idx, src_idx in enumerate(source_vert_indices):

        if src_idx < 0 or src_idx >= len(mesh.vertices):

            continue

        for membership in mesh.vertices[src_idx].groups:

            if membership.weight <= 0.0:

                continue

            new_groups[membership.group].add((new_idx,), membership.weight, "ADD")





def _copy_armature_modifier(source: bpy.types.Object, target: bpy.types.Object) -> None:

    for mod in source.modifiers:

        if mod.type != "ARMATURE":

            continue

        new_mod = target.modifiers.new(name=mod.name, type="ARMATURE")

        new_mod.object = mod.object

        new_mod.use_vertex_groups = mod.use_vertex_groups

        new_mod.use_deform_preserve_volume = mod.use_deform_preserve_volume

        new_mod.vertex_group = mod.vertex_group

        new_mod.invert_vertex_group = mod.invert_vertex_group

        new_mod.show_viewport = True

        new_mod.show_render = True

        return

    armature = source.parent if source.parent and source.parent.type == "ARMATURE" else None

    if armature is None:

        return

    new_mod = target.modifiers.new(name="FLVER Armature", type="ARMATURE")

    new_mod.object = armature





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





def _build_mesh_from_polygons(

    source_mesh: bpy.types.Mesh,

    poly_indices: list[int],

) -> tuple[bpy.types.Mesh, list[int]] | None:

    """Return new mesh data and ``source_vert_indices[new_index] -> source vert index``."""

    if not poly_indices:

        return None



    old_to_new: dict[int, int] = {}

    verts: list[tuple[float, float, float]] = []

    faces: list[list[int]] = []



    for poly_i in poly_indices:

        poly = source_mesh.polygons[poly_i]

        face: list[int] = []

        for loop_i in range(poly.loop_start, poly.loop_start + poly.loop_total):

            vi = source_mesh.loops[loop_i].vertex_index

            new_vi = old_to_new.get(vi)

            if new_vi is None:

                new_vi = len(verts)

                old_to_new[vi] = new_vi

                co = source_mesh.vertices[vi].co

                verts.append((co.x, co.y, co.z))

            face.append(new_vi)

        faces.append(face)



    new_mesh = bpy.data.meshes.new(f"{source_mesh.name}_part")

    new_mesh.from_pydata(verts, [], faces)

    for new_poly, src_poly_i in zip(new_mesh.polygons, poly_indices):
        new_poly.material_index = source_mesh.polygons[src_poly_i].material_index

    new_mesh.update()



    source_vert_indices = [0] * len(verts)

    for old_vi, new_vi in old_to_new.items():

        source_vert_indices[new_vi] = old_vi

    return new_mesh, source_vert_indices





def _extract_mask_submesh(

    source_obj: bpy.types.Object,

    armature_obj: bpy.types.Object,

    target_mask: int,

    poly_indices: list[int],

) -> bpy.types.Object | None:

    """Create one skinned child mesh containing only faces for ``target_mask`` (-1 = unmasked)."""

    mesh = source_obj.data

    if not isinstance(mesh, bpy.types.Mesh):

        return None



    built = _build_mesh_from_polygons(mesh, poly_indices)

    if built is None:

        return None

    new_mesh, source_vert_indices = built



    for mat in mesh.materials:

        new_mesh.materials.append(mat)



    suffix = "base" if target_mask < 0 else f"mask{target_mask:02d}"

    new_name = f"{source_obj.name}_{suffix}"

    new_mesh.name = new_name

    new_obj = bpy.data.objects.new(new_name, new_mesh)

    _copy_vertex_groups_subset(source_obj, new_obj, source_vert_indices)

    if hasattr(source_obj, "soulstruct_type"):

        new_obj.soulstruct_type = source_obj.soulstruct_type

    for collection in source_obj.users_collection:

        if new_obj.name not in collection.objects:

            collection.objects.link(new_obj)



    new_obj.parent = armature_obj

    new_obj.matrix_parent_inverse = source_obj.matrix_parent_inverse.copy()

    new_obj.location = source_obj.location.copy()

    new_obj.rotation_euler = source_obj.rotation_euler.copy()

    new_obj.scale = source_obj.scale.copy()



    _copy_armature_modifier(source_obj, new_obj)

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

            if _extract_mask_submesh(source, armature_obj, mask_id, polys_by_mask[mask_id]) is not None:

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


