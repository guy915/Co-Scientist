"""Renders the upload master: 4K, 60 fps, motion-blurred, for YouTube.

Motion blur: each 60 fps frame averages several renders spread forward across
a 180-degree shutter (src/launch/Master.tsx renders the film at any time).
Forward only, so a frame on a beat cut holds nothing from before the cut and
the cuts stay hard.

Most of the film barely moves between frames (held type, slow backdrop drift,
a still end card), so each frame takes only the samples its motion needs: a
480x270 render, which also carries the mix, measures how much of the busiest
30 px tile changes over each film frame, and that picks 1, 2, 4 or 8 samples.
Uniform 8 would render ~26k 4K frames; this renders about half.

ffmpeg's tmix averages 8 slots per frame (a frame with fewer samples repeats
each one evenly), summing in integers and rounding once, so the pastel
gradients don't band the way 8-bit in-browser blending would.

The film renders in chunks of 240 frames (eight closed GOPs): each chunk
encodes while the next renders, and the chunks join with a stream copy. On a
16 GB machine the renderer's browser tabs run out of memory before cores, so
raising --concurrency past what fits in RAM makes it slower, not faster.

The encode is for YouTube: H.264 High at CRF 6 with adaptive quantization
tuned for flat gradients (~30-50 Mbps on this film, near YouTube's 4K60
guidance of 53-68 Mbps; flat pastel graphics need fewer bits than footage for
the same quality), closed 30-frame GOPs (half the frame rate), BT.709 tagged
so the pastels keep their colour through YouTube's re-encode, and AAC at
384 kbps carrying the same mix as render.sh.

Usage: uv run --with numpy python scripts/render_master.py [options]
  -> previews/Open-Co-Scientist-Launch-4K60.mp4
"""

import argparse
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "out" / "master"
FILM_FPS, FPS = 30, 60
FILM_FRAMES = 1624  # LAUNCH_FRAMES
SHUTTER = 0.5  # of a 60 fps frame: 180 degrees
SLOTS = 8  # the most samples a frame takes; tmix averages this many
CHUNK = 240  # 60 fps frames per chunk: eight closed 30-frame GOPs

# Samples by the share of the busiest 30 px tile (at 480x270) that changes over
# one film frame. An edge moving d px there changes d/30 of its tile and moves
# 2d px at 4K across the shutter; samples read as a smooth smear while they
# sit about 2 px apart, so 2 samples cover d <= 2 (6.7%) and 4 cover d <= 4
# (13%). Text has many edges per tile, which only errs towards more samples.
TIERS = [(0.0, 1), (0.05, 2), (0.12, 4)]

COLOUR = "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p"
X264 = [
    "-c:v", "libx264", "-preset", "slow", "-crf", "6", "-profile:v", "high", "-level:v", "5.2",
    "-g", "30", "-bf", "2", "-x264-params", "open-gop=0:aq-mode=3:colorprim=bt709:transfer=bt709:colormatrix=bt709",
    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
]  # fmt: skip


def run(*args: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=ROOT, check=True, **kw)


def remotion(*args: str) -> None:
    run("npx", "remotion", *args, "--log=error")


def motion(video: Path) -> np.ndarray:
    """Per film frame k, the largest share of a tile that changes from k to k+1."""
    raw = run(
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(video),
        "-vf",
        "format=gray",
        "-f",
        "rawvideo",
        "-",
        capture_output=True,
    ).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, 270, 480)
    share = np.zeros(len(frames))
    for k in range(len(frames) - 1):
        changed = np.abs(frames[k + 1].astype(np.int16) - frames[k]) > 24
        share[k] = changed.reshape(9, 30, 16, 30).mean(axis=(1, 3)).max()
    return share


def samples_for(share: float) -> int:
    return next((s for most, s in TIERS if share <= most), SLOTS)


def times_for(frames: range, counts: list[int]) -> list[float]:
    """Film times to render: each 60 fps frame's samples, centred in equal slices of its shutter."""
    return [
        round((n + (i + 0.5) / s * SHUTTER) * FILM_FPS / FPS, 6)
        for n, s in zip(frames, counts)
        for i in range(s)
    ]


