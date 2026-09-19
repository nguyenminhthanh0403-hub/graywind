"""Blender headless converter: a textured, skinned FBX -> GLB for gltf2bam.

Run with Blender, not the project venv:

    /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
        --python mavis/tools/fbx_to_glb.py -- <in.fbx> <out.glb> <texture-dir> [height]

Written for the KonnieGFX Johnny Silverhand port, whose quirks this handles:

* **The FBX references no textures.** The TGAs sit beside it and are matched to
  materials by filename -- `head.tga` -> material `head`, `head_n.tga` -> its
  normal map. Importing without this step yields a fully untextured model.
* **Mesh data names are all junk.** Every mesh's *data* is some variant of
  "i1_002_ma_ring__silverhandout", and the glTF exporter names nodes from the
  data, not the object -- so `scene.py` could not find a mesh called "head".
  Object names are copied onto their data before export.
* **The model is ~73 units tall.** Rescaled to `height` (default 1.8) so that
  lighting distances, near planes and mouth travel are comparable with any
  other avatar rather than being per-model magic numbers.
* **Textures are 2048 uncompressed TGAs, ~357MB of them.** At head-and-
  shoulders framing the shoes and trousers do not earn 2048px, and an 8GB M2
  is the target machine, so anything that is not facial is capped smaller.
  This is the difference between a 344MB .bam and a manageable one.
"""
import os
import sys

import bpy
from mathutils import Vector

# Materials whose detail actually reaches the screen at head-and-shoulders
# framing. Everything else is background and gets the smaller cap.
FACE_MATERIALS = {
    "head", "beard", "eyes", "eyelashes", "eyebrows", "teeth",
    "hair", "hair_scalp", "glass", "glass_outer",
}
FACE_TEXTURE_MAX = 1024
OTHER_TEXTURE_MAX = 512


def _texture_index(texdir):
    """Shipped base-colour textures by stem. `*_n` are normal maps, not bases."""
    return {
        os.path.splitext(f)[0]: f
        for f in os.listdir(texdir)
        if f.lower().endswith(".tga") and not os.path.splitext(f)[0].endswith("_n")
    }


def _mtl_targets(texdir):
    """material name -> the *original* texture basename its .mtl points at.

    The .mtl's paths are absolute paths on the porter's own Windows machine, so
    only the basename is usable -- but that basename is what identifies the
    texture, and the shipped TGAs were renamed by hand from exactly those.
    """
    targets = {}
    for filename in sorted(os.listdir(texdir)):
        if not filename.lower().endswith(".mtl"):
            continue
        current = None
        with open(os.path.join(texdir, filename), encoding="utf-8",
                  errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if line.startswith("newmtl "):
                    current = line.split(None, 1)[1].strip()
                elif current and line.lower().startswith("map_kd"):
                    path = line.split(None, 1)[1].strip().replace("\\", "/")
                    targets[current] = os.path.splitext(os.path.basename(path))[0]
    return targets


def resolve_texture(material, shipped, targets, learned):
    """Stem of the base-colour texture for `material`, or None.

    Six materials have no `<name>.tga` and were previously left untextured,
    which renders as flat white -- visibly, as a white patch on the vest. They
    are recovered in three steps, most trustworthy first:

    1. the .mtl's original basename, mapped through what the materials that
       *do* resolve teach us about the renaming (pants_misc2 and pants point at
       the same original, so pants_misc2 is pants.tga);
    2. a shipped stem appearing inside that original basename
       (`v_common_stitches_n01` -> `stitches.tga`, which is shipped);
    3. the material's own prefix (`shoe_misc` -> `shoe`), for materials the
       .mtl gives no map_Kd for at all.
    """
    if material in shipped:
        return material

    original = targets.get(material)
    if original:
        if original in learned:
            return learned[original]
        lowered = original.lower()
        matches = [stem for stem in shipped
                   if len(stem) > 3 and stem.lower() in lowered]
        if matches:
            return max(matches, key=len)

    prefix = material.split("_")[0]
    return prefix if prefix in shipped else None


def _resize(image, cap):
    width, height = image.size
    largest = max(width, height)
    if largest <= cap:
        return False
    factor = cap / largest
    image.scale(max(1, int(width * factor)), max(1, int(height * factor)))
    return True


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    src, dst, texdir = argv[0], argv[1], argv[2]
    target_height = float(argv[3]) if len(argv) > 3 else 1.8

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=src, automatic_bone_orientation=True)

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    armatures = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    print(f"IMPORTED meshes={len(meshes)} armatures={len(armatures)} "
          f"bones={len(armatures[0].data.bones) if armatures else 0}")

    for obj in meshes:
        obj.data.name = obj.name

    cache = {}

    def load(filename):
        path = os.path.join(texdir, filename)
        if not os.path.exists(path):
            return None
        if path not in cache:
            cache[path] = bpy.data.images.load(path)
        return cache[path]

    shipped = _texture_index(texdir)
    targets = _mtl_targets(texdir)
    learned = {}
    for name, original in targets.items():
        if name in shipped:
            learned.setdefault(original, name)

    wired = 0
    unresolved = []
    for material in bpy.data.materials:
        stem = resolve_texture(material.name, shipped, targets, learned)
        base = load(f"{stem}.tga") if stem else None
        if base is None:
            unresolved.append(material.name)
            print(f"  NO TEXTURE for material {material.name}")
            continue
        if stem != material.name:
            print(f"  {material.name} -> {stem}.tga (resolved)")

        cap = FACE_TEXTURE_MAX if material.name in FACE_MATERIALS else OTHER_TEXTURE_MAX
        if _resize(base, cap):
            print(f"  resized {material.name}.tga -> {base.size[0]}x{base.size[1]}")

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
            _resize(normal, cap)
            normal_tex = tree.nodes.new("ShaderNodeTexImage")
            normal_tex.image = normal
            normal_map = tree.nodes.new("ShaderNodeNormalMap")
            tree.links.new(normal_tex.outputs["Color"], normal_map.inputs["Color"])
            tree.links.new(normal_map.outputs["Normal"], shader.inputs["Normal"])

        # Hair, eyelashes and glass are alpha-cut sheets. Left opaque they
        # render as solid blocks around the face.
        for attribute, value in (("blend_method", "BLEND"),
                                 ("surface_render_method", "BLENDED")):
            try:
                setattr(material, attribute, value)
                break
            except (AttributeError, TypeError):
                continue
        wired += 1

    print(f"WIRED {wired}/{len(bpy.data.materials)} materials")
    if unresolved:
        print(f"UNRESOLVED {len(unresolved)}: {', '.join(sorted(unresolved))}")

    if target_height > 0 and armatures:
        low = Vector((1e9, 1e9, 1e9))
        high = Vector((-1e9, -1e9, -1e9))
        depsgraph = bpy.context.evaluated_depsgraph_get()
        for obj in meshes:
            for corner in obj.evaluated_get(depsgraph).bound_box:
                world = obj.matrix_world @ Vector(corner)
                low = Vector((min(low[i], world[i]) for i in range(3)))
                high = Vector((max(high[i], world[i]) for i in range(3)))
        height = high[2] - low[2]
        if height > 0:
            factor = target_height / height
            root = armatures[0]
            root.scale = tuple(value * factor for value in root.scale)
            print(f"SCALED height {height:.3f} -> {target_height} (factor {factor:.5f})")

    bpy.ops.export_scene.gltf(
        filepath=dst,
        export_format="GLB",
        export_skins=True,
        export_yup=True,
        export_apply=False,
    )
    print("EXPORTED", dst)


if __name__ == "__main__":
    main()
