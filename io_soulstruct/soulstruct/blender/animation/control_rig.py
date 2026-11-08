"""Animator control rig for FromSoftware humanoid skeletons.

Builds Blender-only IK controls on any FLVER Armature that uses FromSoftware's biped bone names, in either naming
scheme seen across the games:
    3ds Max Biped style (DS1/DS3-era ports, e.g. Nightreign c7720):  'L Thigh', 'LUpArmTwist', 'L ForeTwist'
    Elden Ring style (most Nightreign characters):                   'L_Thigh', 'L_UpArmTwist1', 'L_ForeArmTwist'

What it adds (all bones tagged with `CONTROL_RIG_BONE_PROP`, so FLVER export skips them and HKX export never sees
them, since they are not in the HKX skeleton):
    - Per leg/arm: a foot/hand IK control and a knee/elbow pole (parented to 'Master' when present), solved on a
      clean two-bone mechanism chain ('mch_*'). Game bones copy that chain, so odd game layouts (1 cm Elden Ring
      limb bones, unconnected joints, arbitrary bone rolls) never reach the IK solver.
    - An 'ik' slider (0 = FK keys, 1 = IK) on every control, driving all the limb's rig constraints.
    - Twist and joint-helper bones ('*Twist*', 'L_Elbow', 'L_Knee') driven from their limbs, with ratios calibrated
      from the animations already loaded on the Armature (vanilla clips), so the rig reproduces FromSoft's own twist
      distribution per character.

Animation export bakes all of this through the 'Bake Constraints' export setting. Game bones only get constraints
named with `RIG_CONSTRAINT_PREFIX`, which `remove_control_rig()` deletes again.
"""
from __future__ import annotations

__all__ = [
    "AddControlRig",
    "RemoveControlRig",
    "MatchControlsToPose",
    "build_control_rig",
    "remove_control_rig",
    "match_controls_to_pose",
    "find_limb_chains",
]

import math
import re
import typing as tp
from dataclasses import dataclass, field

import bpy
from mathutils import Matrix, Quaternion, Vector

from ..base.operators import LoggingOperator
from ..base.register import io_soulstruct_operator
from ..flver.models.types.bl_flver._export_bones import CONTROL_RIG_BONE_PROP
from ..types import ArmatureObject
from .utilities import get_active_flver_or_part_armature

RIG_CONSTRAINT_PREFIX = "CR "
CONTROLS_COLLECTION = "Rig Controls"
MECHANICS_COLLECTION = "Rig Mechanics"
IK_PROP = "ik"

_SIDES = ("L", "R")
_SIDE_SUFFIX = {"L": ".L", "R": ".R"}
# Twist bone name -> limb base name.
_TWIST_RE = re.compile(r"^(L|R)[ _]?(UpArm|ForeArm|Fore|Thigh|Calf)Twist(\d*)$")
_TWIST_LIMB = {"UpArm": "UpperArm", "ForeArm": "Forearm", "Fore": "Forearm", "Thigh": "Thigh", "Calf": "Calf"}
# Limb -> extra twist sources to calibrate against (besides the limb itself).
_TWIST_EXTRA_SOURCES = {"UpperArm": ("Forearm", "Hand"), "Forearm": ("Hand",), "Thigh": ("Calf", "Foot"), "Calf": ("Foot",)}
# Default twist ratios when no animation is loaded to calibrate from (measured on vanilla c7720 clips).
_DEFAULT_TWIST = {"Forearm": ("Hand", 0.95), "Thigh": ("Thigh", -0.25)}
_HELPER_RE = re.compile(r"^(L|R)[ _](Elbow|Knee)$")
_HELPER_LIMB = {"Elbow": "Forearm", "Knee": "Calf"}


@dataclass(slots=True)
class LimbChain:
    side: str
    kind: str  # "leg" or "arm"
    upper: str
    mid: str
    end: str

    @property
    def tag(self) -> str:
        return f"{self.kind}{_SIDE_SUFFIX[self.side]}"


@dataclass(slots=True)
class RigReport:
    chains: list[str] = field(default_factory=list)
    twists: list[str] = field(default_factory=list)
    helpers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    calibrated_from: int = 0


def _bone_name(bones, side: str, base: str) -> str | None:
    for name in (f"{side} {base}", f"{side}_{base}", f"{side}{base}"):
        if name in bones:
            return name
    return None


def find_limb_chains(armature: ArmatureObject) -> list[LimbChain]:
    """Find the two-bone IK chains (thigh/calf/foot and upper arm/forearm/hand) the Armature has."""
    bones = armature.data.bones
    chains = []
    for side in _SIDES:
        for kind, (u, m, e) in (("leg", ("Thigh", "Calf", "Foot")), ("arm", ("UpperArm", "Forearm", "Hand"))):
            names = [_bone_name(bones, side, base) for base in (u, m, e)]
            if all(names):
                chains.append(LimbChain(side, kind, *names))
    return chains


def _limb_base(limb_name: str) -> str:
    return next(base for base in set(_TWIST_LIMB.values()) if limb_name.endswith(base))


def _is_rig_constraint(constraint: bpy.types.Constraint) -> bool:
    return constraint.name.startswith(RIG_CONSTRAINT_PREFIX)


def _swing_twist_axis(q: Quaternion, axis: Vector) -> float:
    """Signed twist angle of `q` about unit `axis` (expressed in the same frame as `q`)."""
    v = Vector((q.x, q.y, q.z))
    p = axis * v.dot(axis)
    tw = Quaternion((q.w, p.x, p.y, p.z))
    if tw.magnitude < 1e-9:
        return 0.0
    tw.normalize()
    angle = 2.0 * math.atan2(Vector((tw.x, tw.y, tw.z)).dot(axis), tw.w)
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


