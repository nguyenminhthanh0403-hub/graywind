"""
Pure state‑machine for the Johnny avatar.

The AvatarApp class contains no I/O, no sleeping and no threading – it is
intended to be called only from the render thread.  It manipulates the
provided ``scene`` (show/hide, mouth, pose clips, notices) and decides which
pre‑recorded line (if any) the caller should play.  All side‑effects are
delegated to the ``scene`` and optional ``canned`` line provider.
"""

from typing import Any, Dict, Tuple, Optional

# public state constants
SLEEPING = "sleeping"
LISTENING = "listening"
THINKING = "thinking"
SPEAKING = "speaking"
DISMISSING = "dismissing"

# the dismiss helper lives in the package; import the function we need
from avatar import dismiss


class AvatarApp:
    """Pure state machine driving the avatar.

    ``scene`` supplies visual control; ``canned`` supplies optional pre‑recorded
    audio lines.  The machine never touches files, threads or sleeps.
    """

    def __init__(self, scene: Any, canned: Optional[Any] = None) -> None:
        self.scene = scene
        self.canned = canned
        self.state: str = SLEEPING
        # remember the last line text per moment so we can avoid immediate repeats
        self._last: Dict[str, str] = {}
        self.scene.hide()

    # ------------------------------------------------------------------ helpers
    def _pose(self, moment: str) -> None:
        """Play the clip associated with *moment* (if any)."""
        clip = self.scene.config.get("poses", {}).get(moment)
        if clip:
            # looping is disabled only for the "dismissing" moment
            loop = moment != "dismissing"
            self.scene.play(clip, loop=loop)

    def _line(self, moment: str) -> Optional[Tuple[str, str]]:
        """Return a (text, wav_path) tuple from ``canned`` for *moment*."""
        if self.canned is None:
            return None
        pick = self.canned.path_for(moment, exclude=self._last.get(moment))
        if pick:
            self._last[moment] = pick[0]
        return pick

    # ----------------------------------------------------------- public API
    def on_wake(self) -> Optional[Tuple[str, str]]:
        """Transition from SLEEPING → LISTENING, show avatar, play listening pose,
        and return a greeting line if available."""
        if self.state != SLEEPING:
            return None
        self.state = LISTENING
        self.scene.show()
        self._pose("listening")
        return self._line("greeting")

    def on_silence(self) -> Optional[Tuple[str, str]]:
        """While listening, prompt the user (e.g. with a “thinking” pose) and
        return an idle line."""
        if self.state != LISTENING:
            return None
        self._pose("prompting")
        return self._line("idle")

    def on_transcript(self, text: Optional[str]) -> Tuple[str, Optional[Tuple[str, str]]]:
        """Handle a recognised utterance while listening.

        Returns a tuple ``(action, line)`` where *action* is one of:
        - ``"ignore"`` – empty or non‑listening state
        - ``"dismiss"`` – user wants to end the session
        - ``"ask"`` – normal query, transition to THINKING
        The *line* part is the canned audio (or ``None``).
        """
        if self.state != LISTENING:
            return ("ignore", None)

        # Normalise input
        txt = (text or "").strip()
        if not txt:
            return ("ignore", None)

        # Dismissal takes precedence
        if dismiss.is_dismissal(txt):
            self.state = DISMISSING
            self.scene.set_mouth(0.0)
            self._pose("dismissing")
            return ("dismiss", self._line("dismissal"))

        # Regular query
        self.state = THINKING
        self._pose("thinking")
        return ("ask", self._line("filler"))

    def on_answer_ready(self) -> None:
        """The answer has been generated; switch to SPEAKING pose."""
        if self.state != THINKING:
            return
        self.state = SPEAKING
        self._pose("speaking")

    def on_failure(self, reason: str) -> None:
        """Something went wrong while thinking or speaking – show a notice and
        return to listening."""
        if self.state not in (THINKING, SPEAKING):
            return
        self.scene.show_notice(reason)
        self.scene.set_mouth(0.0)
        self.state = LISTENING
        self._pose("listening")

    def on_spoken(self) -> None:
        """The spoken line finished; go back to listening."""
        if self.state != SPEAKING:
            return
        self.scene.set_mouth(0.0)
        self.state = LISTENING
        self._pose("listening")

    def sleep(self) -> None:
        """Force the avatar back to the sleeping state, hide it."""
        self.state = SLEEPING
        self.scene.set_mouth(0.0)
        self.scene.hide()

    def note_degraded(self, reason: str) -> None:
        """Inform the user that voice synthesis is degraded."""
        self.scene.show_notice(f"Voice degraded: {reason} -- using plain speech")
