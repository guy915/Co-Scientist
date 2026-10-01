#!/bin/sh
# Tiles specific frames of a render (3 per row). Usage: frames.sh in.mp4 out.jpg f1 f2 ...
in=$1; out=$2; shift 2
sel=$(printf "eq(n\\\\,%s)+" "$@" | sed 's/+$//')
ffmpeg -v error -y -i "$in" -vf "select='$sel',scale=960:-2,tile=3x$(( ($# + 2) / 3 ))" -frames:v 1 -vsync 0 "$out"