# Twist axis of each limb bone: (from bone, to bone). Hand/foot twist is measured about the forearm/shin axis.
_TWIST_AXIS = {
    "UpperArm": ("UpperArm", "Forearm"),
    "Forearm": ("Forearm", "Hand"),
    "Hand": ("Forearm", "Hand"),
    "Thigh": ("Thigh", "Calf"),
    "Calf": ("Calf", "Foot"),
    "Foot": ("Calf", "Foot"),
}


def _twist_axis(bones, bone_name: str) -> Vector | None:
    """Armature-space rest direction a limb bone twists about (joint to joint, not the bone's own Y axis: Elden Ring
    limb bones can be 1 cm long and point anywhere)."""
    side = bone_name[0]
    base = next((b for b in _TWIST_AXIS if bone_name.endswith(b)), None)
    if base is None:
        return None
    start, end = (_bone_name(bones, side, b) for b in _TWIST_AXIS[base])
    if not start or not end:
        return None
    direction = bones[end].head_local - bones[start].head_local
    return direction.normalized() if direction.length > 1e-6 else None


# region Pose helpers

class _PoseSandbox:
    """Temporarily detach the action, zero every pose channel and mute constraints listed in `mute`."""

    def __init__(self, armature: ArmatureObject, mute: tp.Iterable[bpy.types.Constraint] = ()):
        self.armature = armature
        self.mute = list(mute)

    def __enter__(self):
        arm = self.armature
        self.action = arm.animation_data.action if arm.animation_data else None
        if self.action:
            arm.animation_data.action = None
        self.channels = {
            pb.name: (pb.location.copy(), pb.rotation_quaternion.copy(), pb.rotation_euler.copy(), pb.scale.copy())
            for pb in arm.pose.bones
        }
        for pb in arm.pose.bones:
            pb.location = (0.0, 0.0, 0.0)
            pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
            pb.rotation_euler = (0.0, 0.0, 0.0)
            pb.scale = (1.0, 1.0, 1.0)
        self.muted = [(c, c.mute) for c in self.mute]
        for c, _ in self.muted:
            c.mute = True
        bpy.context.view_layer.update()
        return self

    def __exit__(self, *exc):
        arm = self.armature
        for c, was_muted in self.muted:
            c.mute = was_muted
        for pb in arm.pose.bones:
            loc, rq, re_, sc = self.channels[pb.name]
            pb.location, pb.rotation_quaternion, pb.rotation_euler, pb.scale = loc, rq, re_, sc
        if self.action:
            arm.animation_data.action = self.action
        bpy.context.view_layer.update()
        return False


def _armature_actions(armature: ArmatureObject, probe_bone: str) -> list[bpy.types.Action]:
    """Actions that key `probe_bone` (i.e. were made for this skeleton)."""
    path = f'pose.bones["{probe_bone}"]'

    def keys_probe(action: bpy.types.Action) -> bool:
        for layer in getattr(action, "layers", ()):
            for strip in layer.strips:
                for channelbag in strip.channelbags:
                    if any(fc.data_path.startswith(path) for fc in channelbag.fcurves):
                        return True
        return False

    return [action for action in bpy.data.actions if keys_probe(action)]


