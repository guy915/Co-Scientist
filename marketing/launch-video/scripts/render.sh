#!/bin/sh
# Renders every preview at full 1080p, synthesizes the scores, and muxes them
# loudness-normalized to -16 LUFS (YouTube's playback reference).
# Usage: scripts/render.sh [scale]   -> previews/<id>.mp4
set -e
cd "$(dirname "$0")/.."
scale=${1:-1}
mkdir -p out previews
uv run -q --with numpy python scripts/score.py out
for pair in "A-Expressive:a" "B-Glide:b" "C-Signal:c"; do
  id=${pair%%:*}; s=${pair##*:}
  npx remotion render src/index.ts "$id" "out/$s-video.mp4" --scale="$scale" --concurrency=8 --log=error
  ffmpeg -v error -y -i "out/$s-video.mp4" -i "out/$s.wav" \
    -af "loudnorm=I=-16:TP=-1.5:LRA=11" -c:v copy -c:a aac -b:a 256k -ar 48000 -shortest \
    -movflags +faststart "previews/Open-Co-Scientist-$id.mp4"
  echo "previews/Open-Co-Scientist-$id.mp4"
done
# Intermediates are reproducible from source; keep only the deliverables.
rm -rf out
