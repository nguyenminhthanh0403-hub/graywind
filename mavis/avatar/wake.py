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
