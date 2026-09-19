# MAVIS Johnny Silverhand Avatar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A wake-word-triggered desktop presence that renders an animated 3D Johnny Silverhand, answers a spoken question in a Johnny-styled voice with visible mouth movement, and disappears on a spoken dismissal.

**Architecture:** Three processes. An avatar app on Python 3.14 (`mavis/.venv`) owns the mic, the wake word, the Panda3D window and the state machine. A **persistent warm** voice worker on Python 3.12 (`bullion-live-map/.venv-narration`) holds ChatterboxVC in memory — the two Pythons cannot share a process, and spawning per request would add ~16s to every reply. Groq (Whisper STT + the existing `/ask` endpoint) supplies transcription and answers over HTTP.

**Tech Stack:** Panda3D 1.10.16 + `panda3d-gltf`, `openwakeword` 0.6.0 + `onnxruntime`, `sounddevice`, `numpy`, `httpx`, ChatterboxVC (torch 2.6.0, MPS).

**Spec:** `docs/superpowers/specs/2026-09-19-mavis-avatar-design.md`

## Global Constraints

Every task's requirements implicitly include this section.

- **Runtime venv is Python 3.14** at `mavis/.venv`. torch must **never** be installed into it — `openwakeword.train` pulls torch, and training happens out of band.
- **Voice worker interpreter** is exactly `~/minhthanh0403/claude-projects/claudekit/bullion-live-map/.venv-narration/bin/python` (Python 3.12.13, torch 2.6.0, MPS available).
- **The voice worker is persistent.** Never `subprocess.run()` per request. Model load (14.85s) + reference embedding (1.14s) are paid once at startup. A spawn-per-request implementation is a defect, and Task 5 has a regression test for it.
- **Never run two heavy local neural steps concurrently.** Voice conversion completes and writes a file; only then does the renderer animate against it.
- **Voice conversion is a ~1.4x-realtime rate, not a flat cost.** 6.67s of input took 9.19s. Answer length is capped so latency stays bounded.
- `openwakeword.Model` **must** be constructed with `inference_framework="onnx"` — the default is `"tflite"`, which is not available here.
- **Attribution is a licence term, not a nicety:** the string `Model: "Jonny Silverhand" by Stuxed (CC BY)` must be visible on screen whenever the avatar is shown.
- **No silent failures.** Every degraded path shows something on screen.
- Tests run with `cd mavis && .venv/bin/python -m pytest -q`. The existing suite is 50/50 green; keep it green.
- Follow the existing code style: module-level constants read from env, docstrings that explain *why*, no inline comments restating code.

---

## File Structure

MAVIS's existing modules are flat at `mavis/` (`app.py`, `auth.py`, `grounding.py`…). The avatar adds nine modules, which would crowd that root, so they live in a package. Imports stay flat-compatible (`from avatar import lipsync`) because the app already runs with `mavis/` on `sys.path`.

| Path | Responsibility |
|---|---|
| `mavis/tools/repair_gltf.py` | Strip redundant aliased UV sets so `panda3d-gltf` can convert the model |
| `mavis/assets/avatar/` | `jonny.glb` (source), `jonny_fixed.glb`, `jonny_fixed.bam`, `ATTRIBUTION.md` |
| `mavis/assets/wakeword/` | `wake_up_johnny.onnx` from the Colab training run |
| `mavis/avatar/lipsync.py` | Audio → per-frame `mouthOpen` values (pure, no I/O) |
| `mavis/avatar/dismiss.py` | Does this transcript mean "go away"? (pure) |
| `mavis/avatar/scene.py` | Panda3D window, model, idle motion, slider driving |
| `mavis/avatar/voice_client.py` | Owns the warm worker subprocess, restart + fallback policy |
| `mavis/scripts/voice_worker.py` | **Runs under 3.12.** ChatterboxVC held warm, newline-JSON protocol |
| `mavis/avatar/wake.py` | openWakeWord wrapper over a mic stream |
| `mavis/avatar/capture.py` | Record one utterance, endpoint on silence |
| `mavis/avatar/stt.py` | Groq Whisper transcription |
| `mavis/avatar/brain.py` | `httpx` → `/ask`, answer-length cap |
| `mavis/avatar/app.py` | The state machine wiring it together |

Task order front-loads a visible window (Task 2) so the riskiest assumption fails early if it is going to fail.

---

### Task 1: Vendor the asset and its repair tool

The repaired model currently exists only in `~/Documents/`. Nothing else can be built until it is in the repo and reproducible from source.

**Files:**
- Create: `mavis/tools/repair_gltf.py`
- Create: `mavis/assets/avatar/ATTRIBUTION.md`
- Create: `tests/test_repair_gltf.py`
- Modify: `mavis/requirements.txt`
- Modify: `mavis/.gitignore`

**Interfaces:**
- Consumes: nothing
- Produces: `repair_gltf.strip_aliased_uvs(src: Path, dst: Path) -> int` (returns count of removed attributes); the asset at `mavis/assets/avatar/jonny_fixed.bam`

- [x] **Step 1: Create the branch**

```bash
cd ~/Projects/graywind
git checkout -b feat/mavis-avatar
```

- [x] **Step 2: Copy the source asset into the repo**

All 20 textures are **embedded** in the GLB's binary chunk as `bufferView` images — verified, none use external `uri` references. So `jonny.glb` is fully self-contained: do **not** copy the `textures/` folder from `~/Documents/` (those 24 files are an artifact of the zip and nothing reads them), and the asset's location in the repo cannot break texture resolution.

The `.bam` is a 22MB build artifact — regenerated, not committed.

```bash
cd ~/Projects/graywind/mavis
mkdir -p assets/avatar tools
cp ~/Documents/jonny-silverhand-extracted/source/jonny.glb assets/avatar/jonny.glb
```

- [x] **Step 3: Write the failing test**

Create `tests/test_repair_gltf.py`:

```python
import json
import struct
from pathlib import Path

import pytest

from tools import repair_gltf

ASSET = Path(__file__).resolve().parent.parent / "assets" / "avatar" / "jonny.glb"


def _read_gltf_json(path):
    size = path.stat().st_size
    with open(path, "rb") as fh:
        fh.seek(12)
        while fh.tell() < size:
            chunk_len, chunk_type = struct.unpack("<II", fh.read(8))
            data = fh.read(chunk_len)
            if chunk_type == 0x4E4F534A:
                return json.loads(data)
    raise AssertionError("no JSON chunk")


def test_source_asset_has_the_aliased_uv_defect(tmp_path):
    """Guards the premise: if a future re-download lacks the defect, the
    repair is a no-op and this test says so loudly rather than silently
    passing."""
    gltf = _read_gltf_json(ASSET)
    aliased = [
        prim
        for mesh in gltf["meshes"]
        for prim in mesh["primitives"]
        if any(k.startswith("TEXCOORD_") and int(k.split("_")[1]) >= 1
               for k in prim["attributes"])
    ]
    assert aliased, "expected at least one primitive with TEXCOORD_1+"


def test_strip_aliased_uvs_removes_extra_texcoords(tmp_path):
    dst = tmp_path / "fixed.glb"
    removed = repair_gltf.strip_aliased_uvs(ASSET, dst)

    assert removed == 7
    gltf = _read_gltf_json(dst)
    for mesh in gltf["meshes"]:
        for prim in mesh["primitives"]:
            extra = [k for k in prim["attributes"]
                     if k.startswith("TEXCOORD_") and int(k.split("_")[1]) >= 1]
            assert extra == []


def test_strip_aliased_uvs_preserves_morph_targets(tmp_path):
    """The whole point of repairing rather than using the GLB-converted
    download: the morphs must survive."""
    dst = tmp_path / "fixed.glb"
    repair_gltf.strip_aliased_uvs(ASSET, dst)

    gltf = _read_gltf_json(dst)
    named = [m.get("extras", {}).get("targetNames") for m in gltf["meshes"]]
    assert ["mouthOpen", "mouthSmile"] in named


def test_strip_aliased_uvs_preserves_binary_chunk_byte_for_byte(tmp_path):
    dst = tmp_path / "fixed.glb"
    repair_gltf.strip_aliased_uvs(ASSET, dst)
    assert _binary_chunk(dst) == _binary_chunk(ASSET)


def _binary_chunk(path):
    size = path.stat().st_size
    with open(path, "rb") as fh:
        fh.seek(12)
        while fh.tell() < size:
            chunk_len, chunk_type = struct.unpack("<II", fh.read(8))
            data = fh.read(chunk_len)
            if chunk_type == 0x004E4942:
                return data.rstrip(b"\x00")
    raise AssertionError("no BIN chunk")
```

