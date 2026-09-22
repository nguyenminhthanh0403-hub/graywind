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