def _sample_frames(actions: list[bpy.types.Action], max_samples: int = 600) -> list[tuple[bpy.types.Action, int]]:
    frames = []
    for action in actions:
        f0, f1 = (int(v) for v in action.frame_range)
        frames.extend((action, f) for f in range(f0, f1 + 1))
    step = max(1, len(frames) // max_samples)
    return frames[::step]

# endregion


# region Calibration

@dataclass(slots=True)
class _TwistPlan:
    bone: str
    limb: str
    source: str | None
    ratio: float
    sibling: bool = False  # Biped layout: twist bone is a child of the limb's parent, not of the limb


@dataclass(slots=True)
class _HelperPlan:
    bone: str
    limb: str
    weight: float


def _calibrate(
    armature: ArmatureObject,
    twist_bones: list[tuple[str, str]],
    helpers: list[tuple[str, str]],
    report: RigReport,
) -> tuple[list[_TwistPlan], list[_HelperPlan]]:
    bones = armature.data.bones
    pose = armature.pose.bones

    twist_candidates = {}  # type: dict[str, list[str]]
    for twist, limb in twist_bones:
        side = twist[0]
        limb_base = _limb_base(limb)
        candidates = [limb]
        for extra in _TWIST_EXTRA_SOURCES.get(limb_base, ()):
            name = _bone_name(bones, side, extra)
            if name:
                candidates.append(name)
        twist_candidates[twist] = candidates

    probe = twist_bones[0][1] if twist_bones else (helpers[0][1] if helpers else None)
    actions = _armature_actions(armature, probe) if probe else []
    samples = _sample_frames(actions)
    report.calibrated_from = len(actions)

    # Twist axes in each bone's own rest frame: the limb axis for twist bones, the source's axis for sources.
    axes_local = {}  # type: dict[str, Vector]
    for twist, limb in list(twist_bones):
        limb_axis = _twist_axis(bones, limb)
        if limb_axis is None:
            twist_bones.remove((twist, limb))
            continue
        axes_local[twist] = bones[twist].matrix_local.to_quaternion().inverted() @ limb_axis
        for cand in list(twist_candidates[twist]):
            cand_axis = _twist_axis(bones, cand)
            if cand_axis is None:
                twist_candidates[twist].remove(cand)
                continue
            axes_local[cand] = bones[cand].matrix_local.to_quaternion().inverted() @ cand_axis
    twist_data = {twist: ([], {c: [] for c in twist_candidates[twist]}) for twist, _ in twist_bones}
    helper_data = {h: [] for h, _ in helpers}

    if samples:
        all_constraints = [c for pb in pose for c in pb.constraints]
        original_action = armature.animation_data.action if armature.animation_data else None
        mutes = [(c, c.mute) for c in all_constraints]
        for c, _ in mutes:
            c.mute = True
        try:
            for action, frame in samples:
                armature.animation_data.action = action
                bpy.context.scene.frame_set(frame)
                for twist, limb in twist_bones:
                    limb_rest = bones[limb].matrix_local.to_quaternion()
                    tw_rest = bones[twist].matrix_local.to_quaternion()
                    rigid = pose[limb].matrix.to_quaternion() @ limb_rest.inverted() @ tw_rest
                    deviation = rigid.inverted() @ pose[twist].matrix.to_quaternion()
                    twist_data[twist][0].append(_swing_twist_axis(deviation, axes_local[twist]))
                    for cand in twist_candidates[twist]:
                        twist_data[twist][1][cand].append(
                            _swing_twist_axis(pose[cand].rotation_quaternion, axes_local[cand])
                        )
                for helper, limb in helpers:
                    # Both bones share a parent: compare local rotations expressed in the helper's rest frame.
                    rel = bones[helper].matrix_local.to_quaternion().inverted() @ bones[limb].matrix_local.to_quaternion()
                    limb_local = rel @ pose[limb].rotation_quaternion @ rel.inverted()
                    helper_data[helper].append((pose[helper].rotation_quaternion.copy(), limb_local))
        finally:
            for c, was in mutes:
                c.mute = was
            armature.animation_data.action = original_action

    twist_plans = []
    for twist, limb in twist_bones:
        values, sources = twist_data[twist]
        best = None
        if values:
            total = sum(v * v for v in values)
            for cand, src in sources.items():
                den = sum(s * s for s in src)
                if den < 1e-6:
                    continue
                k = sum(v * s for v, s in zip(values, src)) / den
                residual = sum((v - k * s) ** 2 for v, s in zip(values, src))
                explained = 1.0 - residual / total if total > 1e-9 else 0.0
                if best is None or explained > best[2]:
                    best = (cand, k, explained)
            if best is not None and best[2] < 0.5:
                report.warnings.append(
                    f"{twist}: twist does not follow any limb consistently in the loaded animations "
                    f"(best {best[0]} explains {best[2]:.0%}); it will follow {limb} without extra twist."
                )
                best = (None, 0.0, best[2])
        else:
            default = _DEFAULT_TWIST.get(_limb_base(limb))
            if default:
                src = _bone_name(bones, twist[0], default[0])
                best = (src, default[1], 1.0) if src else None
        source, ratio = (best[0], best[1]) if best else (None, 0.0)
        if source is not None and abs(ratio) < 0.02:
            source, ratio = None, 0.0
        parent = bones[twist].parent
        if parent is not None and parent.name == limb:
            sibling = False
        elif parent is not None and parent == bones[limb].parent:
            sibling = True
        else:
            report.warnings.append(
                f"{twist}: parent '{parent.name if parent else None}' is neither {limb} nor its parent (re-parented?); "
                f"not driven by the rig."
            )
            continue
        twist_plans.append(_TwistPlan(twist, limb, source, round(ratio, 3), sibling))

    helper_plans = []
    for helper, limb in helpers:
        data = helper_data[helper]
        weight = 0.5
        if data:
            best_t, best_err = 0.0, None
            for i in range(21):
                t = i / 20
                err = 0.0
                for helper_q, limb_q in data:
                    target = Quaternion().slerp(limb_q, t)
                    err += helper_q.rotation_difference(target).angle
                if best_err is None or err < best_err:
                    best_t, best_err = t, err
            weight = best_t
        if weight > 0.0:
            helper_plans.append(_HelperPlan(helper, limb, weight))
    return twist_plans, helper_plans

# endregion


# region Twist/helper key conversion

_DRIVEN_PREFIXES = (f"{RIG_CONSTRAINT_PREFIX}Twist", f"{RIG_CONSTRAINT_PREFIX}Helper")


def _driven_bone_names(armature: ArmatureObject) -> list[str]:
    """Game bones whose rotation the rig drives 'Before Original' (twist and joint helper bones)."""
    return [
        pb.name for pb in armature.pose.bones
        if not armature.data.bones[pb.name].get(CONTROL_RIG_BONE_PROP)
        and any(c.name.startswith(_DRIVEN_PREFIXES) for c in pb.constraints)
        and pb.rotation_mode == "QUATERNION"
    ]


def _local_rotation(armature: ArmatureObject, name: str) -> Quaternion:
    """Evaluated (post-constraint) rotation of a bone relative to its rest pose in its parent: the value its rotation
    channel would need to produce the same pose without constraints."""
    pb = armature.pose.bones[name]
    bone = armature.data.bones[name]
    if bone.parent is None:
        frame = bone.matrix_local.to_quaternion()
    else:
        frame = (
            pb.parent.matrix.to_quaternion()
            @ bone.parent.matrix_local.to_quaternion().inverted()
            @ bone.matrix_local.to_quaternion()
        )
    return frame.inverted() @ pb.matrix.to_quaternion()


def _convert_keys(armature: ArmatureObject, bone_names: list[str], to_residual: bool) -> int:
    """Rewrite rotation keys of rig-driven bones in every action keying them.

    `to_residual`: keys hold full rotations (as imported) -> store only the remainder on top of the rig.
    Otherwise: keys hold remainders -> store the full rotation again (before the rig is removed).
    Evaluated in FK (IK follow constraints muted), which is how the keys were authored. Returns keys rewritten.
    """
    if not bone_names or armature.animation_data is None:
        return 0
    pose = armature.pose.bones
    paths = {f'pose.bones["{n}"].rotation_quaternion': n for n in bone_names}
    ik_constraints = [c for pb in pose for c in pb.constraints if c.name.startswith(f"{RIG_CONSTRAINT_PREFIX}IK")]
    saved_mutes = [(c, c.mute) for c in ik_constraints]
    for c, _ in saved_mutes:
        c.mute = True
    original_action = armature.animation_data.action
    scene = bpy.context.scene
    original_frame = scene.frame_current
    count = 0
    try:
        for action in bpy.data.actions:
            frames_by_bone = {}  # type: dict[str, set[int]]
            for layer in getattr(action, "layers", ()):
                for strip in layer.strips:
                    for channelbag in strip.channelbags:
                        for fc in channelbag.fcurves:
                            if fc.data_path in paths:
                                frames_by_bone.setdefault(paths[fc.data_path], set()).update(
                                    int(round(kp.co[0])) for kp in fc.keyframe_points
                                )
            if not frames_by_bone:
                continue
            armature.animation_data.action = action
            all_frames = sorted(set().union(*frames_by_bone.values()))
            previous = {}  # type: dict[str, Quaternion]
            for frame in all_frames:
                scene.frame_set(frame)
                updates = {}
                for name, frames in frames_by_bone.items():
                    if frame not in frames:
                        continue
                    own = pose[name].rotation_quaternion.copy()
                    result = _local_rotation(armature, name)
                    if to_residual:
                        rig = result @ own.inverted()  # what the rig applies before the channel
                        new = rig.inverted() @ own
                    else:
                        new = result
                    if name in previous and previous[name].dot(new) < 0.0:
                        new.negate()
                    previous[name] = new
                    updates[name] = new
                for name, new in updates.items():
                    pose[name].rotation_quaternion = new
                    pose[name].keyframe_insert("rotation_quaternion", frame=frame)
                    count += 1
    finally:
        for c, was in saved_mutes:
            c.mute = was
        armature.animation_data.action = original_action
        scene.frame_set(original_frame)
    return count

# endregion


# region Build / remove

def _new_bone(edit_bones, name: str, head: Vector, tail: Vector, parent, roll_target: Vector | None = None):
    bone = edit_bones.new(name)
    bone.head, bone.tail = head, tail
    if roll_target is not None:
        bone.align_roll(roll_target)
    bone.parent = parent
    bone.use_deform = False
    bone[CONTROL_RIG_BONE_PROP] = 1
    return bone


def _copy_bone_matrix(edit_bones, name: str, source, parent, length: float):
    bone = edit_bones.new(name)
    # Copy head, direction and roll explicitly: assigning `matrix` to a new zero-length EditBone flips it.
    bone.head = source.head.copy()
    bone.tail = source.head + (source.tail - source.head).normalized() * length
    bone.roll = source.roll
    bone.parent = parent
    bone.use_deform = False
    bone[CONTROL_RIG_BONE_PROP] = 1
    return bone


def _add_ik_driver(armature: ArmatureObject, constraint: bpy.types.Constraint, control: str):
    fcurve = constraint.driver_add("influence")
    driver = fcurve.driver
    driver.type = "AVERAGE"
    var = driver.variables.new()
    var.name = "ik"
    var.type = "SINGLE_PROP"
    var.targets[0].id_type = "OBJECT"
    var.targets[0].id = armature
    var.targets[0].data_path = f'pose.bones["{control}"]["{IK_PROP}"]'


def _pole_direction(upper_head: Vector, mid_head: Vector, end_head: Vector, fallback: Vector) -> Vector:
    axis = end_head - upper_head
    if axis.length < 1e-6:
        return fallback.normalized()
    closest = upper_head + axis * ((mid_head - upper_head).dot(axis) / axis.length_squared)
    bend = mid_head - closest
    if bend.length < 0.02 * axis.length:  # (nearly) straight limb in rest pose
        bend = fallback - axis * (fallback.dot(axis) / axis.length_squared)
    return bend.normalized()


def build_control_rig(
    armature: ArmatureObject,
    arms_ik: bool = False,
    legs_ik: bool = True,
    rig_twists: bool = True,
) -> RigReport:
    """Build the control rig on `armature` (removing any previous one first). See module docstring."""
    report = RigReport()
    remove_control_rig(armature)
    bones = armature.data.bones
    chains = find_limb_chains(armature)
    if not chains:
        raise ValueError(
            "No FromSoftware biped limbs found (need e.g. 'L Thigh'/'L Calf'/'L Foot' or 'L_Thigh'/'L_Calf'/'L_Foot')."
        )

    master = "Master" if "Master" in bones else None
    foreign = sorted({
        pb.name for pb in armature.pose.bones for c in pb.constraints
        if not _is_rig_constraint(c) and not c.mute and c.influence > 0
    })
    if foreign:
        report.warnings.append(
            f"{len(foreign)} bone(s) already have other constraints, which stay active on top of this rig and may "
            f"fight it: {', '.join(foreign[:10])}{' ...' if len(foreign) > 10 else ''}"
        )
    for chain in chains:
        if bones[chain.end].parent is None or bones[chain.end].parent.name != chain.mid:
            report.warnings.append(
                f"'{chain.end}' is not parented to '{chain.mid}' (re-parented?); the game skeleton expects it to be."
            )

    # Twist bones and joint helpers, plus calibration (before adding any rig constraints).
    twist_bones = []  # type: list[tuple[str, str]]
    helpers = []  # type: list[tuple[str, str]]
    if rig_twists:
        for bone in bones:
            if m := _TWIST_RE.match(bone.name):
                limb = _bone_name(bones, m.group(1), _TWIST_LIMB[m.group(2)])
                if limb:
                    twist_bones.append((bone.name, limb))
            elif m := _HELPER_RE.match(bone.name):
                limb = _bone_name(bones, m.group(1), _HELPER_LIMB[m.group(2)])
                if limb and bone.parent and bones[limb].parent == bone.parent:
                    helpers.append((bone.name, limb))
    twist_plans, helper_plans = _calibrate(armature, twist_bones, helpers, report)

    # 1. Bones (EDIT mode).
    prev_active = bpy.context.view_layer.objects.active
    prev_mode = armature.mode
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="EDIT")
    eb = armature.data.edit_bones
    try:
        master_eb = eb.get(master) if master else None
        names = {}  # chain tag -> dict of created bone names
        for chain in chains:
            sfx = _SIDE_SUFFIX[chain.side]
            up, mid, end = eb[chain.upper], eb[chain.mid], eb[chain.end]
            upper_head, mid_head, end_head = up.head.copy(), mid.head.copy(), end.head.copy()
            seg = (mid_head - upper_head).length + (end_head - mid_head).length
            # Characters face -Y in Blender: knees bend forward, elbows backward.
            fallback = Vector((0.0, -1.0, 0.0)) if chain.kind == "leg" else Vector((0.0, 1.0, 0.0))
            pole_dir = _pole_direction(upper_head, mid_head, end_head, fallback)
            joint = "knee" if chain.kind == "leg" else "elbow"
            effector = "foot" if chain.kind == "leg" else "hand"
            n = {
                "root": f"mch_{chain.kind}_root{sfx}",
                "upper": f"mch_{chain.kind}_upper{sfx}",
                "lower": f"mch_{chain.kind}_lower{sfx}",
                "upper_follow": f"mch_{chain.kind}_upper_follow{sfx}",
                "mid_follow": f"mch_{chain.kind}_mid_follow{sfx}",
                "ctrl": f"ctrl_{effector}_ik{sfx}",
                "pole": f"ctrl_{joint}_pole{sfx}",
            }
            names[chain.tag] = n
            # Root anchor: same rest as the game's upper bone, location driven by its location keys (vanilla clips
            # translate thighs/upper arms), so the IK chain starts where the FK hip/shoulder really is.
            root = _copy_bone_matrix(eb, n["root"], up, up.parent, max(up.length, 0.05))
            upper_ik = _new_bone(eb, n["upper"], upper_head, mid_head, root, pole_dir)
            lower_ik = _new_bone(eb, n["lower"], mid_head, end_head, upper_ik, pole_dir)
            lower_ik.use_connect = True
            _copy_bone_matrix(eb, n["upper_follow"], up, upper_ik, max(up.length, 0.05))
            _copy_bone_matrix(eb, n["mid_follow"], mid, lower_ik, max(mid.length, 0.05))
            _copy_bone_matrix(eb, n["ctrl"], end, master_eb, max(0.15 * seg, 0.05))
            pole_head = mid_head + pole_dir * (0.5 * seg)
            _new_bone(eb, n["pole"], pole_head, pole_head + pole_dir * (0.08 * seg), master_eb)

        # Twist drivers. Twist is measured and applied about joint-to-joint limb axes via axis-aligned mechanism
        # bones, because game limb bones' own Y axes need not run along the limb.
        twist_sources = {plan.source for plan in twist_plans if plan.source}
        for source in twist_sources:
            src = eb[source]
            axis = _twist_axis(bones, source)
            _new_bone(eb, f"mch_twist_src_{source}", src.head.copy(), src.head + axis * 0.1, src.parent)
        for plan in twist_plans:
            if plan.source:
                tw = eb[plan.bone]
                axis = _twist_axis(bones, plan.limb)
                _new_bone(eb, f"mch_twist_{plan.bone}", tw.head.copy(), tw.head + axis * 0.1, eb[plan.limb])
    finally:
        bpy.ops.object.mode_set(mode="POSE")

    # 2. Bone collections, display.
    coll_controls = armature.data.collections.get(CONTROLS_COLLECTION) or armature.data.collections.new(
        CONTROLS_COLLECTION
    )
    coll_mech = armature.data.collections.get(MECHANICS_COLLECTION) or armature.data.collections.new(
        MECHANICS_COLLECTION
    )
    coll_mech.is_visible = False
    for bone in armature.data.bones:
        if bone.get(CONTROL_RIG_BONE_PROP):
            (coll_controls if bone.name.startswith("ctrl_") else coll_mech).assign(bone)
            if bone.name.startswith("ctrl_"):
                bone.color.palette = "THEME01" if bone.name.endswith(".L") else "THEME04"

    # 3. Constraints.
    pose = armature.pose.bones
    for chain in chains:
        n = names[chain.tag]
        ctrl = pose[n["ctrl"]]
        ctrl[IK_PROP] = 1.0 if (legs_ik if chain.kind == "leg" else arms_ik) else 0.0
        ctrl.id_properties_ui(IK_PROP).update(min=0.0, max=1.0, soft_min=0.0, soft_max=1.0,
                                              description="0 = FK (keyframes on game bones), 1 = IK controls")
        for axis in range(3):
            fcurve = pose[n["root"]].driver_add("location", axis)
            fcurve.driver.type = "AVERAGE"
            var = fcurve.driver.variables.new()
            var.name = "loc"
            var.type = "SINGLE_PROP"
            var.targets[0].id_type = "OBJECT"
            var.targets[0].id = armature
            var.targets[0].data_path = f'pose.bones["{chain.upper}"].location[{axis}]'
        ik = pose[n["lower"]].constraints.new("IK")
        ik.name = f"{RIG_CONSTRAINT_PREFIX}IK"
        ik.target, ik.subtarget = armature, n["ctrl"]
        ik.pole_target, ik.pole_subtarget = armature, n["pole"]
        ik.chain_count = 2
        ik.use_stretch = False
        for game_bone, follow in ((chain.upper, n["upper_follow"]), (chain.mid, n["mid_follow"])):
            c = pose[game_bone].constraints.new("COPY_TRANSFORMS")
            c.name = f"{RIG_CONSTRAINT_PREFIX}IK Follow"
            c.target, c.subtarget = armature, follow
            _add_ik_driver(armature, c, n["ctrl"])
        c = pose[chain.end].constraints.new("COPY_ROTATION")
        c.name = f"{RIG_CONSTRAINT_PREFIX}IK Rotation"
        c.target, c.subtarget = armature, n["ctrl"]
        _add_ik_driver(armature, c, n["ctrl"])

    # 4. Pole angles: the rest pose must be reproduced exactly with IK on.
    foreign_constraints = [c for pb in pose for c in pb.constraints if not _is_rig_constraint(c)]
    with _PoseSandbox(armature, mute=foreign_constraints):
        for chain in chains:
            n = names[chain.tag]
            ik = pose[n["lower"]].constraints[f"{RIG_CONSTRAINT_PREFIX}IK"]
            rest_q = bones[n["upper"]].matrix_local.to_quaternion()

            def err(deg: float) -> float:
                ik.pole_angle = math.radians(deg)
                bpy.context.view_layer.update()
                return rest_q.rotation_difference(pose[n["upper"]].matrix.to_quaternion()).angle

            best = min(range(-180, 180, 5), key=err)
            fine = min((best + d / 4 for d in range(-20, 21)), key=err)
            ik.pole_angle = math.radians(fine)
            residual = math.degrees(err(fine))
            if residual > 0.5:
                report.warnings.append(f"{chain.tag}: IK reproduces rest pose only to {residual:.1f} deg.")
            report.chains.append(f"{chain.tag}: {chain.upper} > {chain.mid} > {chain.end} "
                                 f"(pole angle {fine:.1f}, IK {'on' if pose[n['ctrl']][IK_PROP] else 'off'})")

    # 5. Twist bones and helpers.
    for source in {plan.source for plan in twist_plans if plan.source}:
        # Source axis bone: the source's local rotation re-expressed with Y along its limb axis.
        c = pose[f"mch_twist_src_{source}"].constraints.new("COPY_ROTATION")
        c.name = f"{RIG_CONSTRAINT_PREFIX}Twist Source"
        c.target, c.subtarget = armature, source
        c.target_space, c.owner_space = "LOCAL_OWNER_ORIENT", "LOCAL"
        c.mix_mode = "REPLACE"
    for plan in twist_plans:
        # All twist constraints use 'Before Original' in local space: the rig's follow/twist is applied first and the
        # bone's own rotation channels stay on top, so animators can still twist it by hand (see `_convert_keys`).
        pb = pose[plan.bone]
        if plan.source:
            # Driver bone (child of the limb, Y along the limb axis) carries `ratio` x the source twist.
            t = pose[f"mch_twist_{plan.bone}"].constraints.new("TRANSFORM")
            t.name = f"{RIG_CONSTRAINT_PREFIX}Twist"
            t.target, t.subtarget = armature, f"mch_twist_src_{plan.source}"
            t.target_space, t.owner_space = "LOCAL", "LOCAL"
            t.map_from, t.map_to = "ROTATION", "ROTATION"
            t.from_rotation_mode = "SWING_TWIST_Y"
            t.from_min_y_rot, t.from_max_y_rot = -math.pi, math.pi
            t.map_to_x_from, t.map_to_y_from, t.map_to_z_from = "X", "Y", "Z"
            t.to_min_y_rot, t.to_max_y_rot = -math.pi * plan.ratio, math.pi * plan.ratio
            t.to_euler_order = "YXZ"
            t.mix_mode_rot = "REPLACE"
            c = pb.constraints.new("COPY_ROTATION")
            c.name = f"{RIG_CONSTRAINT_PREFIX}Twist Amount"
            c.target, c.subtarget = armature, f"mch_twist_{plan.bone}"
            c.target_space, c.owner_space = "LOCAL_OWNER_ORIENT", "LOCAL"
            c.mix_mode = "BEFORE"
        if plan.sibling:
            # Biped layout: the twist bone hangs off the limb's parent, so it must also be made to follow the limb.
            # Added after the twist so the result is limb @ twist @ own.
            c = pb.constraints.new("COPY_ROTATION")
            c.name = f"{RIG_CONSTRAINT_PREFIX}Twist Follow"
            c.target, c.subtarget = armature, plan.limb
            c.target_space, c.owner_space = "LOCAL_OWNER_ORIENT", "LOCAL"
            c.mix_mode = "BEFORE"
        report.twists.append(
            f"{plan.bone}: follows {plan.limb}" + (f", {plan.ratio:+.2f} x {plan.source} twist" if plan.source else "")
        )
    for plan in helper_plans:
        pb = pose[plan.bone]
        c = pb.constraints.new("COPY_ROTATION")
        c.name = f"{RIG_CONSTRAINT_PREFIX}Helper"
        c.target, c.subtarget = armature, plan.limb
        c.target_space, c.owner_space = "LOCAL_OWNER_ORIENT", "LOCAL"
        c.mix_mode = "BEFORE"
        c.influence = plan.weight
        report.helpers.append(f"{plan.bone}: {plan.weight:.2f} x {plan.limb} rotation")

    # 6. Existing keys on driven twist/helper bones hold their full (vanilla) rotation, which the rig now supplies:
    # rewrite them as the remainder on top of the rig, so every clip looks exactly as before and stays editable.
    converted = _convert_keys(armature, _driven_bone_names(armature), to_residual=True)
    if converted:
        report.warnings.append(
            f"Rewrote {converted} twist/helper keyframes in this character's animations as offsets on top of the rig "
            f"(clips look unchanged; 'Remove Control Rig' converts them back)."
        )

    # 7. Start the controls on the current pose so nothing jumps.
    match_controls_to_pose(armature, keyframe=False)

    bpy.ops.object.mode_set(mode=prev_mode if prev_mode in {"OBJECT", "POSE"} else "POSE")
    if prev_active is not None:
        bpy.context.view_layer.objects.active = prev_active
    return report


