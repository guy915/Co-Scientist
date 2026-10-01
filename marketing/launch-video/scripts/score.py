"""Synthesizes each preview's soundtrack from its own cue sheet.

No licensed music: every sound is generated here, so the film can ship
anywhere. Cues are frame numbers at 30 fps on the same 120 bpm grid the
compositions cut on (one beat = 15 frames), so hits land on picture.

Usage: uv run --with numpy python scripts/score.py out/   -> out/{a,b,c}.wav
"""

import sys
import wave
from pathlib import Path

import numpy as np

SR = 48_000
FPS = 30
BEAT = 0.5  # seconds at 120 bpm
rng = np.random.default_rng(3)


def t_of(frame):
    return frame / FPS


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def env(n, a, d, s, r, sustain_n):
    """ADSR envelope over n samples (a/d/r in seconds)."""
    e = np.zeros(n)
    ai, di, ri = int(a * SR), int(d * SR), int(r * SR)
    k = 0
    for seg in (
        np.linspace(0, 1, ai, endpoint=False),
        np.linspace(1, s, di, endpoint=False),
        np.full(max(0, sustain_n), s),
        np.linspace(s, 0, ri),
    ):
        m = min(len(seg), n - k)
        e[k : k + m] = seg[:m]
        k += m
        if k >= n:
            break
    return e


class Mix:
    def __init__(self, seconds):
        self.buf = np.zeros((int(seconds * SR) + SR * 4, 2))

    def add(self, at, sig, gain=1.0, pan=0.0):
        i = int(at * SR)
        if i >= len(self.buf):
            return
        sig = sig[: len(self.buf) - i]
        left, right = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
        self.buf[i : i + len(sig), 0] += sig * gain * left
        self.buf[i : i + len(sig), 1] += sig * gain * right


def lowpass(x, cutoff):
    a = np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):  # short signals only
        acc = (1 - a) * v + a * acc
        y[i] = acc
    return y


def fast_lowpass(x, cutoff):
    """FFT brick-ish lowpass with a soft knee, for long signals."""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X *= 1 / (1 + (f / cutoff) ** 4)
    return np.fft.irfft(X, len(x))


def pad_note(midi, dur, bright=0.3):
    n = int((dur + 2.0) * SR)
    t = np.arange(n) / SR
    f0 = hz(midi)
    sig = sum(
        np.sin(2 * np.pi * f0 * d * t + rng.uniform(0, 6)) for d in (1, 1.003, 0.997)
    )
    sig += bright * sum(np.sin(2 * np.pi * f0 * 2 * d * t) for d in (1, 1.002)) * 0.5
    return sig * env(n, 0.9, 0.5, 0.7, 2.0, int(dur * SR) - int(1.4 * SR)) / 3


def pluck(midi, gain=1.0, decay=1.2):
    n = int(decay * 2.5 * SR)
    t = np.arange(n) / SR
    f0 = hz(midi)
    sig = (
        np.sin(2 * np.pi * f0 * t)
        + 0.35 * np.sin(2 * np.pi * f0 * 2 * t) * np.exp(-t * 6)
        + 0.12 * np.sin(2 * np.pi * f0 * 3 * t) * np.exp(-t * 9)
    )
    return gain * sig * np.exp(-t / decay * 3) * np.minimum(1, t * 400)


def bell(midi, gain=1.0):
    n = int(3.5 * SR)
    t = np.arange(n) / SR
    f0 = hz(midi)
    partials = [(1, 1, 1.0), (2.76, 0.4, 2.2), (5.4, 0.2, 3.5), (2.0, 0.3, 1.6)]
    sig = sum(
        a * np.sin(2 * np.pi * f0 * r * t) * np.exp(-t * k) for r, a, k in partials
    )
    return gain * sig * np.minimum(1, t * 300) * 0.5


def kick(gain=1.0):
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    f = 46 + 90 * np.exp(-t * 28)
    return gain * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 7)


def tick(gain=1.0, freq=4000):
    n = int(0.04 * SR)
    t = np.arange(n) / SR
    return (
        gain
        * (rng.standard_normal(n) * 0.4 + np.sin(2 * np.pi * freq * t))
        * np.exp(-t * 160)
    )


def key_click(gain=1.0):
    n = int(0.03 * SR)
    t = np.arange(n) / SR
    return gain * lowpass(rng.standard_normal(n), 2500) * np.exp(-t * 220)


def whoosh(dur=0.7, gain=1.0, rise=True):
    n = int(dur * SR)
    t = np.linspace(0, 1, n)
    shape = (t**2 if rise else (1 - t) ** 2) * np.sin(
        np.pi * np.minimum(t * 1.05, 1)
    ) ** 0.5
    noise = fast_lowpass(rng.standard_normal(n), 1800)
    return gain * noise * shape


def boom(gain=1.0):
    n = int(2.5 * SR)
    t = np.arange(n) / SR
    return (
        gain
        * (np.sin(2 * np.pi * 38 * t) + 0.3 * fast_lowpass(rng.standard_normal(n), 120))
        * np.exp(-t * 1.6)
        * np.minimum(1, t * 200)
    )


