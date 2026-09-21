"""Blender headless: retarget Mixamo clips onto the Keanu rig and export a GLB.

Run with Blender, not the project venv:

    /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
        --python mavis/tools/retarget_anim.py -- \
        <keanu.fbx> <texture-dir> <out.glb> idle=<Breathing Idle.fbx> smoking=<Smoking.fbx>

The model ships with **no animation at all** -- a game rip gives you the mesh
and the skeleton in its authoring bind pose, arms out at 45 degrees. That pose
is most of why the avatar read as a mannequin, and no amount of procedural
head-drift on top of it helps.

**How the retarget works, and why the obvious way fails.** Each bone's rotation
is transferred as a *world-space* delta from its own rest pose:

    tgt_rot = (src_rot @ src_rest^-1) @ tgt_rest

At rest that is the identity. Because the delta is expressed in world space
rather than in either skeleton's local bone frame, it survives Mixamo and
ValveBiped having entirely different bone rolls and axis conventions. The
tempting alternative -- copying local rotations -- assumes the two rigs agree
on what "bend forward" means per bone, and produces arms rotated into the
torso.

Bones are posed parents-first so a child's world matrix is computed against a
parent already in its final pose.

Only the 22 body bones below are driven. The 283 CDPR facial joints are left
alone deliberately: `mid_J_jaw_JNT` stays free for lipsync to control, and
Mixamo has nothing to say about a face anyway.
"""
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fbx_to_glb as conv  # noqa: E402

TARGET_HEIGHT = 1.8

M = "mixamorig:"
V = "ValveBiped.Bip01_"

BONE_MAP = {
    M + "Hips": V + "Pelvis",
    M + "Spine": V + "Spine",
    M + "Spine1": V + "Spine1",
    M + "Spine2": V + "Spine2",
    M + "Neck": V + "Neck1",
    M + "Head": V + "Head1",
    M + "LeftShoulder": V + "L_Clavicle",
    M + "LeftArm": V + "L_UpperArm",
    M + "LeftForeArm": V + "L_Forearm",
    M + "LeftHand": V + "L_Hand",
    M + "RightShoulder": V + "R_Clavicle",
    M + "RightArm": V + "R_UpperArm",
    M + "RightForeArm": V + "R_Forearm",
    M + "RightHand": V + "R_Hand",
    M + "LeftUpLeg": V + "L_Thigh",
    M + "LeftLeg": V + "L_Calf",
    M + "LeftFoot": V + "L_Foot",
    M + "LeftToeBase": V + "L_Toe0",
    M + "RightUpLeg": V + "R_Thigh",
    M + "RightLeg": V + "R_Calf",
    M + "RightFoot": V + "R_Foot",
    M + "RightToeBase": V + "R_Toe0",
}
ROOT_SRC = M + "Hips"


def _depth(bone):
    count = 0
    while bone.parent:
        bone = bone.parent
        count += 1
    return count