def remove_control_rig(armature: ArmatureObject) -> int:
    """Remove rig bones, rig constraints (and their drivers) and rig bone collections. Returns removed bone count."""
    rig_bone_names = [b.name for b in armature.data.bones if b.get(CONTROL_RIG_BONE_PROP)]
    _convert_keys(armature, _driven_bone_names(armature), to_residual=False)
    if armature.animation_data:
        for fcurve in list(armature.animation_data.drivers):
            if f'constraints["{RIG_CONSTRAINT_PREFIX}' in fcurve.data_path or any(
                f'pose.bones["{n}"]' in fcurve.data_path for n in rig_bone_names
            ):
                armature.animation_data.drivers.remove(fcurve)
    for pb in armature.pose.bones:
        for c in list(pb.constraints):
            if _is_rig_constraint(c):
                pb.constraints.remove(c)
    if rig_bone_names:
        prev_active = bpy.context.view_layer.objects.active
        prev_mode = armature.mode
        bpy.context.view_layer.objects.active = armature
        bpy.ops.object.mode_set(mode="EDIT")
        eb = armature.data.edit_bones
        for name in rig_bone_names:
            if name in eb:
                eb.remove(eb[name])
        bpy.ops.object.mode_set(mode=prev_mode if prev_mode in {"OBJECT", "POSE"} else "OBJECT")
        if prev_active is not None:
            bpy.context.view_layer.objects.active = prev_active
    for name in (CONTROLS_COLLECTION, MECHANICS_COLLECTION):
        coll = armature.data.collections.get(name)
        if coll is not None:
            armature.data.collections.remove(coll)
    # Remove keyframes on deleted control bones from every action of this armature.
    for action in bpy.data.actions:
        for layer in getattr(action, "layers", ()):
            for strip in layer.strips:
                for channelbag in strip.channelbags:
                    for fcurve in list(channelbag.fcurves):
                        if any(f'pose.bones["{n}"]' in fcurve.data_path for n in rig_bone_names):
                            channelbag.fcurves.remove(fcurve)
    return len(rig_bone_names)

