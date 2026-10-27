#!/bin/bash
# Styri's /ros_entrypoint.sh: the ROS 2 environment, then any message
# overlays, then the command. An overlay is a colcon install folder holding a
# robot's own message packages, built for ROS 2 Jazzy, mounted read-only at
# /opt/styri/overlay (or several, at /opt/styri/overlay/<name>). See
# docs/MAPPING.md, "Your own message types".
set -e
source "/opt/ros/$ROS_DISTRO/setup.bash" --

STYRI_OVERLAYS=""
root="${STYRI_OVERLAY_DIR:-/opt/styri/overlay}"
for dir in "$root" "$root"/*/; do
  dir="${dir%/}"
  [ -f "$dir/local_setup.bash" ] || continue
  if source "$dir/local_setup.bash" --; then
    STYRI_OVERLAYS="${STYRI_OVERLAYS:+$STYRI_OVERLAYS:}$dir"
  else
    echo "styri: could not load the message overlay in $dir" >&2
  fi
done
export STYRI_OVERLAYS

exec "$@"