def retarget(target, anim_fbx, action_name):
    """Bake one clip onto `target`, returning the new action."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=anim_fbx)
    imported = [o for o in bpy.data.objects if o not in before]
    source = next(o for o in imported if o.type == "ARMATURE")

    scene = bpy.context.scene
    start, end = scene.frame_start, scene.frame_end

    pairs = [(source.pose.bones[s], target.pose.bones[t])
             for s, t in BONE_MAP.items()
             if s in source.pose.bones and t in target.pose.bones]
    print(f"  mapped {len(pairs)}/{len(BONE_MAP)} bones")

    correction = {t.name: (s.bone.matrix_local.to_3x3().inverted(),
                           t.bone.matrix_local.to_3x3())
                  for s, t in pairs}

    # Hip travel is scaled by the height ratio, or a short character inherits a
    # tall rig's stride.
    src_h = max(b.head.z for b in source.pose.bones) or 1.0
    tgt_h = max(b.head.z for b in target.pose.bones) or 1.0
    hip_scale = tgt_h / src_h

    pairs.sort(key=lambda p: _depth(p[1].bone))
    root_tgt = target.pose.bones[BONE_MAP[ROOT_SRC]]
    root_src = source.pose.bones[ROOT_SRC]
    tgt_rest_head = root_tgt.bone.matrix_local.translation.copy()
    src_rest_head = root_src.bone.matrix_local.translation.copy()

    target.animation_data_create()
    action = bpy.data.actions.new(action_name)
    target.animation_data.action = action
    for pose_bone in target.pose.bones:
        pose_bone.rotation_mode = "QUATERNION"

    for frame in range(start, end + 1):
        scene.frame_set(frame)
        for s, t in pairs:
            src_inv, tgt_rest = correction[t.name]
            matrix = ((s.matrix.to_3x3() @ src_inv) @ tgt_rest).to_4x4()
            if t is root_tgt:
                matrix.translation = tgt_rest_head + (
                    s.matrix.translation - src_rest_head) * hip_scale
            else:
                matrix.translation = t.matrix.translation
            t.matrix = matrix
            bpy.context.view_layer.update()
        for _s, t in pairs:
            t.keyframe_insert("rotation_quaternion", frame=frame)
            if t is root_tgt:
                t.keyframe_insert("location", frame=frame)

    print(f"  baked {end - start + 1} frames as {action_name!r}")

    # Names first: removing an object dangles every other reference to it.
    for name in [o.name for o in imported]:
        obj = bpy.data.objects.get(name)
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)

    target.animation_data.action = None
    return action


def wire_textures(texdir):
    """Same material resolution the plain converter does; see fbx_to_glb."""
    shipped = conv._texture_index(texdir)
    targets = conv._mtl_targets(texdir)
    learned = {}
    for name, original in targets.items():
        if name in shipped:
            learned.setdefault(original, name)

    cache = {}

    def load(filename):
        path = os.path.join(texdir, filename)
        if not os.path.exists(path):
            return None
        if path not in cache:
            cache[path] = bpy.data.images.load(path)
        return cache[path]

    wired = 0
    for material in bpy.data.materials:
        stem = conv.resolve_texture(material.name, shipped, targets, learned)
        base = load(f"{stem}.tga") if stem else None
        if base is None:
            continue
        cap = (conv.FACE_TEXTURE_MAX if material.name in conv.FACE_MATERIALS
               else conv.OTHER_TEXTURE_MAX)
        conv._resize(base, cap)

        material.use_nodes = True
        tree = material.node_tree
        tree.nodes.clear()
        output = tree.nodes.new("ShaderNodeOutputMaterial")
        shader = tree.nodes.new("ShaderNodeBsdfPrincipled")
        tree.links.new(shader.outputs["BSDF"], output.inputs["Surface"])
        colour = tree.nodes.new("ShaderNodeTexImage")
        colour.image = base
        tree.links.new(colour.outputs["Color"], shader.inputs["Base Color"])
        tree.links.new(colour.outputs["Alpha"], shader.inputs["Alpha"])

        normal = load(f"{stem}_n.tga")
        if normal is not None:
            normal.colorspace_settings.name = "Non-Color"
            conv._resize(normal, cap)
            normal_tex = tree.nodes.new("ShaderNodeTexImage")
            normal_tex.image = normal
            normal_map = tree.nodes.new("ShaderNodeNormalMap")
            tree.links.new(normal_tex.outputs["Color"], normal_map.inputs["Color"])
            tree.links.new(normal_map.outputs["Normal"], shader.inputs["Normal"])

        for attribute, value in (("blend_method", "BLEND"),
                                 ("surface_render_method", "BLENDED")):
            try:
                setattr(material, attribute, value)
                break
            except (AttributeError, TypeError):
                continue
        wired += 1
    print(f"WIRED {wired}/{len(bpy.data.materials)} materials")


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    target_fbx, texdir, out_glb = argv[0], argv[1], argv[2]
    clips = [spec.split("=", 1) for spec in argv[3:]]
    if not clips:
        raise SystemExit("give at least one clip as name=path/to/clip.fbx")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=target_fbx, automatic_bone_orientation=True)
    target = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    target.name = "Johnny"

    ours = []
    for name, path in clips:
        print(f"CLIP {name} <- {os.path.basename(path)}")
        ours.append(retarget(target, path, name))

    # Purge every action we did not create. Importing a clip brings its own
    # Mixamo action along, and those survive deleting the object that used
    # them -- they would otherwise be exported beside ours as a second,
    # meaningless animation on the finished model.
    keep = {action.name for action in ours}
    for action in list(bpy.data.actions):
        if action.name not in keep:
            print(f"  purged stray action {action.name!r}")
            bpy.data.actions.remove(action)

    # One NLA track per clip is what makes the glTF exporter emit each as its
    # own named animation rather than exporting only the active action.
    target.animation_data.action = None
    for action in ours:
        track = target.animation_data.nla_tracks.new()
        track.name = action.name
        track.strips.new(action.name, int(action.frame_range[0]), action)

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    for obj in meshes:
        obj.data.name = obj.name
    wire_textures(texdir)

    low = Vector((1e9,) * 3)
    high = Vector((-1e9,) * 3)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj in meshes:
        for corner in obj.evaluated_get(depsgraph).bound_box:
            world = obj.matrix_world @ Vector(corner)
            low = Vector((min(low[i], world[i]) for i in range(3)))
            high = Vector((max(high[i], world[i]) for i in range(3)))
    height = high[2] - low[2]
    factor = TARGET_HEIGHT / height
    target.scale = tuple(value * factor for value in target.scale)
    print(f"SCALED {height:.2f} -> {TARGET_HEIGHT} (factor {factor:.5f})")

    bpy.ops.export_scene.gltf(
        filepath=out_glb, export_format="GLB", export_skins=True,
        export_yup=True, export_animations=True, export_apply=False,
    )
    print(f"EXPORTED {out_glb} with {len(ours)} animation(s): "
          f"{', '.join(sorted(keep))}")


if __name__ == "__main__":
    main()