# endregion


# region Match controls to FK pose

def _rig_chain_controls(armature: ArmatureObject) -> list[tuple[LimbChain, str, str]]:
    out = []
    for chain in find_limb_chains(armature):
        sfx = _SIDE_SUFFIX[chain.side]
        effector, joint = ("foot", "knee") if chain.kind == "leg" else ("hand", "elbow")
        ctrl, pole = f"ctrl_{effector}_ik{sfx}", f"ctrl_{joint}_pole{sfx}"
        if ctrl in armature.pose.bones and pole in armature.pose.bones:
            out.append((chain, ctrl, pole))
    return out


def match_controls_to_pose(
    armature: ArmatureObject,
    keyframe: bool = False,
    frames: tp.Iterable[int] | None = None,
) -> int:
    """Move IK controls and poles onto the FK pose (the game bones' own keyframes).

    With `keyframe`, keys the controls on each frame of `frames` (default: current frame only), so an existing
    animation can be edited with IK. Returns the number of frames matched.
    """
    pose = armature.pose.bones
    items = _rig_chain_controls(armature)
    if not items:
        return 0
    scene = bpy.context.scene
    frame_list = list(frames) if frames is not None else [scene.frame_current]
    original_frame = scene.frame_current
    # Disable the rig's effect on game bones while reading their FK pose (IK sliders driven to 0).
    follow_constraints = [
        c for pb in pose for c in pb.constraints
        if _is_rig_constraint(c) and c.name.startswith(f"{RIG_CONSTRAINT_PREFIX}IK ")
    ]
    saved = [(c, c.mute) for c in follow_constraints]
    for c, _ in saved:
        c.mute = True
    try:
        for frame in frame_list:
            scene.frame_set(frame)
            for chain, ctrl, pole in items:
                end_matrix = pose[chain.end].matrix.copy()
                upper_head = pose[chain.upper].head.copy()
                mid_head = pose[chain.mid].head.copy()
                end_head = pose[chain.end].head.copy()
                # For (nearly) straight limbs the bend plane is undefined: carry the rest pole direction along with
                # the FK upper bone's rotation instead.
                rest_pole = armature.data.bones[pole].head_local - armature.data.bones[chain.mid].head_local
                upper_delta = pose[chain.upper].matrix.to_3x3() @ armature.data.bones[chain.upper].matrix_local.to_3x3().inverted()
                fallback = upper_delta @ rest_pole
                pole_dir = _pole_direction(upper_head, mid_head, end_head, fallback)
                seg = (mid_head - upper_head).length + (end_head - mid_head).length
                pose[ctrl].matrix = end_matrix
                bpy.context.view_layer.update()
                pole_matrix = Matrix.Translation(mid_head + pole_dir * (0.5 * seg))
                pose[pole].matrix = pole_matrix @ armature.data.bones[pole].matrix_local.to_3x3().to_4x4()
                bpy.context.view_layer.update()
                if keyframe:
                    for name in (ctrl, pole):
                        pose[name].keyframe_insert("location", frame=frame)
                        pose[name].keyframe_insert("rotation_quaternion", frame=frame)
    finally:
        for c, was in saved:
            c.mute = was
        scene.frame_set(original_frame if keyframe else scene.frame_current)
    return len(frame_list)

