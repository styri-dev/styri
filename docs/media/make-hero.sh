#!/usr/bin/env bash
# Re-record docs/media/hero.gif: the terminal (VHS) and the panel (Playwright)
# are recorded at the same time against real containers, then stacked and
# turned into a looping GIF.
#
# Needs: docker, vhs, ffmpeg, node, the JetBrains Mono font, port 8080 free and
# nothing else on ROS_DOMAIN_ID 0. Run from the repo root:
#   docs/media/make-hero.sh            the latest v* tag (what the README shows)
#   docs/media/make-hero.sh v0.3.1     a specific, already published release
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
version=${1:-$(git -C "$root" describe --tags --abbrev=0 --match 'v*')}
image="ghcr.io/styri-dev/styri-core:$version"
echo "recording $image"
work=$(mktemp -d)
trap 'docker rm -f styri robot >/dev/null 2>&1 || true; [ -n "${KEEP:-}" ] && echo "kept $work" || rm -rf "$work"' EXIT

docker pull -q "$image" >/dev/null || { echo "$image isn't published yet; wait for the release run" >&2; exit 1; }
docker build -q -t styri-sim "$root/sim" >/dev/null
(cd "$root/e2e" && npm ci --silent >/dev/null)
sed "s|__VERSION__|$version|g" "$root/docs/media/hero-terminal.tape" > "$work/hero-terminal.tape"
cp "$root/docs/media/hero-panel.mjs" "$root/e2e/.hero-panel.mjs"  # resolves @playwright/test from e2e/
cd "$work"
docker rm -f styri robot >/dev/null 2>&1 || true

# The terminal tape writes term.start when it begins; start the panel then.
(vhs hero-terminal.tape >vhs.log 2>&1; touch vhs.done) &
for _ in $(seq 1 240); do [ -f term.start ] && break; sleep 0.25; done
node "$root/e2e/.hero-panel.mjs"
while [ ! -f vhs.done ]; do sleep 0.5; done
rm -f "$root/e2e/.hero-panel.mjs"

offset=$(python3 -c "print(round($(cat panel.start) - $(cat term.start), 3))")
ffmpeg -v error -y -i term.mp4 -itsoffset "$offset" -i video/*.webm -filter_complex \
  "[0:v]fps=20,scale=560:620,setsar=1[t];[1:v]fps=20,scale=1000:620,setsar=1[p];[t][p]hstack=inputs=2[v]" \
  -map "[v]" -c:v libx264 -crf 18 -pix_fmt yuv420p both.mp4
# Start once the panel shows "No robot topics found"; end on the warning, held.
# Playwright's video begins a little after the page is created, hence -0.6 s;
# then skip forward past any blank (white) frame before the panel loads.
start=$(python3 -c "print(round($(cat panel.loaded) - $(cat term.start) - 0.6, 2))")
for _ in $(seq 1 12); do
  px=$(ffmpeg -v error -ss "$start" -i both.mp4 -vf "crop=200:200:800:200,scale=1:1" -frames:v 1 -f rawvideo -pix_fmt gray - | od -An -tu1 | tr -d ' ')
  [ "$px" -lt 128 ] && break
  start=$(python3 -c "print($start + 0.25)")
done
# End 1.2 s after the warning appears: the first frame where the panel's
# status block has turned amber.
amber() {  # exit 0 if the status block is amber at time $1
  ffmpeg -v error -ss "$1" -i both.mp4 -vf "crop=200:30:640:150,scale=1:1" -frames:v 1 \
    -f rawvideo -pix_fmt rgb24 - | od -An -tu1 | awk '{ exit !($1 > 200 && $2 > 140 && $3 < 110) }'
}
dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 both.mp4)
warn="" t=$(python3 -c "print($start + 4)")
while python3 -c "import sys; sys.exit($t >= $dur - 0.2)"; do
  if amber "$t"; then warn=$t; break; fi
  t=$(python3 -c "print(round($t + 0.2, 2))")
done
[ -n "$warn" ] || { echo "never saw the warning; the robot fault did not land" >&2; exit 1; }
length=$(python3 -c "print(round($warn + 1.2 - $start, 2))")
echo "loop: starts at $start s, warning at $warn s, $length s long"
ffmpeg -v error -y -ss "$start" -t "$length" -i both.mp4 -vf \
  "fps=12,scale=1200:-1:flags=lanczos,tpad=stop_mode=clone:stop_duration=1.2,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" \
  -loop 0 "$root/docs/media/hero.gif"
ls -lh "$root/docs/media/hero.gif"
