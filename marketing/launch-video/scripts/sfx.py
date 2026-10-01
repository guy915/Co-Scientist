"""Synthesizes the launch film's sound effects into public/sfx/*.wav.

Every effect is dry (no reverb tail) with a fast attack and most of its energy
in the 2-8 kHz band, where the soundtrack's dense low-mid mix leaves room; a
reverb-washed or bass-heavy effect disappears under the music. Pitched effects
are tuned to the soundtrack's key, B-flat major, on its pentatonic scale, so
they read as part of the track rather than against it.

Each file peaks at -1 dBFS; the composition sets each placement's level.

Usage: uv run --with numpy --with scipy python scripts/sfx.py
"""

import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, istft, sosfilt, stft

SR = 48_000
OUT = Path(__file__).resolve().parent.parent / "public" / "sfx"
rng = np.random.default_rng(7)

# B-flat major pentatonic, Bb5 upward: Bb C D F G. The recording is tuned about
# 18 cents sharp of A=440 (its Bb5 measures 941 Hz), so the scale is raised to
# match; at A=440 a sustained ding would beat against the track's own notes.
TUNING = 2 ** (18 / 1200)
PENTA = [
    f * TUNING
    for f in (932.33, 1046.50, 1174.66, 1396.91, 1567.98, 1864.66, 2093.00, 2349.32)
]


def n_of(seconds):
    return int(seconds * SR)


def t_axis(seconds):
    return np.arange(n_of(seconds)) / SR


def band(x, lo, hi, order=4):
    return sosfilt(butter(order, [lo, hi], btype="band", fs=SR, output="sos"), x)


def high(x, f, order=4):
    return sosfilt(butter(order, f, btype="high", fs=SR, output="sos"), x)


def decay(seconds, tau, attack=0.001):
    t = t_axis(seconds)
    return np.minimum(1, t / attack) * np.exp(-t / tau)


def noise(seconds):
    return rng.standard_normal(n_of(seconds))


def sine(seconds, f0, f1=None, glide=0.02):
    """Sine whose pitch glides from f0 to f1 over `glide` seconds, then holds."""
    t = t_axis(seconds)
    f = np.full_like(t, f1 if f1 is not None else f0)
    if f1 is not None:
        k = np.clip(t / glide, 0, 1)
        f = f0 * (f1 / f0) ** (1 - (1 - k) ** 2)
    return np.sin(2 * np.pi * np.cumsum(f) / SR)


def fit(x, seconds):
    out = np.zeros(n_of(seconds))
    out[: min(len(x), len(out))] = x[: len(out)]
    return out


def transient(seconds=0.004, lo=2500):
    """A 1-4 ms high-passed noise snap: the 'crisp' in every click."""
    return high(noise(seconds), lo) * decay(seconds, seconds / 4, 0.0002)


def at(x, offset, total):
    out = np.zeros(n_of(total))
    i = n_of(offset)
    out[i : i + len(x)] = x[: len(out) - i]
    return out


# ---- the effects -----------------------------------------------------------


def tick():
    d = 0.05
    return fit(transient(0.003, 3000), d) + 0.5 * sine(d, 4200) * decay(d, 0.008)


def key(i):
    d = 0.06
    body = sine(d, 260 + 40 * i) * decay(d, 0.006) * 0.5
    clack = band(noise(d), 1800 + 300 * i, 7000) * decay(d, 0.010 + 0.002 * i, 0.0005)
    return clack + body + 0.25 * sine(d, 2100 + 150 * i) * decay(d, 0.005)


def click():
    """Mouse press then release, 45 ms apart, as a real button sounds."""
    d = 0.12

    def one(f):
        s = 0.06
        return fit(transient(0.003, 2200), s) + 0.6 * sine(s, f) * decay(s, 0.007)

    return at(one(3000), 0, d) + 0.6 * at(one(3600), 0.045, d)


def pop(f):
    """A bubbly, tuned pop: the pitch springs up into the note."""
    d = 0.18
    tone = sine(d, f * 0.62, f, 0.018) * decay(d, 0.045, 0.0015)
    return (
        tone
        + 0.18 * sine(d, 2 * f) * decay(d, 0.02)
        + 0.35 * fit(transient(0.002, 3500), d)
    )