def reverb(buf, seconds=2.4, wet=0.28):
    out = buf.copy()
    n = int(seconds * SR)
    decay = np.exp(-np.arange(n) / SR * 3 / seconds)
    for ch in range(2):
        ir = rng.standard_normal(n) * decay
        ir = fast_lowpass(ir, 6000)
        ir /= np.sqrt(np.sum(ir**2))
        L = len(buf) + n
        size = 1 << (L - 1).bit_length()
        y = np.fft.irfft(np.fft.rfft(buf[:, ch], size) * np.fft.rfft(ir, size), size)[
            : len(buf)
        ]
        out[:, ch] = buf[:, ch] * (1 - wet) + y * wet
    return out


# Chords as MIDI notes: Cmaj9, Am9, Fmaj7#11, Gsus — bright, unresolved, Google-ish.
CHORDS = [
    [48, 55, 59, 62, 64],
    [45, 52, 55, 59, 60],
    [41, 48, 52, 55, 59],
    [43, 50, 55, 57, 62],
]
DARK = [[38, 45, 50, 53], [34, 41, 46, 50], [36, 43, 48, 51], [33, 40, 45, 48]]


def bed(m, seconds, chords, bars_per=2, gain=0.09, bright=0.3, start=0.0):
    bar = BEAT * 4
    k = 0
    at = start
    while at < seconds:
        for note in chords[k % len(chords)]:
            m.add(
                at,
                pad_note(note, bar * bars_per, bright),
                gain,
                pan=rng.uniform(-0.4, 0.4),
            )
        at += bar * bars_per
        k += 1


