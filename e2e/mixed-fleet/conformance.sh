#!/usr/bin/env bash
# Record what's on the broker during the acceptance run, and check it with
# vda5050-testkit. Run from examples/mixed-fleet, with the testkit image built as CI
# builds it (pinned commit, then patch_testkit_schemas.py, then docker build).
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
out="$PWD/out/conformance"
mkdir -p "$out" && chmod 777 "$out"
docker compose up -d
trap 'docker compose down -t 2 -v >/dev/null 2>&1' EXIT
# In Styri's network namespace, for the anonymous localhost listener.
docker run --rm -d --name testkit --network "container:$(docker compose ps -q styri)" -v "$out:/out" vda5050-testkit \
  record -b tcp://127.0.0.1:1883 --duration 45 -o /out/trace.jsonl >/dev/null
sleep 3
docker compose exec -T styri /ros_entrypoint.sh python3 - < "$here/accept.py" | tail -1
docker wait testkit >/dev/null
docker run --rm -v "$out:/out" vda5050-testkit check --report /out/report.json --format json /out/trace.jsonl > /dev/null
code=$?
docker run --rm -v "$out:/out" vda5050-testkit check /out/trace.jsonl | tee "$out/report.txt"
exit $code
