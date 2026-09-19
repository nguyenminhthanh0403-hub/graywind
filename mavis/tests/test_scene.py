import sys
import types

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
    """Always the committed CC-BY model.

    `keanu` is gitignored -- it is an extracted CD Projekt Red asset and this
    repo is public -- so it is absent on a fresh clone and cannot be what the
    suite asserts against. Pinning also stops these tests from silently
    changing meaning on a machine that happens to have built the other model.
    """
    return scene.AvatarScene(base, "jonny")


def _vertices(actor, mesh):
    node = [g for g in actor.findAllMatches("**/+GeomNode")
            if g.getName() == mesh][0].node()
    vd = node.getGeom(0).getVertexData().animateVertices(
        True, Thread.getCurrentThread())
    reader = GeomVertexReader(vd, "vertex")
    out = []
    while not reader.isAtEnd():
        out.append(tuple(reader.getData3()))
    return out


def test_actor_loads_with_full_skeleton(avatar):
    assert len(avatar.actor.getJoints()) >= 77


def test_mouth_sliders_are_found(avatar):
    """Sliders live in the PartBundle, not the scene graph -- a
    findAllMatches("**/+CharacterSlider") search returns zero and is the
    reason an earlier session wrongly concluded this model had no morphs."""
    assert len(avatar.mouth_sliders) == 5


def test_set_mouth_moves_head_geometry(avatar):
    avatar.set_mouth(0.0)
    closed = _vertices(avatar.actor, "Wolf3D_Head")
    avatar.set_mouth(1.0)
    opened = _vertices(avatar.actor, "Wolf3D_Head")

    moved = sum(1 for a, b in zip(closed, opened) if a != b)
    assert moved > 500


def test_no_mesh_escapes_the_model_bounds(avatar):
    """Guards the built .bam, not the repair tool's GLB output.

    The .bam is a gitignored artifact rebuilt by whatever panda3d-gltf is
    installed, and every other test here samples only Wolf3D_Head. All of them
    passed while Wolf3D_Outfit_Bottom was exploded to +/-18 units by a
    mis-strided read -- the only symptom was a human noticing a grey mass on
    screen. A whole-model sanity check catches that class headlessly.
    """
    low, high = avatar.actor.get_tight_bounds()
    height = high[2] - low[2]
    assert 1.0 < height < 3.0, f"model is {height:.2f} units tall, not human-scale"

    for node in avatar.actor.findAllMatches("**/+GeomNode"):
        lo, hi = node.get_tight_bounds(avatar.actor)
        assert hi[2] - lo[2] <= height + 1e-3, (
            f"{node.getName()} spans {hi[2] - lo[2]:.2f} units inside a "
            f"{height:.2f}-unit model"
        )


def test_set_mouth_clamps_negative_input(avatar):
    avatar.set_mouth(-5.0)
    assert avatar.mouth_sliders[0].getValue() == 0.0


def test_attribution_text_is_present(avatar):
    assert "Stuxed" in avatar.credit.getText()


def test_every_avatar_declares_a_credit():
    """Attribution is a licence condition for the CC-BY model and basic
    honesty for the ported one, so no entry may ship without a credit."""
    for name, config in scene.AVATARS.items():
        assert config["credit"].strip(), f"{name} has no credit string"
        assert config["mouth"]["kind"] in scene._DRIVERS


def test_pbr_shader_initialises_once_per_window(base, monkeypatch):
    """simplepbr claims the display region via a FilterManager, so a second
    init dies with "Could not find appropriate DisplayRegion to filter" -- a
    second AvatarScene on one window (swapping models at runtime) crashed
    outright until the pipeline was cached on the ShowBase.

    Driven with a stub because the suite runs window-type none, where the
    real path is skipped entirely and the bug is invisible.
    """
    calls = []
    stub = types.ModuleType("simplepbr")
    stub.init = lambda **kwargs: calls.append(kwargs) or "pipeline"
    monkeypatch.setitem(sys.modules, "simplepbr", stub)
    monkeypatch.setattr(base, "win", object(), raising=False)
    monkeypatch.setattr(base, "_mavis_pbr_pipeline", None, raising=False)

    first = scene.AvatarScene(base, "jonny")
    second = scene.AvatarScene(base, "jonny")

    assert len(calls) == 1, f"simplepbr.init called {len(calls)} times"
    assert first.pipeline is second.pipeline


def test_explicit_unknown_avatar_is_rejected(monkeypatch):
    monkeypatch.setenv("MAVIS_AVATAR", "nobody")
    with pytest.raises(ValueError):
        scene.choose_avatar()


# --- the ported model: only runs where it has actually been built ----------

_KEANU = scene.ASSET_DIR / scene.AVATARS["keanu"]["bam"]
needs_keanu = pytest.mark.skipif(
    not _KEANU.exists(),
    reason="keanu.bam is gitignored (extracted CDPR asset); build it locally",
)


@pytest.fixture(scope="module")
def keanu(base):
    return scene.AvatarScene(base, "keanu")


@needs_keanu
def test_keanu_uses_the_jaw_joint_not_morphs(keanu):
    """This model has no morph targets at all -- Cyberpunk animates faces with
    joints, which is exactly why its facial rig survived extraction."""
    assert isinstance(keanu.mouth, scene._JawMouth)
    assert keanu.mouth_sliders == []


@needs_keanu
def test_keanu_jaw_moves_head_and_teeth(keanu):
    """Rotating a controlled joint does nothing visible without a bundle
    forceUpdate(); this fails flat if that call is ever dropped."""
    keanu.set_mouth(0.0)
    shut_head = _vertices(keanu.actor, "head")
    shut_teeth = _vertices(keanu.actor, "teeth")

    keanu.set_mouth(1.0)
    open_head = _vertices(keanu.actor, "head")
    open_teeth = _vertices(keanu.actor, "teeth")

    assert sum(1 for a, b in zip(shut_head, open_head) if a != b) > 500
    assert sum(1 for a, b in zip(shut_teeth, open_teeth) if a != b) > 100


@needs_keanu
def test_keanu_head_is_framed_in_actor_space(keanu):
    """get_tight_bounds() with no reference reports the mesh's own untrans-
    formed space. This model carries a scale above its meshes, so reading it
    that way is out by ~40x and frames empty air."""
    head = keanu.actor.find("**/head")
    low, high = head.get_tight_bounds(keanu.actor)
    assert 1.0 < low[2] < 2.0, f"head sits at z {low[2]:.2f}, not on a 1.8m body"
