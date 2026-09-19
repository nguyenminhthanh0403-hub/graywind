"""The Panda3D side of the avatar: window, model, idle motion, mouth.

Mouth movement is driven by CharacterSlider morph targets rather than a
jaw bone -- this model has no jaw joint. The sliders are reached by
walking the character's PartBundle; they are NOT scene-graph nodes, so
NodePath searches for them return nothing.

MOUTH_GAIN is an amplification knob for that morph. A slider value of 1.0
displaces head vertices by only ~0.011 units on a ~1.85-unit model (~11mm
of jaw travel), which was expected to read as a twitch rather than speech.
It does not: once the head is framed properly the raw movement is enough,
and 1.0 was chosen by eye over 1.5/2.0/3.0. The knob stays because morph
targets extrapolate linearly, so a re-framed or swapped model can want
more; judge it against a real window, not against this number.
"""
import math
from pathlib import Path

from direct.actor.Actor import Actor
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import AmbientLight, DirectionalLight, TextNode, Vec4

ASSET = Path(__file__).resolve().parent.parent / "assets" / "avatar" / "jonny_fixed.bam"

MOUTH_GAIN = 1.0
CREDIT = 'Model: "Jonny Silverhand" by Stuxed (CC BY)'

HEAD_MESH = "Wolf3D_Head"
# Framing height as a multiple of the head's own height: ~2.6 puts head and
# shoulders in frame with air above. Measured at load rather than hardcoded so
# a swapped-in model of a different scale still frames itself correctly.
FRAMING = 2.6
DEFAULT_FOV = 30.0


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
        self._init_shader()
        self.actor = load_actor(show_base.loader)
        self.actor.reparent_to(show_base.render)
        self._frame_head()

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

    def _init_shader(self):
        """Install the PBR shader the glTF materials are written against.

        The model's colour lives in each material's baseColorTexture. Panda3D's
        fixed-function pipeline has no idea how to sample that, so it lights the
        material colours alone and the avatar renders as a flat grey figure --
        textures fully loaded, fully bound, entirely unused. simplepbr supplies
        the shader that reads them.

        Skipped without a window (window-type none in the tests), where there is
        no graphics context to compile shaders against.
        """
        if self.base.win is None:
            return
        import simplepbr

        self.pipeline = simplepbr.init(msaa_samples=0)

    def _frame_head(self):
        """Place the actor so the head fills the frame, from measured bounds.

        The camera stays at the origin looking down +Y. Distance is solved from
        the lens's own vertical FOV, so this holds if the lens changes -- and
        measuring beats hardcoding because model scale is not knowable up front:
        this one is ~1.85 units tall, and an earlier hardcoded offset written
        for an assumed ~1.7 left the camera inside the geometry.
        """
        self.actor.set_pos(0, 0, 0)
        head = self.actor.find(f"**/{HEAD_MESH}")
        target = self.actor if head.is_empty() else head

        low, high = target.get_tight_bounds()
        center_z = (low[2] + high[2]) / 2.0
        framed = max(high[2] - low[2], 1e-3) * FRAMING

        # No lens exists under window-type none, where the framing is arithmetic
        # rather than something anyone looks at; Panda3D's own default stands in.
        lens = self.base.camLens
        fov_v = lens.get_fov()[1] if lens is not None else DEFAULT_FOV
        distance = (framed / 2.0) / math.tan(math.radians(fov_v / 2.0))
        self.actor.set_pos(0, distance, -center_z)

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