- [x] **Step 4: Run it and watch it fail**

Run: `cd ~/Projects/graywind/mavis && .venv/bin/python -m pytest tests/test_repair_gltf.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools'`

- [x] **Step 5: Write the implementation**

Create `mavis/tools/__init__.py` (empty) and `mavis/tools/repair_gltf.py`:

```python
"""Make the Sketchfab Johnny model convertible by panda3d-gltf.

The model is a Ready Player Me export whose `Wolf3D_Outfit_Bottom`
primitive declares TEXCOORD_1..TEXCOORD_7 all pointing at a single
accessor. panda3d-gltf miscounts vertex rows from those aliased UV sets
and then fails on the *following* mesh with "GeomTriangles references
vertices up to 1003, but GeomVertexData has only 557 rows".

Nothing in the file is actually malformed -- every accessor count is a
consistent 1004 -- so the repair only deletes the redundant attribute
*references*. The binary chunk is copied through untouched, which is why
the morph targets (mouthOpen/mouthSmile) survive; the GLB-converted
download from Sketchfab loses them.
"""
import json
import struct
from pathlib import Path

GLB_MAGIC = 0x46546C67
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942


def _pad(data: bytes, filler: bytes) -> bytes:
    return data + filler * ((4 - len(data) % 4) % 4)


def strip_aliased_uvs(src: Path, dst: Path) -> int:
    """Rewrite `src` to `dst` without TEXCOORD_1+ attributes.

    Returns the number of attribute references removed.
    """
    src, dst = Path(src), Path(dst)
    size = src.stat().st_size
    gltf, binary = None, b""

    with open(src, "rb") as fh:
        magic, _version, _total = struct.unpack("<III", fh.read(12))
        if magic != GLB_MAGIC:
            raise ValueError(f"{src} is not a .glb file")
        while fh.tell() < size:
            chunk_len, chunk_type = struct.unpack("<II", fh.read(8))
            data = fh.read(chunk_len)
            if chunk_type == CHUNK_JSON:
                gltf = json.loads(data)
            elif chunk_type == CHUNK_BIN:
                binary = data

    removed = 0
    for mesh in gltf.get("meshes", []):
        for prim in mesh["primitives"]:
            extra = [
                k for k in prim["attributes"]
                if k.startswith("TEXCOORD_") and int(k.split("_")[1]) >= 1
            ]
            for key in extra:
                del prim["attributes"][key]
                removed += 1

    json_chunk = _pad(json.dumps(gltf, separators=(",", ":")).encode(), b" ")
    bin_chunk = _pad(binary, b"\x00")
    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)

    with open(dst, "wb") as fh:
        fh.write(struct.pack("<III", GLB_MAGIC, 2, total))
        fh.write(struct.pack("<II", len(json_chunk), CHUNK_JSON))
        fh.write(json_chunk)
        fh.write(struct.pack("<II", len(bin_chunk), CHUNK_BIN))
        fh.write(bin_chunk)

    return removed


def main() -> None:
    root = Path(__file__).resolve().parent.parent / "assets" / "avatar"
    removed = strip_aliased_uvs(root / "jonny.glb", root / "jonny_fixed.glb")
    print(f"removed {removed} aliased texcoord attributes")


if __name__ == "__main__":
    main()
```

- [x] **Step 6: Run the tests and watch them pass — and confirm the import path**

Run: `cd ~/Projects/graywind/mavis && .venv/bin/python -m pytest tests/test_repair_gltf.py -q`
Expected: 4 passed

This is also the first use of a **subpackage** import (`from tools import repair_gltf`). Existing tests import flat modules (`import mcp_tools`), which resolve because pytest puts `mavis/` on `sys.path`; a package with `__init__.py` resolves the same way. Six later tasks depend on `from avatar import ...` working identically, so confirm it here rather than discovering it in Task 7. If collection fails with `ModuleNotFoundError`, the fix is one line in the existing (empty) `mavis/conftest.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
```

- [x] **Step 7: Build the .bam**

```bash
cd ~/Projects/graywind/mavis
.venv/bin/python -m tools.repair_gltf
.venv/bin/gltf2bam assets/avatar/jonny_fixed.glb assets/avatar/jonny_fixed.bam
```

Expected: `removed 7 aliased texcoord attributes`, then gltf2bam exits 0. It prints many `Could not find joint in jvtmap` warnings — these are zero-weight joint indices and are harmless; the exit code is what matters.

- [x] **Step 8: Write the attribution file**

Create `mavis/assets/avatar/ATTRIBUTION.md`:

```markdown
# Avatar model attribution

"Jonny Silverhand" by **Stuxed**
https://sketchfab.com/3d-models/jonny-silverhand-806032afcab34b118809e864a5c54ee4

Licensed **CC Attribution (CC BY)**. Credit is a licence condition, so the
on-screen credit in `avatar/scene.py` is required, not decorative. Do not
remove it.

A stylized fan interpretation, not screen-accurate — the creator notes the
metal arm is on the wrong side. Base mesh is a Ready Player Me export,
which is where the `Wolf3D_*` mesh names and the aliased UV sets come from.

`jonny.glb` is the Sketchfab "Original format" download. `jonny_fixed.glb`
and `jonny_fixed.bam` are build artifacts — regenerate with:

    .venv/bin/python -m tools.repair_gltf
    .venv/bin/gltf2bam assets/avatar/jonny_fixed.glb assets/avatar/jonny_fixed.bam
```

- [x] **Step 9: Update requirements and gitignore**

Append to `mavis/requirements.txt`:

```
panda3d==1.10.16
panda3d-gltf==1.3.0
panda3d-simplepbr==0.13.1
openwakeword==0.6.0
sounddevice==0.5.3
numpy==2.5.3
```

Append to `mavis/.gitignore`:

```
assets/avatar/jonny_fixed.glb
assets/avatar/jonny_fixed.bam
```

- [x] **Step 10: Confirm the full suite is still green**

Run: `cd ~/Projects/graywind/mavis && .venv/bin/python -m pytest -q`
Expected: 54 passed (50 existing + 4 new)

- [x] **Step 11: Commit**

```bash
cd ~/Projects/graywind
git add mavis/tools mavis/assets mavis/requirements.txt mavis/.gitignore mavis/tests/test_repair_gltf.py
git commit -m "feat(mavis): vendor Johnny avatar asset and its glTF repair tool"
```

---

### Task 2: Render the avatar in a real window

**This task tests the design's largest unverified assumption.** Everything so far ran headless. Panda3D 1.10.16 on Apple Silicon uses a deprecated OpenGL path; if a window will not open, that is discovered here and the renderer choice reopens — nothing downstream is wasted.

**Files:**
- Create: `mavis/avatar/__init__.py`, `mavis/avatar/scene.py`
- Create: `tests/test_scene.py`

**Interfaces:**
- Consumes: `assets/avatar/jonny_fixed.bam` from Task 1
- Produces:
  - `scene.MOUTH_GAIN: float`
  - `scene.AvatarScene(show_base)` with `.set_mouth(amount: float) -> None`, `.show() -> None`, `.hide() -> None`, `.mouth_sliders: list`
  - `scene.load_actor(loader) -> Actor`

- [x] **Step 1: Write the failing test**

These tests run headless (`window-type none`) so they work in CI; the visible window is checked by hand in Step 6.

Create `tests/test_scene.py`:

```python
import pytest
from panda3d.core import loadPrcFileData

loadPrcFileData("", "window-type none\naudio-library-name null\n"
                    "hardware-animated-vertices false")

from direct.showbase.ShowBase import ShowBase  # noqa: E402
from panda3d.core import GeomVertexReader, Thread  # noqa: E402

from avatar import scene  # noqa: E402


@pytest.fixture(scope="module")
def base():
    b = ShowBase()
    yield b
    b.destroy()


@pytest.fixture(scope="module")
def avatar(base):
    return scene.AvatarScene(base)


def test_actor_loads_with_full_skeleton(avatar):
    assert len(avatar.actor.getJoints()) >= 68


def test_mouth_sliders_are_found(avatar):
    """Sliders live in the PartBundle, not the scene graph -- a
    findAllMatches("**/+CharacterSlider") search returns zero and is the
    reason an earlier session wrongly concluded this model had no morphs."""
    assert len(avatar.mouth_sliders) == 5


def test_set_mouth_moves_head_geometry(avatar):
    def sample():
        node = [g for g in avatar.actor.findAllMatches("**/+GeomNode")
                if g.getName() == "Wolf3D_Head"][0].node()
        vd = node.getGeom(0).getVertexData().animateVertices(
            True, Thread.getCurrentThread())
        reader = GeomVertexReader(vd, "vertex")
        out = []
        while not reader.isAtEnd():
            out.append(tuple(reader.getData3()))
        return out

    avatar.set_mouth(0.0)
    closed = sample()
    avatar.set_mouth(1.0)
    opened = sample()

    moved = sum(1 for a, b in zip(closed, opened) if a != b)
    assert moved > 500


def test_set_mouth_clamps_negative_input(avatar):
    avatar.set_mouth(-5.0)
    assert avatar.mouth_sliders[0].getValue() == 0.0


def test_attribution_text_is_present(avatar):
    assert "Stuxed" in avatar.credit.getText()
```

- [x] **Step 2: Run it and watch it fail**

Run: `cd ~/Projects/graywind/mavis && .venv/bin/python -m pytest tests/test_scene.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'avatar'`

- [x] **Step 3: Write the implementation**

Create `mavis/avatar/__init__.py` (empty) and `mavis/avatar/scene.py`:

```python
"""The Panda3D side of the avatar: window, model, idle motion, mouth.

Mouth movement is driven by CharacterSlider morph targets rather than a
jaw bone -- this model has no jaw joint. The sliders are reached by
walking the character's PartBundle; they are NOT scene-graph nodes, so
NodePath searches for them return nothing.

MOUTH_GAIN exists because a slider value of 1.0 displaces head vertices
by only ~0.011 units on a ~1.7-unit model (~11mm of jaw travel), which
reads as a twitch rather than speech. Morph targets extrapolate linearly,
so values above 1.0 are legitimate.
"""
import math
from pathlib import Path

from direct.actor.Actor import Actor
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import AmbientLight, DirectionalLight, TextNode, Vec4

ASSET = Path(__file__).resolve().parent.parent / "assets" / "avatar" / "jonny_fixed.bam"

MOUTH_GAIN = 2.0
CREDIT = 'Model: "Jonny Silverhand" by Stuxed (CC BY)'


def load_actor(loader) -> Actor:
    if not ASSET.exists():
        raise FileNotFoundError(
            f"avatar model missing at {ASSET} -- build it with "
            "`.venv/bin/python -m tools.repair_gltf` then `gltf2bam`"
        )
    return Actor(str(ASSET))


def _collect_sliders(part, name, acc):
    if type(part).__name__ == "CharacterSlider" and part.getName() == name:
        acc.append(part)
    for i in range(part.getNumChildren()):
        _collect_sliders(part.getChild(i), name, acc)
    return acc


class AvatarScene:
    """Owns the avatar's visual state. Knows nothing about audio."""

    def __init__(self, show_base):
        self.base = show_base
        self.actor = load_actor(show_base.loader)
        self.actor.reparent_to(show_base.render)
        self.actor.set_pos(0, 3.2, -1.45)

        character = self.actor.find("**/+Character").node()
        self._character = character
        self._bundle = character.getBundle(0)
        self.mouth_sliders = _collect_sliders(self._bundle, "mouthOpen", [])

        self._light()
        self.credit = OnscreenText(
            text=CREDIT, pos=(0.0, -0.95), scale=0.04,
            fg=(0.8, 0.8, 0.85, 1.0), align=TextNode.ACenter, mayChange=False,
        )
        self._t = 0.0
        self.visible = True

    def _light(self):
        key = DirectionalLight("key")
        key.set_color(Vec4(1.0, 0.95, 0.9, 1))
        key_np = self.base.render.attach_new_node(key)
        key_np.set_hpr(20, -20, 0)
        self.base.render.set_light(key_np)

        ambient = AmbientLight("ambient")
        ambient.set_color(Vec4(0.35, 0.35, 0.45, 1))
        self.base.render.set_light(self.base.render.attach_new_node(ambient))

    def set_mouth(self, amount: float) -> None:
        """Drive every mouthOpen slider. `amount` is 0..1 before gain."""
        value = max(0.0, min(1.0, amount)) * MOUTH_GAIN
        for slider in self.mouth_sliders:
            slider.applyFreezeScalar(value)
        self._bundle.forceUpdate()

    def idle(self, elapsed: float) -> None:
        """A slow sway so he doesn't look frozen between questions."""
        self._t = elapsed
        self.actor.set_h(math.sin(elapsed * 0.4) * 12)

    def show(self) -> None:
        self.actor.show()
        self.credit.show()
        self.visible = True

    def hide(self) -> None:
        self.actor.hide()
        self.credit.hide()
        self.visible = False
```

- [x] **Step 4: Run the tests and watch them pass**

Run: `cd ~/Projects/graywind/mavis && .venv/bin/python -m pytest tests/test_scene.py -q`
Expected: 5 passed

- [x] **Step 5: Run the whole suite**

