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

MOUTH_GAIN = 1.5
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
        # mayChange=True keeps a live TextNode. The default flattens the text
        # into a bare PandaNode, after which the credit can no longer be read
        # back off the node -- and this credit is a licence condition, so it
        # has to stay verifiable.
        self.credit = OnscreenText(
            text=CREDIT, pos=(0.0, -0.95), scale=0.04,
            fg=(0.8, 0.8, 0.85, 1.0), align=TextNode.ACenter, mayChange=True,
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
