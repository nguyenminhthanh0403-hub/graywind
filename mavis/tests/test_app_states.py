import pytest

from avatar import states
from avatar.states import AvatarApp, SLEEPING, LISTENING, THINKING, SPEAKING, DISMISSING


class StubScene:
    def __init__(self, config=None):
        self.visible = False
        self.mouth = None
        self.plays = []          # (clip, loop)
        self.notices = []
        self.config = config or {}

    def hide(self):
        self.visible = False

    def show(self):
        self.visible = True

    def play(self, clip, loop=True):
        self.plays.append((clip, loop))
        return True

    def set_mouth(self, v):
        self.mouth = v

    def show_notice(self, txt):
        self.notices.append(txt)


class StubCanned:
    def __init__(self):
        self.counters = {}
        self.last_exclude = {}

    def path_for(self, moment, exclude=None):
        self.last_exclude[moment] = exclude
        cnt = self.counters.get(moment, 0)
        # generate a candidate that avoids the excluded text
        while True:
            txt = f"{moment}-{cnt % 2}"
            if txt != exclude:
                break
            cnt += 1
        self.counters[moment] = cnt + 1
        return txt, f"/x/{txt}.wav"


@pytest.fixture
def scene():
    poses = {
        "listening": "listen_clip",
        "prompting": "prompt_clip",
        "thinking": "think_clip",
        "speaking": "speak_clip",
        "dismissing": "dismiss_clip",
    }
    return StubScene(config={"poses": poses})


@pytest.fixture
def canned():
    return StubCanned()


def test_initial_state(scene):
    app = AvatarApp(scene)
    assert app.state == SLEEPING
    assert not scene.visible


def test_wake_shows_and_greeting(scene, canned):
    app = AvatarApp(scene, canned)
    line = app.on_wake()
    assert app.state == LISTENING
    assert scene.visible
    assert scene.plays == [("listen_clip", True)]
    assert line == ("greeting-0", "/x/greeting-0.wav")
    # second wake does nothing
    assert app.on_wake() is None
    assert app.state == LISTENING
    assert len(scene.plays) == 1


def test_silence_prompt_and_idle(scene, canned):
    app = AvatarApp(scene, canned)
    app.on_wake()
    line1 = app.on_silence()
    assert scene.plays[-1] == ("prompt_clip", True)
    assert line1[0].startswith("idle-")
    # second idle should differ (exclude passed)
    line2 = app.on_silence()
    assert line2[0] != line1[0]
    assert canned.last_exclude["idle"] == line1[0]


def test_transcript_empty_ignored(scene, canned):
    app = AvatarApp(scene, canned)
    app.on_wake()
    assert app.on_transcript("") == ("ignore", None)
    assert app.on_transcript(None) == ("ignore", None)


def test_dismissal_transcript(scene, canned):
    app = AvatarApp(scene, canned)
    app.on_wake()
    action, line = app.on_transcript("that's all")
    assert action == "dismiss"
    assert line[0].startswith("dismissal-")
    assert app.state == DISMISSING
    assert scene.mouth == 0.0
    # dismising pose played once, loop=False
    assert ("dismiss_clip", False) in scene.plays
    assert scene.visible  # caller hides later


def test_sleep_hides(scene, canned):
    app = AvatarApp(scene, canned)
    app.on_wake()
    app.sleep()
    assert app.state == SLEEPING
    assert not scene.visible


def test_question_transcript(scene, canned):
    app = AvatarApp(scene, canned)
    app.on_wake()
    act, line = app.on_transcript("what are the tier pools doing")
    assert act == "ask"
    assert line[0].startswith("filler-")
    assert app.state == THINKING
    assert ("think_clip", True) in scene.plays


def test_answer_ready_and_spoken(scene, canned):
    app = AvatarApp(scene, canned)
    app.on_wake()
    app.on_transcript("hi")
    app.on_answer_ready()
    assert app.state == SPEAKING
    assert ("speak_clip", True) in scene.plays
    app.on_spoken()
    assert app.state == LISTENING
    assert scene.mouth == 0.0
    assert ("listen_clip", True) in scene.plays


def test_on_failure_from_thinking(scene, canned):
    app = AvatarApp(scene, canned)
    app.on_wake()
    app.on_transcript("hi")
    app.on_failure("boom")
    assert scene.notices[-1] == "boom"
    assert scene.mouth == 0.0
    assert app.state == LISTENING
    assert ("listen_clip", True) in scene.plays


def test_transcript_while_thinking_ignored(scene, canned):
    app = AvatarApp(scene, canned)
    app.on_wake()
    app.on_transcript("hi")
    assert app.state == THINKING
    assert app.on_transcript("something") == ("ignore", None)
    assert app.state == THINKING


def test_canned_none_behaviour(scene):
    app = AvatarApp(scene, canned=None)
    assert app.on_wake() is None
    app.on_wake()
    assert app.on_silence() is None
    assert app.on_transcript("hi") == ("ask", None)
    # filler line is None, but pose still changes
    assert ("think_clip", True) in scene.plays


def test_no_poses_config():
    s = StubScene(config={})  # no "poses" key
    app = AvatarApp(s, canned=None)
    app.on_wake()
    assert s.plays == []  # nothing played


def test_note_degraded_names_the_voice(scene):
    AvatarApp(scene).note_degraded("worker died")
    assert "voice" in scene.notices[-1].lower()


def test_real_pose_config_names_real_clips_and_moments():
    from avatar import scene as scene_mod
    moments = {"listening", "prompting", "thinking", "speaking", "dismissing"}
    for name, config in scene_mod.AVATARS.items():
        poses = config.get("poses", {})
        assert set(poses) <= moments, name
        assert set(poses.values()) <= set(config.get("anims", ())), name