Run: `cd ~/Projects/graywind/mavis && .venv/bin/python -m pytest -q`
Expected: 64 passed (the "59" written here originally forgot to add Task 2's own 5).

> **As built (2026-09-19, commit `7aeefd4`) — two deviations from the code above:**
> 1. `OnscreenText` takes **`mayChange=True`**, not `False`. The default flattens
>    the text into a bare `PandaNode` and `getText()` then raises
>    `AttributeError: 'PandaNode' object has no attribute 'getWtext'` — the credit
>    becomes unreadable off the node, which is unacceptable for a licence string.
> 2. **`MOUTH_GAIN = 1.5`**, not 2.0 — chosen by eye at the Step 6 gate; 2.0 and 3.0
>    overshot. Confirmed `slider.getValue()` does reflect the frozen scalar
>    (`set_mouth(0.25)` → `0.5` at gain 2.0), so the clamp test is not vacuous.
>
> **Superseded 2026-09-19 (`dee78e6`):** the model was replaced with KonnieGFX's
> port of CD Projekt Red's actual Johnny, which has **no morph targets** -- its
> mouth is a rotation of `mid_J_jaw_JNT`. `MOUTH_GAIN` no longer exists as a
> module constant; per-model mouth config lives in `scene.AVATARS`. The public
> interface Tasks 4-7 depend on is unchanged: `set_mouth(0..1)`. The CC-BY
> Stuxed model is retained as the only asset the tests can use, since the
> replacement is an extracted CDPR asset and cannot be committed.

- [x] **Step 6: Verify a real window opens — THE GATE FOR THIS TASK**

Headless tests cannot answer this. Run by hand and *look at the screen*.

This must exercise **`avatar/scene.py` itself**, not the throwaway `render_test.py` — `AvatarScene.__init__` builds `OnscreenText`, attaches lights and places the camera, and none of that has ever run with a real window:

```bash
cd ~/Projects/graywind/mavis
.venv/bin/python -c "
from panda3d.core import loadPrcFileData
loadPrcFileData('', 'window-title Johnny\nhardware-animated-vertices false')
from direct.showbase.ShowBase import ShowBase
from avatar import scene as m
import math
base = ShowBase()
s = m.AvatarScene(base)
base.taskMgr.add(lambda t: (s.idle(t.time),
    s.set_mouth(math.sin(t.time * 5) * 0.5 + 0.5), t.cont)[-1], 'sweep')
base.run()"
```

To choose `MOUTH_GAIN`, edit its value in `scene.py` between runs, or use the throwaway sweep which steps 1.0 → 1.5 → 2.0 → 3.0 automatically:

```bash
cd ~/Documents/jonny-silverhand-extracted
~/Projects/graywind/mavis/.venv/bin/python render_test.py
```

Confirm, in order:
0. The on-screen Stuxed credit is visible (it is a licence condition, and this is the only place it can be checked).
1. A window opens and shows a lit, textured figure — not a black rectangle, not a crash. Textures are embedded in the model, so an untextured grey figure means the material/lighting setup is wrong, not that a file is missing.
2. The figure sways.
3. The mouth visibly opens and closes.
4. As the printed gain steps 1.0 → 1.5 → 2.0 → 3.0, note which value first reads as *talking* rather than twitching.

**If the window does not open:** stop. Do not continue to Task 3. The renderer choice reopens and the spec needs revisiting — that is a design decision, not a bug to work around.

**If it opens:** set `MOUTH_GAIN` in `scene.py` to the value chosen in (4).

> **GATE RESULT, 2026-09-19 — passed, after the gate caught a real defect.**
>
> The first run showed a formless grey mass. That was NOT lighting or textures:
> Task 1's repair had silently corrupted `Wolf3D_Outfit_Bottom`, exploding it to
> ±18 units so the camera sat inside the geometry. Fixed in `1c5ebce` — see that
> commit and Task 1's own note. The gate did its job; do not weaken it.
>
> Confirmed after the fix:
> - **A real window opens.** Panda3D 1.10.16 loads `CocoaGraphicsPipe` and runs
>   on Apple Silicon. *The design's largest unverified assumption is cleared.*
> - **Textured and correctly framed**, verified by offscreen render (head and
>   shoulders, jacket, beard, aviators, in colour).
> - **The on-screen Stuxed credit renders.** A human confirmed it at the window
>   on the pre-fix build; the post-fix offscreen PNG also shows it drawing,
>   which is the evidence that matches the current code, since simplepbr
>   installs its own display-region filtering after that human check.
> - **The mouth moves.** `MOUTH_GAIN = 1.0`, chosen by eye against 1.5/2.0/3.0
>   at the corrected framing. The earlier 1.5 was picked while the camera was
>   inside the broken mesh, so it was never a valid reading.
>
> Two pieces of machinery worth reusing for later tasks:
> - `window-type offscreen` + `base.win.getScreenshot(PNMImage())` renders
>   headlessly and can be inspected directly — far tighter than asking a human
>   "does this look right". Step the task manager, don't call `renderFrame()`:
>   simplepbr feeds `camera_world_position` from a task.
> - The throwaway gain sweep lives in the session scratchpad, not the repo.

- [x] **Step 7: Commit**

```bash
cd ~/Projects/graywind
git add mavis/avatar mavis/tests/test_scene.py
git commit -m "feat(mavis): render the avatar with morph-driven mouth"
```

---

### Task 3: Turn audio into mouth movement

Pure functions, no I/O, no Panda3D — the easiest part to get exactly right, and the part most worth testing precisely.

**Files:**
- Create: `mavis/avatar/lipsync.py`
- Create: `tests/test_lipsync.py`

**Interfaces:**
- Consumes: nothing
- Produces: `lipsync.envelope(samples: np.ndarray, sample_rate: int, fps: int = 60) -> np.ndarray` (values 0..1, one per frame); `lipsync.amount_at(env: np.ndarray, elapsed: float, fps: int = 60) -> float`

- [x] **Step 1: Write the failing test**

Create `tests/test_lipsync.py`:

```python
import numpy as np
import pytest

from avatar import lipsync


def _tone(seconds, sample_rate=22050, amplitude=1.0):
    t = np.linspace(0, seconds, int(seconds * sample_rate), endpoint=False)
    return (amplitude * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def test_envelope_has_one_value_per_frame():
    env = lipsync.envelope(_tone(1.0), 22050, fps=60)
    assert len(env) == 60


def test_envelope_is_normalised_to_unit_range():
    env = lipsync.envelope(_tone(1.0), 22050)
    assert env.max() == pytest.approx(1.0, abs=1e-6)
    assert env.min() >= 0.0


def test_silence_produces_a_closed_mouth():
    env = lipsync.envelope(np.zeros(22050, dtype=np.float32), 22050)
    assert env.max() == 0.0


def test_loud_section_scores_above_quiet_section():
    quiet = _tone(0.5, amplitude=0.1)
    loud = _tone(0.5, amplitude=1.0)
    env = lipsync.envelope(np.concatenate([quiet, loud]), 22050, fps=10)
    assert env[:5].mean() < env[5:].mean()


def test_envelope_handles_audio_shorter_than_one_frame():
    env = lipsync.envelope(_tone(0.001), 22050, fps=60)
    assert len(env) >= 1


def test_amount_at_reads_the_matching_frame():
    env = np.array([0.0, 0.5, 1.0])
    assert lipsync.amount_at(env, 0.0, fps=10) == 0.0
    assert lipsync.amount_at(env, 0.1, fps=10) == 0.5
    assert lipsync.amount_at(env, 0.2, fps=10) == 1.0


def test_amount_at_closes_the_mouth_past_the_end():
    """When playback outruns the envelope the mouth must close, not hold
    open on the last value."""
    env = np.array([1.0, 1.0])
    assert lipsync.amount_at(env, 99.0, fps=10) == 0.0


def test_amount_at_on_empty_envelope_is_closed():
    assert lipsync.amount_at(np.array([]), 0.0) == 0.0
```

- [x] **Step 2: Run it and watch it fail**

Run: `cd ~/Projects/graywind/mavis && .venv/bin/python -m pytest tests/test_lipsync.py -q`
Expected: FAIL — `ImportError: cannot import name 'lipsync'`

- [x] **Step 3: Write the implementation**

Create `mavis/avatar/lipsync.py`:

```python
"""Amplitude-driven mouth movement.

This model carries only two blendshapes (mouthOpen, mouthSmile) and no
visemes, so true phoneme-accurate lip-sync is not available at any price.
An RMS envelope of the finished audio is what the rig can actually
express.

Working from *finished* audio is also what keeps the 8GB M2 viable: the
envelope is computed once after voice conversion completes, so nothing
neural is running while the renderer animates.
"""
import numpy as np


def envelope(samples: np.ndarray, sample_rate: int, fps: int = 60) -> np.ndarray:
    """RMS energy per animation frame, normalised to 0..1.

    Returns at least one frame even for very short input.
    """
    samples = np.asarray(samples, dtype=np.float32)
    if samples.size == 0:
        return np.zeros(1, dtype=np.float32)

    per_frame = max(1, sample_rate // fps)
    frame_count = max(1, int(np.ceil(samples.size / per_frame)))

    padded = np.zeros(frame_count * per_frame, dtype=np.float32)
    padded[: samples.size] = samples
    blocks = padded.reshape(frame_count, per_frame)

    rms = np.sqrt(np.mean(np.square(blocks), axis=1))
    peak = rms.max()
    if peak <= 0.0:
        return np.zeros(frame_count, dtype=np.float32)
    return (rms / peak).astype(np.float32)


def amount_at(env: np.ndarray, elapsed: float, fps: int = 60) -> float:
    """Envelope value for a playback position, 0.0 outside the clip."""
    if len(env) == 0 or elapsed < 0:
        return 0.0
    index = int(elapsed * fps)
    if index >= len(env):
        return 0.0
    return float(env[index])
```

- [x] **Step 4: Run the tests and watch them pass**

Run: `cd ~/Projects/graywind/mavis && .venv/bin/python -m pytest tests/test_lipsync.py -q`
Expected: 8 passed

- [x] **Step 5: Commit**

```bash
cd ~/Projects/graywind
git add mavis/avatar/lipsync.py mavis/tests/test_lipsync.py
git commit -m "feat(mavis): derive mouth movement from an audio envelope"
```

---

### Task 4: Recognise a spoken dismissal

**Files:**
- Create: `mavis/avatar/dismiss.py`
- Create: `tests/test_dismiss.py`

**Interfaces:**
- Consumes: nothing
- Produces: `dismiss.is_dismissal(transcript: str, threshold: float = 0.82) -> bool`; `dismiss.PHRASES: tuple[str, ...]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_dismiss.py`:

```python
import pytest

from avatar import dismiss


@pytest.mark.parametrize("said", [
    "that's all",
    "That's all!",
    "  that's all, Johnny  ",
    "go away",
    "shut up Johnny",
])
def test_recognises_dismissal_phrases(said):
    assert dismiss.is_dismissal(said) is True


@pytest.mark.parametrize("said", [
    "what's the market doing today",
    "tell me about the tier pools",
    "",
    "that's a lot of money",
])
def test_ordinary_questions_are_not_dismissals(said):
    assert dismiss.is_dismissal(said) is False


def test_tolerates_small_transcription_errors():
    """Whisper mishears short phrases; an exact match would make dismissal
    unreliable, and the user chose spoken-only dismissal with no timeout
    fallback."""
    assert dismiss.is_dismissal("thats all johnny") is True


def test_does_not_fire_on_a_phrase_buried_in_a_long_sentence():
    said = "before you go away I wanted to ask about the backtest results"
    assert dismiss.is_dismissal(said) is False
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd ~/Projects/graywind/mavis && .venv/bin/python -m pytest tests/test_dismiss.py -q`
Expected: FAIL — `ImportError: cannot import name 'dismiss'`

- [ ] **Step 3: Write the implementation**

Create `mavis/avatar/dismiss.py`:

```python
"""Does this transcript mean 'go away'?

Dismissal is spoken-phrase-only by design -- there is no idle timeout --
so this has to tolerate the small errors Whisper makes on short
utterances. It matches fuzzily, but only against the whole transcript:
"before you go away I wanted to ask..." is a question, not a dismissal.
"""
import re
from difflib import SequenceMatcher

PHRASES = (
    "that's all",
    "that's all johnny",
    "go away",
    "shut up johnny",
    "goodbye johnny",
)

MAX_WORDS = 5


def _normalise(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z\s']", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_dismissal(transcript: str, threshold: float = 0.82) -> bool:
    said = _normalise(transcript)
    if not said:
        return False
    if len(said.split()) > MAX_WORDS:
        return False
    return any(
        SequenceMatcher(None, said, _normalise(p)).ratio() >= threshold
        for p in PHRASES
    )
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd ~/Projects/graywind/mavis && .venv/bin/python -m pytest tests/test_dismiss.py -q`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/graywind
git add mavis/avatar/dismiss.py mavis/tests/test_dismiss.py
git commit -m "feat(mavis): recognise spoken dismissal phrases"
```

---

### Task 5: The warm voice worker

The most failure-prone component, and the one where a plausible-looking implementation silently destroys the approved latency budget.

**Files:**
- Create: `mavis/scripts/voice_worker.py`
- Create: `mavis/avatar/voice_client.py`
- Create: `tests/test_voice_client.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `voice_client.VoiceClient(python_exe: str = ..., ref_wav: str = ...)` with `.start() -> None`, `.convert(in_path: str, out_path: str) -> bool`, `.stop() -> None`, `.degraded: bool`
  - `voice_client.say_to_wav(text: str, path: str) -> None`
  - Worker protocol: newline-delimited JSON both ways

- [ ] **Step 1: Write the worker**

Create `mavis/scripts/voice_worker.py`. It is not imported by the test suite (it cannot be — different interpreter), so it is written before its client.

```python
"""Long-lived ChatterboxVC process. RUNS UNDER PYTHON 3.12, NOT 3.14.

ChatterboxVC needs torch, which lives in bullion-live-map's
.venv-narration (py3.12); Panda3D needs py3.14. The two cannot share a
process, so voice conversion happens here, behind a pipe.

This process stays alive for the whole MAVIS session on purpose. Model
load is ~14.85s and embedding the reference clip is ~1.14s; paying that
once at startup is the difference between a ~12-15s reply and a ~30s one.
Anything that restarts this per request has broken the design.

Protocol: one JSON object per line, both directions.
  in :  {"id": 1, "op": "convert", "input": "/tmp/a.wav", "output": "/tmp/b.wav"}
  in :  {"id": 2, "op": "ping"}
  out:  {"ready": true}                       (once, after model load)
  out:  {"id": 1, "ok": true, "seconds": 9.2}
  out:  {"id": 1, "ok": false, "error": "..."}
"""
import json
import sys
import time

import torch
from chatterbox.vc import ChatterboxVC

REF_WAV = sys.argv[1]


def _emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main():
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = ChatterboxVC.from_pretrained(device=device)
    model.set_target_voice(REF_WAV)
    _emit({"ready": True, "device": device})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue

        op = req.get("op")
        if op == "ping":
            _emit({"id": req.get("id"), "ok": True})
            continue
        if op == "shutdown":
            return
        if op != "convert":
            _emit({"id": req.get("id"), "ok": False,
                   "error": f"unknown op {op!r}"})
            continue

        started = time.monotonic()
        try:
            wav = model.generate(req["input"])
            import torchaudio
            torchaudio.save(req["output"], wav, model.sr)
            _emit({"id": req.get("id"), "ok": True,
                   "seconds": round(time.monotonic() - started, 2)})
        except Exception as exc:  # noqa: BLE001 - must not kill the worker
            _emit({"id": req.get("id"), "ok": False,
                   "error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write the failing test**

The client is tested against a *fake* worker script — a few lines of stdlib Python that speak the same protocol. That keeps the tests fast and torch-free while still exercising real subprocess plumbing.

Create `tests/test_voice_client.py`:

```python
import json
import textwrap

import pytest

from avatar import voice_client

FAKE_WORKER = textwrap.dedent("""
    import json, sys
    sys.stdout.write(json.dumps({"ready": True}) + "\\n")
    sys.stdout.flush()
    for line in sys.stdin:
        req = json.loads(line)
        if req.get("op") == "shutdown":
            break
        sys.stdout.write(json.dumps({"id": req.get("id"), "ok": True,
                                     "seconds": 0.1}) + "\\n")
        sys.stdout.flush()
""")

CRASHING_WORKER = 'import sys; sys.exit(1)'

SLOW_FAILING_WORKER = textwrap.dedent("""
    import json, sys
    sys.stdout.write(json.dumps({"ready": True}) + "\\n")
    sys.stdout.flush()
    for line in sys.stdin:
        req = json.loads(line)
        sys.stdout.write(json.dumps({"id": req.get("id"), "ok": False,
                                     "error": "boom"}) + "\\n")
        sys.stdout.flush()
""")


def _client(tmp_path, source, **kwargs):
    script = tmp_path / "worker.py"
    script.write_text(source)
    return voice_client.VoiceClient(
        python_exe="python3", worker_script=str(script),
        ref_wav=str(tmp_path / "ref.wav"), **kwargs)


def test_start_waits_for_ready(tmp_path):
    client = _client(tmp_path, FAKE_WORKER)
    try:
        client.start()
        assert client.ready is True
        assert client.degraded is False
    finally:
        client.stop()


def test_convert_returns_true_on_success(tmp_path):
    client = _client(tmp_path, FAKE_WORKER)
    try:
        client.start()
        assert client.convert("in.wav", "out.wav") is True
    finally:
        client.stop()


def test_process_is_reused_across_conversions(tmp_path):
    """The regression test for the whole design: a spawn-per-request
    implementation would show a different pid on the second call and cost
    ~16s of model load every reply."""
    client = _client(tmp_path, FAKE_WORKER)
    try:
        client.start()
        client.convert("a.wav", "b.wav")
        first_pid = client.pid
        client.convert("c.wav", "d.wav")
        assert client.pid == first_pid
    finally:
        client.stop()


def test_worker_that_fails_to_start_marks_degraded(tmp_path):
    client = _client(tmp_path, CRASHING_WORKER, ready_timeout=3.0)
    try:
        client.start()
        assert client.degraded is True
        assert client.ready is False
    finally:
        client.stop()


def test_convert_while_degraded_returns_false_instead_of_raising(tmp_path):
    client = _client(tmp_path, CRASHING_WORKER, ready_timeout=3.0)
    try:
        client.start()
        assert client.convert("in.wav", "out.wav") is False
    finally:
        client.stop()


def test_conversion_error_returns_false_and_keeps_worker_alive(tmp_path):
    client = _client(tmp_path, SLOW_FAILING_WORKER)
    try:
        client.start()
        assert client.convert("in.wav", "out.wav") is False
        assert client.pid is not None
    finally:
        client.stop()


def test_stop_is_safe_to_call_twice(tmp_path):
    client = _client(tmp_path, FAKE_WORKER)
    client.start()
    client.stop()
    client.stop()
```

- [ ] **Step 3: Run it and watch it fail**

Run: `cd ~/Projects/graywind/mavis && .venv/bin/python -m pytest tests/test_voice_client.py -q`
Expected: FAIL — `ImportError: cannot import name 'voice_client'`

- [ ] **Step 4: Write the implementation**

Create `mavis/avatar/voice_client.py`:

```python
"""Owns the warm ChatterboxVC worker subprocess.

Every failure here degrades to plain `say` rather than silence, and sets
`degraded` so the UI can show it. A voice assistant that goes quiet with
no explanation is the failure mode this project explicitly rejects.
"""
import json
import os
import subprocess
import threading
import time
from pathlib import Path

NARRATION_PYTHON = os.environ.get(
    "MAVIS_VOICE_PYTHON",
    str(Path.home() / "minhthanh0403/claude-projects/claudekit/bullion-live-map"
        "/.venv-narration/bin/python"),
)
ACTOR_REF_WAV = os.environ.get(
    "MAVIS_ACTOR_REF",
    str(Path.home() / "minhthanh0403/claude-projects/claudekit/bullion-live-map"
        "/audio/voice_sample/actor_sample.wav"),
)
WORKER_SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "voice_worker.py")