# endregion


# region Operators

def _poll_armature(context) -> bool:
    armature, *_ = get_active_flver_or_part_armature(context)
    return armature is not None


@io_soulstruct_operator
class AddControlRig(LoggingOperator):
    bl_idname = "soulstruct.add_control_rig"
    bl_label = "Add Control Rig"
    bl_description = (
        "Add IK controls (feet, hands, knee/elbow poles) and twist/helper bone drivers to a FromSoftware humanoid "
        "FLVER Armature. Rebuilds the rig if one exists. Control bones are never exported to FLVER or HKX; export "
        "animations with 'Bake Constraints' on"
    )
    bl_options = {"REGISTER", "UNDO"}

    legs_ik: bpy.props.BoolProperty(name="Legs Start in IK", default=True)
    arms_ik: bpy.props.BoolProperty(name="Arms Start in IK", default=False)
    rig_twists: bpy.props.BoolProperty(
        name="Drive Twist/Helper Bones",
        description="Drive '*Twist*', 'Elbow' and 'Knee' bones from their limbs, calibrated from loaded animations",
        default=True,
    )

    @classmethod
    def poll(cls, context) -> bool:
        return _poll_armature(context)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        armature, *_ = get_active_flver_or_part_armature(context)
        try:
            report = build_control_rig(armature, arms_ik=self.arms_ik, legs_ik=self.legs_ik,
                                       rig_twists=self.rig_twists)
        except ValueError as ex:
            return self.error(str(ex))
        for w in report.warnings:
            self.warning(w)
        self.info(
            f"Control rig added: {len(report.chains)} limb(s), {len(report.twists)} twist and "
            f"{len(report.helpers)} helper bone(s) driven"
            + (f", calibrated from {report.calibrated_from} animation(s)." if report.calibrated_from else
               ". No animations loaded to calibrate twist from; using defaults.")
        )
        return {"FINISHED"}


