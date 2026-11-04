#!/usr/bin/env bash
# Run the fleet on real Nav2, drive the panel through the story, and record it to
# examples/mixed-fleet/out/mixed-fleet.mp4. Run the acceptance test too.
#
# Needs: docker, node, ffmpeg, and Chrome (PW_CHANNEL=chrome), with port 8080 free.
set -euo pipefail
cd "$(dirname "$0")"
compose() { docker compose -f compose.yaml -f compose.nav2.yaml "$@"; }
trap 'compose down -t 2 -v >/dev/null 2>&1' EXIT

compose down -t 2 -v >/dev/null 2>&1 || true
compose up -d --build
echo "Waiting for Nav2…"
for _ in $(seq 1 90); do
  compose logs amr-01 2>&1 | grep -q "Nav2 is up" && break
  sleep 2
done
compose logs amr-01 2>&1 | grep -q "Nav2 is up" || { echo "Nav2 didn't come up in 3 minutes"; exit 1; }
sleep 6

rm -rf out/frames && mkdir -p out/frames
(cd ../../e2e && OUT="$PWD/../examples/mixed-fleet/out/frames" PW_CHANNEL="${PW_CHANNEL:-chrome}" node mixed-fleet/capture.mjs)
ffmpeg -y -loglevel error -f concat -i out/frames/list.txt -vf "fps=30,format=yuv420p" -c:v libx264 -crf 20 out/mixed-fleet.mp4
rm -rf out/frames
echo "Wrote $PWD/out/mixed-fleet.mp4"