READY_TIMEOUT = 90.0
CONVERT_TIMEOUT = 120.0


def say_to_wav(text: str, path: str) -> None:
    """macOS `say` scaffold that ChatterboxVC re-colours into Johnny."""
    subprocess.run(
        ["say", "-v", "Tom", "-o", path, "--data-format=LEF32@22050", text],
        check=True,
    )


class VoiceClient:
    def __init__(self, python_exe=NARRATION_PYTHON, worker_script=WORKER_SCRIPT,
                 ref_wav=ACTOR_REF_WAV, ready_timeout=READY_TIMEOUT):
        self.python_exe = python_exe
        self.worker_script = worker_script
        self.ref_wav = ref_wav
        self.ready_timeout = ready_timeout
        self.proc = None
        self.ready = False
        self.degraded = False
        self.last_error = None
        self._next_id = 0
        self._lock = threading.Lock()

    @property
    def pid(self):
        return self.proc.pid if self.proc and self.proc.poll() is None else None

    def start(self) -> None:
        try:
            self.proc = subprocess.Popen(
                [self.python_exe, self.worker_script, self.ref_wav],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, bufsize=1,
            )
        except OSError as exc:
            self._degrade(f"could not launch voice worker: {exc}")
            return

        deadline = time.monotonic() + self.ready_timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                self._degrade("voice worker exited before becoming ready")
                return
            line = self.proc.stdout.readline()
            if not line:
                self._degrade("voice worker closed its output before ready")
                return
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("ready"):
                self.ready = True
                return
        self._degrade("voice worker did not become ready in time")

    def convert(self, in_path: str, out_path: str) -> bool:
        """True if `out_path` now holds Johnny-voiced audio."""
        if not self.ready or self.pid is None:
            return False
        with self._lock:
            self._next_id += 1
            request = {"id": self._next_id, "op": "convert",
                       "input": in_path, "output": out_path}
            try:
                self.proc.stdin.write(json.dumps(request) + "\n")
                self.proc.stdin.flush()
                line = self.proc.stdout.readline()
            except (BrokenPipeError, OSError) as exc:
                self._degrade(f"voice worker pipe broke: {exc}")
                return False

        if not line:
            self._degrade("voice worker died mid-conversion")
            return False
        try:
            msg = json.loads(line)
        except ValueError:
            self.last_error = "voice worker sent malformed output"
            return False
        if not msg.get("ok"):
            self.last_error = msg.get("error", "voice conversion failed")
            return False
        return True

    def _degrade(self, reason: str) -> None:
        self.ready = False
        self.degraded = True
        self.last_error = reason

    def stop(self) -> None:
        if self.proc is None:
            return
        try:
            if self.proc.poll() is None:
                self.proc.stdin.write(json.dumps({"op": "shutdown"}) + "\n")
                self.proc.stdin.flush()
                self.proc.wait(timeout=5)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            self.proc.kill()
        finally:
            self.proc = None
            self.ready = False
