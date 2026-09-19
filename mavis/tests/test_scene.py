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
