#!/usr/bin/env bash
# Run one suite against the running demo, from a clean state (vehicles back at their
# start nodes, nothing paused, no task running), so what ran before can't change its result:  e2e/mixed-fleet/run.sh accept.py [compose file ...]
# Extra environment for the suite goes in SUITE_ENV, like "EXPECT_NO_INTERNET=1".
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
suite=$1
shift
cd "$here/../../examples/mixed-fleet"
files=(-f compose.yaml)
for f in "$@"; do files+=(-f "$f"); done
exec_py() { docker compose "${files[@]}" exec -T styri /ros_entrypoint.sh python3 - < "$here/$1"; }
docker compose "${files[@]}" restart -t 1 agv-07 agv-08 >/dev/null  # back at their start nodes
exec_py clean.py
args=()
for pair in ${SUITE_ENV:-}; do args+=(-e "$pair"); done
docker compose "${files[@]}" exec -T ${args[@]+"${args[@]}"} styri /ros_entrypoint.sh python3 - < "$here/$suite"