```

- [ ] **Step 5: Run the tests and watch them pass**

Run: `cd ~/Projects/graywind/mavis && .venv/bin/python -m pytest tests/test_voice_client.py -q`
Expected: 7 passed

- [ ] **Step 6: Verify against the REAL worker**

The fake worker proves the plumbing; only the real one proves the premise. This takes about 30 seconds.

```bash
cd ~/Projects/graywind/mavis
.venv/bin/python - <<'PY'
import time
from avatar import voice_client as vc

client = vc.VoiceClient()
t0 = time.monotonic()
client.start()
print(f"startup: {time.monotonic() - t0:.1f}s ready={client.ready} degraded={client.degraded}")
if not client.ready:
    raise SystemExit(f"worker not ready: {client.last_error}")

vc.say_to_wav("Wake up. We got a city to burn.", "/tmp/scaffold.wav")

for i in (1, 2):
    t = time.monotonic()
    ok = client.convert("/tmp/scaffold.wav", f"/tmp/johnny_{i}.wav")
    print(f"convert #{i}: ok={ok} in {time.monotonic() - t:.1f}s")
client.stop()
PY
afplay /tmp/johnny_2.wav
```

Expected: startup 15-25s; **both** conversions in roughly the same time (a few seconds each) — if the *second* takes ~16s longer than the first, the worker is being restarted and the design is broken. Then listen: it should sound like the Bullion actor, not like macOS Tom.

- [ ] **Step 7: Commit**

```bash
cd ~/Projects/graywind
git add mavis/scripts/voice_worker.py mavis/avatar/voice_client.py mavis/tests/test_voice_client.py
git commit -m "feat(mavis): warm ChatterboxVC worker for Johnny's voice"
```

---

### Task 6: Wake word, capture, STT and answers

**Files:**
- Create: `mavis/avatar/wake.py`, `mavis/avatar/capture.py`, `mavis/avatar/stt.py`, `mavis/avatar/brain.py`
- Create: `tests/test_wake.py`, `tests/test_brain.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `wake.WakeListener(model_path, threshold=0.5)` with `.detect(frame: np.ndarray) -> bool`, `.reset() -> None`
  - `capture.record_utterance(seconds_max=12.0, silence_seconds=1.2) -> np.ndarray`
  - `stt.transcribe(samples: np.ndarray, sample_rate: int) -> str`
  - `brain.ask(query: str) -> str`, `brain.MAX_ANSWER_CHARS: int`

- [ ] **Step 1: Train the wake model (out of band, one time)**

This produces an artifact; no repo code depends on *how* it was made.

1. Open openWakeWord's `automatic_model_training.ipynb` in Google Colab (linked from https://github.com/dscripka/openWakeWord#training-new-models).
2. Set the target phrase to `wake up johnny`.
3. Run all cells — it synthesises training clips with Piper TTS and mixes in background noise. Expect roughly an hour, mostly unattended.
4. Download the resulting `.onnx` and place it:

```bash
mkdir -p ~/Projects/graywind/mavis/assets/wakeword
mv ~/Downloads/wake_up_johnny.onnx ~/Projects/graywind/mavis/assets/wakeword/
```

**Do not `pip install` the training dependencies into `mavis/.venv`** — they pull torch, and the runtime venv must stay torch-free.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_wake.py`:

```python
import numpy as np
import pytest

from avatar import wake


class FakeModel:
    """Stands in for openwakeword.Model so tests need no trained artifact."""

    def __init__(self, scores):
        self.scores = list(scores)
        self.reset_calls = 0

    def predict(self, frame):
        return {"wake_up_johnny": self.scores.pop(0)}

    def reset(self):
        self.reset_calls += 1


def _frame():
    return np.zeros(1280, dtype=np.int16)


def test_detects_when_score_crosses_threshold():
    listener = wake.WakeListener(model=FakeModel([0.9]), threshold=0.5)
    assert listener.detect(_frame()) is True


def test_does_not_detect_below_threshold():
    listener = wake.WakeListener(model=FakeModel([0.2]), threshold=0.5)
    assert listener.detect(_frame()) is False


def test_detection_resets_the_model_to_avoid_double_firing():
    """openWakeWord keeps internal state; without a reset one utterance can
    trigger on several consecutive frames."""
    model = FakeModel([0.9])
    listener = wake.WakeListener(model=model, threshold=0.5)
    listener.detect(_frame())
    assert model.reset_calls == 1


def test_missing_model_file_fails_with_a_useful_message(tmp_path):
    with pytest.raises(FileNotFoundError) as exc:
        wake.WakeListener(model_path=str(tmp_path / "nope.onnx"))
    assert "wake_up_johnny" in str(exc.value) or "nope.onnx" in str(exc.value)
```

Create `tests/test_brain.py`:

```python
import httpx
import pytest

from avatar import brain


def _client_for(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler),
                             base_url="http://localhost:8000")


