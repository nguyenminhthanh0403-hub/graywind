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