def blip(f):
    d = 0.09
    return sine(d, f) * decay(d, 0.022, 0.002) + 0.12 * sine(d, 3 * f) * decay(d, 0.01)


def swish(d=0.2, f0=1200, f1=7000, peak=0.7):
    """Band-limited air moving past: the filter sweeps with the motion."""
    t = t_axis(d)
    # A sliding band-pass done in the STFT domain: a per-block IIR would click
    # at every block seam, which is exactly the grit this film is avoiding.
    fr, tt, z = stft(noise(d + 0.02), fs=SR, nperseg=512, noverlap=384)
    c = f0 * (f1 / f0) ** np.clip(tt / d, 0, 1)
    octaves = np.log2(np.maximum(fr, 1)[:, None] / c[None, :])
    _, out = istft(
        z * np.exp(-0.5 * (octaves / 0.55) ** 2), fs=SR, nperseg=512, noverlap=384
    )
    out = fit(out, d)
    shape = np.where(
        t < peak * d, (t / (peak * d)) ** 2, np.exp(-(t - peak * d) / (0.12 * d))
    )
    return out * shape


def rise(d=0.55):
    """Reverse swell: grows and brightens, then stops dead on its last sample."""
    t = t_axis(d)
    x = swish(d, 600, 9000, 0.999)
    return (
        x * (t / d) ** 1.5
        + 0.15 * sine(d, 466.16 * TUNING, 1864.66 * TUNING, d) * (t / d) ** 3
    )


def ding(f):
    d = 1.1
    partials = [
        (1.0, 1.0, 0.7),
        (2.0, 0.35, 0.35),
        (3.01, 0.18, 0.18),
        (4.2, 0.08, 0.1),
    ]
    x = sum(a * sine(d, f * m) * decay(d, tau, 0.001) for m, a, tau in partials)
    return x + 0.3 * fit(transient(0.002, 4000), d)


def sparkle():
    d = 0.7
    x = np.zeros(n_of(d))
    notes = PENTA[3:] + [2793.83 * TUNING, 3135.96 * TUNING]
    for k in range(10):
        s = blip(notes[rng.integers(len(notes))] * 2) * (0.9**k)
        x += at(s, 0.04 * k + rng.uniform(0, 0.015), d)
    return x


def clack():
    """Two ideas colliding: a snap with a short, tight thump under it."""
    d = 0.16
    thump = sine(d, 140, 70, 0.05) * decay(d, 0.035, 0.001)
    snap = band(noise(d), 1500, 6000) * decay(d, 0.012, 0.0005)
    return 0.8 * thump + snap + 0.6 * fit(transient(0.003, 2500), d)


def morph():
    d = 0.12
    return sine(d, 700, PENTA[2], 0.035) * decay(d, 0.03, 0.002) + 0.2 * fit(
        transient(0.002, 4000), d
    )


def send():
    d = 0.4
    return 0.7 * at(swish(0.22, 1500, 8000, 0.3), 0, d) + at(pop(PENTA[5]), 0.03, d)


def shutter():
    d = 0.12
    return 0.8 * fit(swish(0.09, 3000, 9000, 0.2), d) + 0.5 * fit(tick(), d)


SOUNDS = {
    "tick": tick,
    "click": click,
    "swish": lambda: swish(0.2),
    "whoosh": lambda: swish(0.45, 900, 5000, 0.55),
    "rise": rise,
    "ding": lambda: ding(PENTA[3]),
    "ding-hi": lambda: ding(PENTA[5]),
    "sparkle": sparkle,
    "clack": clack,
    "morph": morph,
    "send": send,
    "shutter": shutter,
    **{f"key{i}": (lambda i=i: key(i)) for i in range(4)},
    **{f"pop{i}": (lambda i=i: pop(PENTA[i])) for i in range(len(PENTA))},
    **{f"blip{i}": (lambda i=i: blip(PENTA[i] * 2)) for i in range(len(PENTA))},
}


def write(name, x):
    x = x / (np.abs(x).max() + 1e-9) * 10 ** (-1 / 20)
    # A 2 ms fade-out so no file ends on a click of its own.
    x[-n_of(0.002) :] *= np.linspace(1, 0, n_of(0.002))
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(OUT / f"{name}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, make in SOUNDS.items():
        write(name, make())
    print(f"{len(SOUNDS)} effects -> {OUT}")
