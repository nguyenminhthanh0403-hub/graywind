# Avatar model attribution

"Jonny Silverhand" by **Stuxed**
https://sketchfab.com/3d-models/jonny-silverhand-806032afcab34b118809e864a5c54ee4

Licensed **CC Attribution (CC BY)**. Credit is a licence condition, so the
on-screen credit in `avatar/scene.py` is required, not decorative. Do not
remove it.

A stylized fan interpretation, not screen-accurate — the creator notes the
metal arm is on the wrong side. The base mesh is a Ready Player Me export,
which is where the `Wolf3D_*` mesh names and the aliased UV sets come from.

All 20 textures are embedded in the GLB's binary chunk as `bufferView`
images — there are no external `uri` references, so `jonny.glb` is
self-contained and can be moved without breaking texture resolution.

`jonny.glb` is the Sketchfab "Original format" download and is the only
file here under version control. `jonny_fixed.glb` and `jonny_fixed.bam`
are build artifacts — regenerate them with:

    .venv/bin/python -m tools.repair_gltf
    .venv/bin/gltf2bam assets/avatar/jonny_fixed.glb assets/avatar/jonny_fixed.bam

`gltf2bam` prints ~189 `Could not find joint in jvtmap` warnings. These are
zero-weight joint indices and are harmless; the exit code is what matters.
