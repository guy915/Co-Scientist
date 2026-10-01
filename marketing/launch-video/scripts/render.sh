#!/bin/sh
# Renders the launch film and the three direction previews at 1080p.
# Usage: scripts/render.sh [scale]   -> previews/Open-Co-Scientist-*.mp4
#
# Launch: Remotion mixes the soundtrack and the effects losslessly (PCM), then
# one static gain brings the mix to -14.25 LUFS, near YouTube's -14 reference, so
# the music plays at least as loud as in the trailer it comes from (-16.2 LUFS).
# The music track itself sits 0.25 dB under unity (Launch.tsx); the two are set
# together, so moving the music leaves the effects where they were.
# Not loudnorm: its dynamic mode rides the gain and smears the effects'
# transients, which is the crispness this mix is built for. The effects-only
# cut gets the same gain, so it plays the effects at their level in the mix.
# A peak limiter at -2 dB (true peak about -1 dB after AAC) catches the few
# hits that land on the music's loudest frames; it touches nothing else.
set -e
cd "$(dirname "$0")/.."
[ -f public/audio/soundtrack.wav ] || { echo "No soundtrack: run scripts/fetch_soundtrack.sh first." >&2; exit 1; }
scale=${1:-1}
mkdir -p out previews
uv run -q --with numpy --with scipy python scripts/sfx.py
render() { npx remotion render src/index.ts "$@" --concurrency=8 --log=error; }

# The master: lossless PNG frames and a low CRF, since the big pastel gradients
# band visibly at the config's JPEG frames and ~2 Mbps.
render Launch out/launch.mkv --codec=h264-mkv --audio-codec=pcm-16 --scale="$scale" --image-format=png --crf=10 --x264-preset=slow
render Launch out/sfx.mkv --codec=h264-mkv --audio-codec=pcm-16 --scale=0.25 --props='{"stem":"sfx"}'
lufs=$(ffmpeg -hide_banner -nostats -i out/launch.mkv -af ebur128 -f null - 2>&1 | awk '$1 == "I:" {i = $2} END {print i}')
gain=$(echo "-14.25 - ($lufs)" | bc -l)
mux() { # $1 = audio source, $2 = output
  ffmpeg -v error -y -i out/launch.mkv -i "$1" -map 0:v -map 1:a -af "volume=${gain}dB,alimiter=limit=0.794:attack=1:release=40:level=disabled" \
    -c:v copy -c:a aac -b:a 256k -ar 48000 -movflags +faststart "$2"
  echo "$2"
}
mux out/launch.mkv previews/Open-Co-Scientist-Launch.mp4
mux out/sfx.mkv previews/Open-Co-Scientist-Launch-effects-only.mp4

uv run -q --with numpy python scripts/score.py out
for pair in "A-Expressive:a" "B-Glide:b" "C-Signal:c"; do
  id=${pair%%:*}; s=${pair##*:}
  render "$id" "out/$s-video.mp4" --scale="$scale"
  ffmpeg -v error -y -i "out/$s-video.mp4" -i "out/$s.wav" \
    -af "loudnorm=I=-16:TP=-1.5:LRA=11" -c:v copy -c:a aac -b:a 256k -ar 48000 -shortest \
    -movflags +faststart "previews/Open-Co-Scientist-$id.mp4"
  echo "previews/Open-Co-Scientist-$id.mp4"
done
# Intermediates are reproducible from source; keep only the deliverables.
rm -rf out