@io_soulstruct_operator
class RemoveControlRig(LoggingOperator):
    bl_idname = "soulstruct.remove_control_rig"
    bl_label = "Remove Control Rig"
    bl_description = "Remove the control rig's bones, constraints and control keyframes (game bone keys are kept)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context) -> bool:
        return _poll_armature(context)

    def execute(self, context):
        armature, *_ = get_active_flver_or_part_armature(context)
        count = remove_control_rig(armature)
        self.info(f"Removed control rig ({count} bones).")
        return {"FINISHED"}


@io_soulstruct_operator
class MatchControlsToPose(LoggingOperator):
    bl_idname = "soulstruct.match_controls_to_pose"
    bl_label = "Match Controls to FK Pose"
    bl_description = (
        "Snap IK controls and poles onto the game bones' keyframed pose. 'Whole Animation' keys them on every frame, "
        "so an existing (e.g. vanilla) animation can be edited with IK"
    )
    bl_options = {"REGISTER", "UNDO"}

    whole_animation: bpy.props.BoolProperty(
        name="Whole Animation",
        description="Key the controls on every frame of the active action instead of only the current frame",
        default=False,
    )

    @classmethod
    def poll(cls, context) -> bool:
        if not _poll_armature(context):
            return False
        armature, *_ = get_active_flver_or_part_armature(context)
        return bool(_rig_chain_controls(armature))

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        armature, *_ = get_active_flver_or_part_armature(context)
        frames = None
        if self.whole_animation:
            action = armature.animation_data.action if armature.animation_data else None
            if action is None:
                return self.error("Armature has no active action.")
            f0, f1 = (int(v) for v in action.frame_range)
            frames = range(f0, f1 + 1)
        count = match_controls_to_pose(armature, keyframe=self.whole_animation, frames=frames)
        self.info(f"Matched controls to FK pose on {count} frame(s).")
        return {"FINISHED"}

# endregion