@pytest.mark.asyncio
async def test_ask_returns_the_answer_text(monkeypatch):
    monkeypatch.setenv("MAVIS_API_KEY", "testkey")

    def handler(request):
        assert request.url.path == "/ask"
        assert request.headers["x-api-key"] == "testkey"
        return httpx.Response(200, json={"answer": "Night City burns.",
                                         "citations": []})

    client = _client_for(handler)
    try:
        assert await brain.ask("what's up", client=client) == "Night City burns."
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_long_answers_are_capped_at_a_sentence_boundary():
    """Voice conversion runs at ~1.4x realtime, so answer length is
    latency. Cutting mid-word would sound broken."""
    long_answer = ("This is a sentence. " * 80).strip()

    def handler(request):
        return httpx.Response(200, json={"answer": long_answer, "citations": []})

    client = _client_for(handler)
    try:
        result = await brain.ask("tell me everything", client=client)
    finally:
        await client.aclose()

    assert len(result) <= brain.MAX_ANSWER_CHARS
    assert result.endswith(".")


@pytest.mark.asyncio
async def test_backend_error_raises_brain_error():
    def handler(request):
        return httpx.Response(500, text="boom")

    client = _client_for(handler)
    try:
        with pytest.raises(brain.BrainError):
            await brain.ask("hello", client=client)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_unreachable_backend_raises_brain_error():
    def handler(request):
        raise httpx.ConnectError("refused")

    client = _client_for(handler)
    try:
        with pytest.raises(brain.BrainError):
            await brain.ask("hello", client=client)
    finally:
        await client.aclose()
```

- [ ] **Step 3: Run them and watch them fail**

Run: `cd ~/Projects/graywind/mavis && .venv/bin/python -m pytest tests/test_wake.py tests/test_brain.py -q`
Expected: FAIL — `ImportError: cannot import name 'wake'`

- [ ] **Step 4: Write `wake.py`**

```python
"""Wake-word detection for "Wake up, Johnny".

openWakeWord ships only six pretrained phrases (alexa, hey_mycroft,
hey_jarvis, hey_rhasspy, timer, weather) -- there is no "hey mavis" and no
"wake up johnny", so this loads a custom model trained out of band.

inference_framework must be "onnx": the library defaults to "tflite",
which has no wheel for this Python.
"""
from pathlib import Path

DEFAULT_MODEL = (Path(__file__).resolve().parent.parent
                 / "assets" / "wakeword" / "wake_up_johnny.onnx")

FRAME_SAMPLES = 1280
SAMPLE_RATE = 16000


class WakeListener:
    def __init__(self, model=None, model_path=None, threshold=0.5):
        self.threshold = threshold
        if model is not None:
            self.model = model
            return

        path = Path(model_path) if model_path else DEFAULT_MODEL
        if not path.exists():
            raise FileNotFoundError(
                f"wake-word model missing at {path} -- train "
                "wake_up_johnny.onnx with openWakeWord's Colab notebook "
                "and drop it in assets/wakeword/"
            )
        from openwakeword.model import Model
        self.model = Model(wakeword_models=[str(path)],
                           inference_framework="onnx")

    def detect(self, frame) -> bool:
        """True if this 1280-sample 16kHz int16 frame completes the phrase."""
        scores = self.model.predict(frame)
        if any(score >= self.threshold for score in scores.values()):
            self.reset()
            return True
        return False

    def reset(self) -> None:
        self.model.reset()
```

- [ ] **Step 5: Write `capture.py`**

```python
"""Record one spoken utterance from the default microphone."""
import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
BLOCK = 1280
SILENCE_RMS = 0.012


def record_utterance(seconds_max: float = 12.0,
                     silence_seconds: float = 1.2) -> np.ndarray:
    """Record until the speaker stops, or seconds_max, whichever first.

    Returns float32 samples in -1..1 at SAMPLE_RATE.
    """
    collected = []
    silent_blocks = 0
    needed_silent = int(silence_seconds * SAMPLE_RATE / BLOCK)
    max_blocks = int(seconds_max * SAMPLE_RATE / BLOCK)
    heard_speech = False

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                        blocksize=BLOCK) as stream:
        for _ in range(max_blocks):
            block, _overflowed = stream.read(BLOCK)
            mono = block[:, 0]
            collected.append(mono.copy())

            if float(np.sqrt(np.mean(np.square(mono)))) < SILENCE_RMS:
                silent_blocks += 1
                if heard_speech and silent_blocks >= needed_silent:
                    break
            else:
                heard_speech = True
                silent_blocks = 0

    if not collected:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(collected)
```

- [ ] **Step 6: Write `stt.py`**

```python
"""Transcribe an utterance with Groq's Whisper endpoint."""
import io
import os
import wave

import httpx
import numpy as np

GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_STT_MODEL = "whisper-large-v3-turbo"


class STTError(RuntimeError):
    pass


def _to_wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(sample_rate)
        fh.writeframes(pcm.tobytes())
    return buf.getvalue()


async def transcribe(samples: np.ndarray, sample_rate: int = 16000,
                     *, client: httpx.AsyncClient | None = None) -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise STTError("GROQ_API_KEY not set")
    if samples.size == 0:
        return ""

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=30.0)
    try:
        resp = await client.post(
            GROQ_STT_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": ("utterance.wav", _to_wav_bytes(samples, sample_rate),
                            "audio/wav")},
            data={"model": GROQ_STT_MODEL},
        )
    except httpx.RequestError as exc:
        raise STTError(f"speech-to-text unreachable: {exc}") from exc
    finally:
        if owns_client:
            await client.aclose()

    if resp.status_code != 200:
        raise STTError(f"speech-to-text failed ({resp.status_code})")
    return resp.json().get("text", "").strip()
```

- [ ] **Step 7: Write `brain.py`**

```python
"""Ask the already-running MAVIS backend.

Direct HTTP rather than MCP: this is a GUI app on the same machine as the
server, so it calls /ask exactly the way mcp_tools.call_ask does, without
an MCP layer in between.

Answers are capped because voice conversion runs at roughly 1.4x realtime
-- a 20-second answer costs ~28 seconds of conversion, so length is
latency, not just verbosity.
"""
import os
import re

import httpx

MAX_ANSWER_CHARS = 420


class BrainError(RuntimeError):
    pass


def _base_url() -> str:
    return os.environ.get("MAVIS_URL", "http://localhost:8000")


def cap(answer: str) -> str:
    """Trim to MAX_ANSWER_CHARS at a sentence boundary where possible."""
    answer = answer.strip()
    if len(answer) <= MAX_ANSWER_CHARS:
        return answer
    window = answer[:MAX_ANSWER_CHARS]
    sentences = re.findall(r".+?[.!?](?:\s|$)", window, flags=re.S)
    if sentences:
        return "".join(sentences).strip()
    return window.rsplit(" ", 1)[0].strip()


