#!/bin/sh
# Contact sheet of a render: N evenly spaced frames, 6 per row. Usage: sheet.sh in.mp4 out.jpg [frames]
n=${3:-24}
d=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$1")
ffmpeg -v error -y -i "$1" -vf "fps=$n/$d,scale=480:-2,tile=6x$(( (n + 5) / 6 ))" -frames:v 1 "$2"
