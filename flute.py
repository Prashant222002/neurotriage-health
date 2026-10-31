"""Round 6: calming flute music (offline synth). Slow pentatonic phrases, breath noise, vibrato, soft room reverb + low drone.
Stereo float32 (n,2), peak ~0.9. seed -> different melody per video."""
import numpy as np

SR = 44100
SCALE = [62, 64, 66, 69, 71, 74, 76]          # D major pentatonic-ish, calm


def _hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def _note(f, dur, rng):
    n = int(dur * SR)
    t = np.arange(n) / SR
    vib = 1 + 0.004 * np.sin(2 * np.pi * 5.2 * t) * np.clip(t / 0.5, 0, 1)
    ph = 2 * np.pi * np.cumsum(f * vib) / SR
    x = np.sin(ph) + 0.28 * np.sin(2 * ph) + 0.08 * np.sin(3 * ph)
    breath = rng.standard_normal(n) * 0.05
    breath = np.convolve(breath, np.ones(6) / 6, "same")
    env = np.minimum(1, t / 0.18) * np.minimum(1, (dur - t) / 0.45) * (0.85 + 0.15 * np.sin(2 * np.pi * 0.7 * t))
    return ((x + breath) * np.clip(env, 0, 1)).astype(np.float32)


def _reverb(x, rng, secs=2.2):
    n = int(secs * SR)
    ir = rng.standard_normal(n) * np.exp(-np.arange(n) / SR * 3.0)
    ir = np.convolve(ir, np.ones(20) / 20, "same")
    ir /= np.sqrt((ir ** 2).sum()) + 1e-9
    N = 1 << int(np.ceil(np.log2(len(x) + len(ir))))
    return np.fft.irfft(np.fft.rfft(x, N) * np.fft.rfft(ir, N), N)[: len(x)].astype(np.float32)


def synth(total, seed=7):
    rng = np.random.default_rng(seed)
    n = int(total * SR)
    mel = np.zeros(n, np.float32)
    pos, idx = 0.6, rng.integers(0, len(SCALE))
    while pos < total - 1:
        idx = int(np.clip(idx + rng.choice([-2, -1, -1, 0, 1, 1, 2]), 0, len(SCALE) - 1))
        d = float(rng.choice([1.6, 2.2, 3.0, 3.6]))
        s = _note(_hz(SCALE[idx]), min(d + 0.5, total - pos), rng)
        a = int(pos * SR)
        mel[a:a + len(s)] += s[: n - a]
        pos += d + float(rng.choice([0.0, 0.5, 1.2]))      # rests = calm
    t = np.arange(n) / SR
    drone = (np.sin(2 * np.pi * _hz(38) * t) + 0.5 * np.sin(2 * np.pi * _hz(45) * t)) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.05 * t)) * 0.25
    wet = _reverb(mel, rng)
    L = mel * 0.7 + wet * 0.6 + drone
    R = mel * 0.6 + np.roll(wet, 700) * 0.7 + drone
    out = np.stack([L, R], 1).astype(np.float32)
    out *= np.minimum(1, t / 2.0)[:, None] * np.minimum(1, (total - t) / 2.5)[:, None]
    return out * (0.9 / (np.abs(out).max() + 1e-9))
