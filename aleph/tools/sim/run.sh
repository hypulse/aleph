#!/bin/sh
# Run MPD, alephd (simulated hardware) and aleph-shell inside the aleph-dev container.
# usage: run.sh [script] [screenshot-dir]
set -e
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=${ALEPH_SIM_DIR:-/tmp/aleph-sim}
SCRIPT=$1
SHOTS=${2:-/out}

mkdir -p "$WORK/share" "$WORK/config" "$WORK/cache" "$SHOTS"
[ -d "$WORK/music" ] || python3 "$ROOT/tools/gen_test_music.py" "$WORK"

ln -sfn /usr/share/fonts/pretendard "$WORK/share/fonts"
ln -sfn "$ROOT/shell/assets/icons" "$WORK/share/icons"
for f in "$ROOT"/shell/assets/*.png; do ln -sf "$f" "$WORK/share/"; done
cp -rn "$ROOT/system/mpv" "$WORK/share/" 2>/dev/null || true

cat >"$WORK/mpd.conf" <<EOF
music_directory "$WORK/music"
playlist_directory "$WORK/playlists"
db_file "$WORK/mpd.db"
state_file "$WORK/mpd.state"
bind_to_address "$WORK/mpd.sock"
auto_update "yes"
audio_output {
    type "null"
    name "null"
    mixer_type "none"
}
EOF
pkill -x mpd 2>/dev/null || true
mpd "$WORK/mpd.conf"

pkill -f "alephd --sim" 2>/dev/null || true
python3 "$ROOT/daemon/alephd" --sim --socket "$WORK/alephd.sock" --config "$WORK/config" \
    --cache "$WORK/cache" --music "$WORK/music" --videos "$WORK/videos" --data "$WORK/share" \
    --mpd "$WORK/mpd.sock" >"$WORK/alephd.log" 2>&1 &
DAEMON=$!

make -s -C "$ROOT/shell"
cd "$SHOTS"
if [ -n "$SCRIPT" ]; then
    SDL_VIDEODRIVER=offscreen "$ROOT/shell/aleph-shell" --data "$WORK/share" --socket "$WORK/alephd.sock" \
        --script "$SCRIPT"
fi
kill $DAEMON 2>/dev/null || true
pkill -x mpd 2>/dev/null || true
