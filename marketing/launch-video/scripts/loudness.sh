# Sourced by render.sh and render_master.sh, so both masters get the same mix.
# loudness_filter <file>: the ffmpeg audio filter that brings <file>'s mix to
# -14.25 LUFS with one static gain, then a -2 dB peak limiter (why: render.sh).
loudness_filter() {
  lufs=$(ffmpeg -hide_banner -nostats -i "$1" -af ebur128 -f null - 2>&1 | awk '$1 == "I:" {i = $2} END {print i}')
  echo "volume=$(echo "-14.25 - ($lufs)" | bc -l)dB,alimiter=limit=0.794:attack=1:release=40:level=disabled"
}
