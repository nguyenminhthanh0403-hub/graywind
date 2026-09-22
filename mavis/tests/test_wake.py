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