def arp(m, start, end, chords, gain=0.11, step=BEAT / 2, octave=24, bars_per=2):
    at = start
    i = 0
    while at < end:
        chord = chords[int(at // (BEAT * 4 * bars_per)) % len(chords)]
        note = chord[[1, 2, 3, 4, 3, 2][i % 6] % len(chord)] + octave
        m.add(at, pluck(note, decay=0.9), gain, pan=0.5 * np.sin(i))
        at += step
        i += 1


def typing(m, start_f, end_f, gain=0.18):
    at = t_of(start_f)
    while at < t_of(end_f):
        m.add(at, key_click(), gain * rng.uniform(0.6, 1), pan=rng.uniform(-0.2, 0.2))
        at += rng.uniform(0.045, 0.09)


def finish(m, path, seconds, master=0.9):
    out = reverb(m.buf)
    out = out[: int(seconds * SR)]
    fade = int(1.2 * SR)
    out[-fade:] *= np.linspace(1, 0, fade)[:, None]
    out *= master / np.max(np.abs(out))
    pcm = (np.clip(out, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def resolve(m, at, notes=(60, 64, 67, 71, 74), boom_gain=0.0):
    """The end-card chord: a lift into the lockup and a bell on it."""
    m.add(at - 1.0, whoosh(1.0), 0.16)
    for note in notes:
        m.add(at, pad_note(note, 3.5, 0.5), 0.10)
    m.add(at, bell(84), 0.32)
    if boom_gain:
        m.add(at, boom(), boom_gain)


def score_a(path):
    secs = 990 / FPS
    m = Mix(secs)
    bed(m, secs, CHORDS)
    m.add(0, boom(), 0.25)
    m.add(0, bell(76), 0.35)
    m.add(t_of(50), bell(83), 0.15)
    arp(m, t_of(215), t_of(870), CHORDS, gain=0.09)
    typing(m, 136, 167)
    m.add(t_of(186), bell(88), 0.12)
    for i in range(7):
        m.add(
            t_of(229 + i * 4),
            pluck(72 + [0, 2, 4, 7, 9, 12, 14][i], decay=0.6),
            0.16,
            pan=-0.6 + i * 0.2,
        )
    for f in range(335, 680, 15):
        m.add(t_of(f), kick(), 0.32)
    for f in (120, 215, 335, 410, 485, 560, 680, 780):
        m.add(t_of(f) - 0.45, whoosh(0.5), 0.10)
    m.add(t_of(434), boom(), 0.35)
    m.add(t_of(710), bell(86), 0.2)
    resolve(m, t_of(880))
    finish(m, path, secs)


def score_b(path):
    secs = 960 / FPS
    m = Mix(secs)
    bed(m, secs, CHORDS, gain=0.08, bright=0.15)
    arp(m, t_of(225), t_of(840), CHORDS, gain=0.07, step=BEAT, octave=24)
    m.add(0, boom(), 0.2)
    m.add(t_of(4), bell(79), 0.25)
    typing(m, 132, 179)
    m.add(t_of(202), bell(84), 0.2)
    for f in (56, 100, 225, 366, 510, 622):
        m.add(t_of(f) - 0.3, whoosh(0.7), 0.12)
    for k in range(4):
        m.add(t_of(225 + k * 32), tick(0.5, 3000 + k * 400), 0.25)
    m.add(t_of(392), bell(86), 0.2)
    resolve(m, t_of(848))
    finish(m, path, secs)


def score_c(path):
    secs = 982 / FPS
    m = Mix(secs)
    bed(m, secs, DARK, gain=0.11, bright=0.1)
    m.add(0, boom(), 0.5)
    m.add(t_of(62), whoosh(1.0, rise=False), 0.12)
    m.add(t_of(80), bell(81), 0.22)
    for i in range(8):
        m.add(
            t_of(100 + i * 2),
            pluck(69 + [0, 3, 5, 7, 10, 12, 15, 17][i], decay=0.5),
            0.12,
            pan=-0.7 + i * 0.2,
        )
    for k in range(21):
        f = 210 + k * 6
        m.add(
            t_of(f), tick(0.6, 2500 + (k % 4) * 500), 0.22, pan=rng.uniform(-0.6, 0.6)
        )
        if k % 4 == 0:
            m.add(t_of(f), kick(), 0.28)
    for i in range(7):
        m.add(
            t_of(352 + i * 5), pluck(74 + [0, 2, 5, 7, 9, 12, 14][i], decay=0.7), 0.12
        )
    for f in (452, 602, 702):
        m.add(t_of(f) - 0.5, whoosh(0.6), 0.14)
    for i in range(5):
        m.add(t_of(478 + i * 5), pluck(62 + [12, 9, 7, 5, 2][i], decay=0.8), 0.14)
    m.add(t_of(632), bell(86), 0.2)
    for i in range(6):
        m.add(t_of(762 + i * 5), tick(0.5, 5000), 0.2)
    resolve(m, t_of(840), notes=(50, 57, 62, 65, 69), boom_gain=0.45)
    finish(m, path, secs)


def score_final(path):
    """B's cues to the tournament, C's inside it, B's again after: see src/final/Final.tsx."""
    AGENTS, DARK_F, NET, BOARD, CHECK, LIGHT, APP, END, TOTAL = (
        225,
        352,
        370,
        722,
        872,
        990,
        998,
        1390,
        1515,
    )
    secs = TOTAL / FPS
    m = Mix(secs)
    bed(m, t_of(DARK_F) + 1.0, CHORDS, gain=0.08, bright=0.15)
    bed(m, t_of(LIGHT) + 1.0, DARK, gain=0.11, bright=0.1, start=t_of(NET) - 0.5)
    bed(m, secs, CHORDS, gain=0.08, bright=0.15, start=t_of(LIGHT))
    # B: arrival, the goal typed, the agents.
    m.add(0, boom(), 0.2)
    m.add(t_of(4), bell(79), 0.25)
    for f in (56, 100, AGENTS):
        m.add(t_of(f) - 0.3, whoosh(0.7), 0.12)
    typing(m, 132, 179)
    m.add(t_of(202), bell(84), 0.2)
    arp(m, t_of(AGENTS), t_of(DARK_F), CHORDS, gain=0.07, step=BEAT, octave=24)
    for k in range(4):
        m.add(t_of(AGENTS + k * 32), tick(0.5, 3000 + k * 400), 0.25)
    # Into the dark: C's tournament.
    m.add(t_of(DARK_F) - 0.6, whoosh(0.9), 0.16)
    m.add(t_of(NET), boom(), 0.45)
    for i in range(9):
        m.add(
            t_of(NET + i * 2),
            pluck(69 + [0, 3, 5, 7, 10, 12, 15, 17, 19][i], decay=0.5),
            0.12,
            pan=-0.7 + i * 0.17,
        )
    for k in range(21):
        f = NET + 110 + k * 6
        m.add(
            t_of(f), tick(0.6, 2500 + (k % 4) * 500), 0.22, pan=rng.uniform(-0.6, 0.6)
        )
        if k % 4 == 0:
            m.add(t_of(f), kick(), 0.28)
    for i in range(6):
        m.add(
            t_of(NET + 242 + 10 + i * 5),
            pluck(74 + [0, 2, 5, 7, 9, 12][i], decay=0.7),
            0.12,
        )
    m.add(t_of(BOARD) - 0.5, whoosh(0.6), 0.14)
    for i in range(5):
        m.add(
            t_of(BOARD + 26 + i * 5), pluck(62 + [12, 9, 7, 5, 2][i], decay=0.8), 0.14
        )
    m.add(t_of(CHECK) - 0.5, whoosh(0.6), 0.14)
    for i in range(6):
        m.add(t_of(CHECK + 60 + i * 5), tick(0.5, 5000), 0.2)
    # Back to the light: the real app, then the end card.
    m.add(t_of(LIGHT) - 0.6, whoosh(0.9), 0.16)
    m.add(t_of(APP), bell(81), 0.25)
    m.add(t_of(APP + 32), bell(86), 0.2)
    arp(m, t_of(APP), t_of(END), CHORDS, gain=0.07, step=BEAT, octave=24)
    for f in (APP + 150, APP + 262):
        m.add(t_of(f) - 0.3, whoosh(0.7), 0.12)
    resolve(m, t_of(END + 8))
    finish(m, path, secs)


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "out")
    out.mkdir(exist_ok=True)
    score_a(out / "a.wav")
    score_b(out / "b.wav")
    score_c(out / "c.wav")
    score_final(out / "final.wav")
    print("ok")