def encode(pngs: list[Path], counts: list[int], dest: Path) -> subprocess.Popen:
    """Starts averaging a chunk's samples into its frames; returns the running encode."""
    lines, i = ["ffconcat version 1.0"], 0
    for s in counts:
        lines += [
            f"file '{pngs[i + slot * s // SLOTS]}'\nduration {1 / (FPS * SLOTS)}"
            for slot in range(SLOTS)
        ]
        i += s
    listing = dest.with_suffix(".txt")
    listing.write_text("\n".join(lines) + "\n")
    blend = f"tmix=frames={SLOTS},select='eq(mod(n\\,{SLOTS})\\,{SLOTS - 1})',settb=1/{FPS},setpts=N,fps={FPS},{COLOUR}"
    return subprocess.Popen(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-vf",
            blend,
            *X264,
            # Exact 1/60 timestamps, kept as they are: -r resampled them and duplicated a frame per chunk.
            "-fps_mode",
            "passthrough",
            str(dest),
        ],
        cwd=ROOT,
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Renders the upload master.")
    p.add_argument("--scale", type=float, default=2, help="of 1080p (2 = 4K)")
    p.add_argument("--concurrency", type=int, default=4, help="browser tabs per render")
    p.add_argument(
        "--samples",
        type=int,
        help=f"every frame takes this many (1-{SLOTS}), skipping the motion plan",
    )
    p.add_argument("--start", type=float, default=0, help="seconds")
    p.add_argument("--end", type=float, default=FILM_FRAMES / FILM_FPS, help="seconds")
    p.add_argument(
        "-o",
        "--out",
        type=Path,
        default=ROOT / "previews" / "Open-Co-Scientist-Launch-4K60.mp4",
    )
    a = p.parse_args()
    if not (ROOT / "public" / "audio" / "soundtrack.wav").exists():
        raise SystemExit("No soundtrack: run scripts/fetch_soundtrack.sh first.")

    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    run(
        "uv",
        "run",
        "-q",
        "--with",
        "numpy",
        "--with",
        "scipy",
        "python",
        "scripts/sfx.py",
    )
    remotion("bundle", "src/index.ts", f"--out-dir={WORK / 'bundle'}")
    # The mix, losslessly, with a 480x270 picture for the motion plan (the config's CRF rules out --codec=wav).
    mix = WORK / "mix.mkv"
    remotion(
        "render",
        str(WORK / "bundle"),
        "Launch",
        str(mix),
        "--codec=h264-mkv",
        "--audio-codec=pcm-16",
        "--scale=0.25",
        "--image-format=png",
    )

    frames = range(round(a.start * FPS), round(a.end * FPS))
    if a.samples:
        counts = [a.samples] * len(frames)
    else:
        share = motion(mix)
        counts = [samples_for(share[n * FILM_FPS // FPS]) for n in frames]
    times = times_for(frames, counts)
    props = WORK / "times.json"
    props.write_text(json.dumps({"times": times}))
    print(f"{len(times)} renders for {len(frames)} frames", flush=True)

    chunks, pending, first = [], None, 0
    for c in range(0, len(frames), CHUNK):
        n = sum(counts[c : c + CHUNK])
        seq = WORK / f"seq-{c}"
        remotion("render", str(WORK / "bundle"), "Launch-Master", str(seq), "--sequence", "--image-format=png",
                 f"--scale={a.scale}", f"--props={props}", f"--frames={first}-{first + n - 1}", f"--concurrency={a.concurrency}")  # fmt: skip
        if pending:
            if pending[0].wait():
                raise SystemExit("encode failed")
            shutil.rmtree(pending[1])
        chunks.append(WORK / f"chunk-{c}.mp4")
        pending = (
            encode(sorted(seq.glob("*.png")), counts[c : c + CHUNK], chunks[-1]),
            seq,
        )
        first += n
        print(
            f"rendered {min(c + CHUNK, len(frames))}/{len(frames)} frames", flush=True
        )
    if pending and pending[0].wait():
        raise SystemExit("encode failed")

    (WORK / "chunks.txt").write_text("".join(f"file '{c}'\n" for c in chunks))
    af = run(
        "sh",
        "-c",
        '. scripts/loudness.sh && loudness_filter "$1"',
        "_",
        str(mix),
        capture_output=True,
        text=True,
    ).stdout.strip()
    run("ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(WORK / "chunks.txt"),
        "-ss", str(a.start), "-t", str(len(frames) / FPS), "-i", str(mix), "-map", "0:v", "-map", "1:a",
        "-c:v", "copy", "-af", af, "-c:a", "aac", "-b:a", "384k", "-ar", "48000", "-movflags", "+faststart", str(a.out))  # fmt: skip
    shutil.rmtree(WORK)
    print(a.out)


if __name__ == "__main__":
    main()
