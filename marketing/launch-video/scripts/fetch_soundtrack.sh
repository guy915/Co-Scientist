#!/bin/sh
# Fetches the launch film's soundtrack: the music of Google's "Introducing
# Gemini Omni" trailer (no voiceover). It is Google's recording, not ours, so
# it is pulled at build time into the gitignored public/audio/ and never
# committed. Needs yt-dlp and ffmpeg.
set -e
cd "$(dirname "$0")/.."
mkdir -p public/audio
tmp=$(mktemp -d)
yt-dlp -q --no-warnings -f 'ba[ext=m4a]/ba' -o "$tmp/track.%(ext)s" 'https://www.youtube.com/watch?v=KUyRq7szZsM'
ffmpeg -v error -y -i "$tmp"/track.* -ac 2 -ar 48000 public/audio/soundtrack.wav
rm -rf "$tmp"
echo public/audio/soundtrack.wav