async def ask(query: str, *, client: httpx.AsyncClient | None = None) -> str:
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(base_url=_base_url(), timeout=60.0)
    try:
        resp = await client.post(
            "/ask", json={"query": query},
            headers={"X-API-Key": os.environ.get("MAVIS_API_KEY", "")},
        )
    except httpx.RequestError as exc:
        raise BrainError(f"MAVIS backend unreachable: {exc}") from exc
    finally:
        if owns_client:
            await client.aclose()

    if resp.status_code != 200:
        raise BrainError(f"MAVIS backend returned {resp.status_code}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise BrainError("MAVIS backend returned a non-JSON response") from exc
    return cap(body.get("answer", ""))
```

- [ ] **Step 8: Run the tests and watch them pass**

Run: `cd ~/Projects/graywind/mavis && .venv/bin/python -m pytest tests/test_wake.py tests/test_brain.py -q`
Expected: 8 passed

- [ ] **Step 9: Verify the wake model fires on your actual voice**

```bash
cd ~/Projects/graywind/mavis
.venv/bin/python - <<'PY'
import numpy as np, sounddevice as sd
from avatar import wake
listener = wake.WakeListener()
print('say "Wake up, Johnny" -- ctrl-C to stop')
with sd.InputStream(samplerate=16000, channels=1, dtype='int16', blocksize=1280) as s:
    while True:
        block, _ = s.read(1280)
        if listener.detect(block[:, 0]):
            print("  DETECTED")
PY
```

Expected: fires when you say it; stays quiet through ordinary conversation. If it misfires constantly or never triggers, raise/lower `threshold` before moving on — a bad wake model makes the finished app unusable.

- [ ] **Step 10: Commit**

```bash
cd ~/Projects/graywind
git add mavis/avatar mavis/tests/test_wake.py mavis/tests/test_brain.py mavis/assets/wakeword
git commit -m "feat(mavis): wake word, capture, STT and answer plumbing"
```

---

### Task 7: The state machine, and the live run

**Files:**
- Create: `mavis/avatar/app.py`
- Create: `tests/test_app_states.py`

**Interfaces:**
- Consumes: every module above
- Produces: `app.AvatarApp` with `.state: str` in `{"sleeping", "listening", "thinking", "speaking"}`; `python -m avatar.app` entry point

- [ ] **Step 1: Write the failing test**

State transitions are tested without audio hardware or a window by driving the machine directly.

Create `tests/test_app_states.py`:

```python
import numpy as np
import pytest

from avatar import app


class StubScene:
    def __init__(self):
        self.mouth = 0.0
        self.visible = False
        self.notice = None

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def set_mouth(self, amount):
        self.mouth = amount

    def show_notice(self, text):
        self.notice = text


@pytest.fixture
def machine():
    return app.AvatarApp(scene=StubScene(), voice=None, listener=None)


def test_starts_asleep_and_hidden(machine):
    assert machine.state == "sleeping"
    assert machine.scene.visible is False


def test_waking_shows_the_avatar(machine):
    machine.on_wake()
    assert machine.state == "listening"
    assert machine.scene.visible is True


def test_dismissal_transcript_sends_him_away(machine):
    machine.on_wake()
    machine.on_transcript("that's all")
    assert machine.state == "sleeping"
    assert machine.scene.visible is False


def test_question_transcript_moves_to_thinking(machine):
    machine.on_wake()
    machine.on_transcript("what are the tier pools doing")
    assert machine.state == "thinking"


def test_empty_transcript_stays_listening(machine):
    machine.on_wake()
    machine.on_transcript("")
    assert machine.state == "listening"


def test_degraded_voice_shows_a_notice(machine):
    machine.note_degraded("voice worker died")
    assert machine.scene.notice is not None
    assert "voice" in machine.scene.notice.lower()


def test_sleeping_closes_the_mouth(machine):
    machine.on_wake()
    machine.scene.set_mouth(0.8)
    machine.on_transcript("go away")
    assert machine.scene.mouth == 0.0
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd ~/Projects/graywind/mavis && .venv/bin/python -m pytest tests/test_app_states.py -q`
Expected: FAIL — `ImportError: cannot import name 'app'`

- [ ] **Step 3: Write the implementation**

Create `mavis/avatar/app.py`:

```python
"""The avatar's state machine and entry point.

Sleeping -> (wake word) -> Listening -> (question) -> Thinking ->
Speaking -> Listening, and any transcript that reads as a dismissal drops
straight back to Sleeping.

Speaking only ever animates against audio that has already been fully
generated. That ordering is deliberate: it guarantees the renderer and a
neural model never contend for this machine's 8GB at the same moment.
"""
import asyncio
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

from avatar import brain, dismiss, lipsync, stt, voice_client

SLEEPING, LISTENING, THINKING, SPEAKING = (
    "sleeping", "listening", "thinking", "speaking")


class AvatarApp:
    def __init__(self, scene, voice=None, listener=None):
        self.scene = scene
        self.voice = voice
        self.listener = listener
        self.state = SLEEPING
        self.scene.hide()

    def on_wake(self) -> None:
        self.state = LISTENING
        self.scene.show()

    def on_transcript(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return self.state
        if dismiss.is_dismissal(text):
            self.sleep()
            return self.state
        self.state = THINKING
        return self.state

    def sleep(self) -> None:
        self.state = SLEEPING
        self.scene.set_mouth(0.0)
        self.scene.hide()

    def note_degraded(self, reason: str) -> None:
        self.scene.show_notice(f"Voice degraded: {reason} -- using plain speech")


def _read_wav(path):
    with wave.open(str(path), "rb") as fh:
        rate = fh.getframerate()
        raw = fh.readframes(fh.getnframes())
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return samples, rate


async def speak(app_state, text, play):
    """Generate audio fully, then hand it to `play` with its envelope."""
    tmp = Path(tempfile.mkdtemp())
    scaffold, final = tmp / "scaffold.wav", tmp / "johnny.wav"

    voice_client.say_to_wav(text, str(scaffold))
    converted = app_state.voice.convert(str(scaffold), str(final)) \
        if app_state.voice else False

    if not converted:
        if app_state.voice and app_state.voice.last_error:
            app_state.note_degraded(app_state.voice.last_error)
        final = scaffold

    samples, rate = _read_wav(final)
    play(str(final), lipsync.envelope(samples, rate))


def main() -> int:
    from panda3d.core import loadPrcFileData
    loadPrcFileData("", "window-title Johnny\nhardware-animated-vertices false")
    from direct.showbase.ShowBase import ShowBase
    from avatar import scene as scene_mod

    base = ShowBase()
    scene = scene_mod.AvatarScene(base)
    voice = voice_client.VoiceClient()
    voice.start()

    app_state = AvatarApp(scene=scene, voice=voice)
    if voice.degraded:
        app_state.note_degraded(voice.last_error or "worker unavailable")

    try:
        base.run()
    finally:
        voice.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Add `show_notice` to `AvatarScene` in `avatar/scene.py`:

```python
    def show_notice(self, text: str) -> None:
        """Degraded states must be visible -- never fail silently."""
        if getattr(self, "_notice", None) is None:
            from direct.gui.OnscreenText import OnscreenText
            from panda3d.core import TextNode
            self._notice = OnscreenText(
                text="", pos=(0.0, 0.88), scale=0.05,
                fg=(1.0, 0.6, 0.3, 1.0), align=TextNode.ACenter, mayChange=True)
        self._notice.setText(text)
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd ~/Projects/graywind/mavis && .venv/bin/python -m pytest tests/test_app_states.py -q`
Expected: 7 passed

- [ ] **Step 5: Run the whole suite**

Run: `cd ~/Projects/graywind/mavis && .venv/bin/python -m pytest -q`
Expected: 81 passed (50 existing + 31 new)

- [ ] **Step 6: THE LIVE ACCEPTANCE RUN**

Automated tests cannot pass this task. Every MAVIS session so far has ended with a real run, and so does this one.

```bash
cd ~/Projects/graywind/mavis
export GROQ_API_KEY=...   # if not already exported
export MAVIS_API_KEY=...
.venv/bin/uvicorn app:app --port 8000 &   # backend, if not already running
.venv/bin/python -m avatar.app
```

Walk the whole path and confirm each step:

1. Say **"Wake up, Johnny"** → the window appears, the avatar animates.
2. Ask a real question ("what are the tier pools doing?") → an answer comes back.
3. It is spoken **in the actor's voice**, not macOS Tom, and **his mouth moves with it**.
4. Say **"that's all"** → he disappears.
5. Say **"Wake up, Johnny"** again → he comes back, and the second reply is **not** ~16s slower than the first (proving the worker stayed warm).

- [ ] **Step 7: Commit and finish the branch**

```bash
cd ~/Projects/graywind
git add mavis/avatar mavis/tests/test_app_states.py
git commit -m "feat(mavis): avatar state machine and entry point"
```

Then use `superpowers:finishing-a-development-branch` to decide how `feat/mavis-avatar` lands.

---

## Self-Review

**Spec coverage** — every section maps to a task: asset repair → 1; renderer + attribution + `MOUTH_GAIN` → 2; lip-sync → 3; dismissal → 4; warm worker + fallback → 5; wake word/STT/`/ask` + answer cap → 6; state machine, error notices, live acceptance → 7. The spec's "render test not yet run" open item is Task 2 Step 6, with an explicit stop instruction. The "training deps never enter the runtime venv" constraint appears in Global Constraints and again in Task 6 Step 1.

**Placeholders** — none. Every code step carries real code; every verification step names a command and its expected output.

**Type consistency** — `set_mouth`/`show`/`hide`/`show_notice` match between `scene.py`, `StubScene` and `app.py`. `envelope`/`amount_at` signatures match their uses. `VoiceClient.convert` returns `bool` everywhere. `brain.ask` and `stt.transcribe` are both async and awaited as such.

**Steps only a human can run:** Task 2 Step 6 (window, mouth legibility, credit), Task 5 Step 6 (listening to the converted voice), Task 6 Step 9 (speaking the wake phrase), Task 7 Step 6 (the full live acceptance). No subagent can sign these off — they come back to the operator regardless of how the rest is executed.

**Known gap, deliberate:** `capture.py` and `stt.py` have no unit tests — both are thin wrappers over hardware and a network call, where a mock would test the mock. They are covered by Task 6 Step 9 and Task 7 Step 6 live runs.
