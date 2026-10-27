# Styri: one image, one port. The bridge serves the operator UI and its live
# data on 8080.
#
#   docker run --rm --network host ghcr.io/styri-dev/styri-core:v0.3.1
#
# ros:jazzy-ros-base is multi-arch (amd64 + arm64/Jetson) and already ships
# rclpy and the standard message packages.

# --- UI: static files, built natively (no need for QEMU) -------------------
FROM --platform=$BUILDPLATFORM node:24-alpine AS ui
WORKDIR /src
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

# --- runtime -----------------------------------------------------------------
FROM ros:jazzy-ros-base
# All dependencies are resolved at build time; the running container never
# reaches the network.
COPY bridge/pyproject.toml bridge/setup.py bridge/setup.cfg bridge/package.xml /opt/styri/bridge/
COPY bridge/resource /opt/styri/bridge/resource
COPY bridge/styri_bridge /opt/styri/bridge/styri_bridge
# Example mapping files: -e STYRI_CONFIG=/opt/styri/presets/turtlebot4.yaml
COPY presets /opt/styri/presets
# Message packages beyond ros-base's standard ones (std, geometry, sensor,
# nav, diagnostic, action, ...), so common robots' topics can be read: Nav2,
# maps, ros2_control and the iRobot Create 3 / TurtleBot 4. A robot's own
# types load as an overlay (/opt/styri/overlay, see ros_entrypoint.sh).
# ros-base has no pip; install it just long enough to add our package.
# Cyclone DDS ships alongside Fast DDS: set RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
# to match a robot that uses it.
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3-pip ros-jazzy-rmw-cyclonedds-cpp \
      ros-jazzy-nav2-msgs ros-jazzy-map-msgs ros-jazzy-control-msgs ros-jazzy-irobot-create-msgs \
 && pip3 install --no-cache-dir --break-system-packages /opt/styri/bridge \
 && apt-get purge -y --auto-remove python3-pip \
 && rm -rf /var/lib/apt/lists/* \
 && . /opt/ros/jazzy/setup.sh \
 && python3 -c "import styri_bridge, websockets, yaml, rosidl_runtime_py, diagnostic_msgs, nav2_msgs, nav_msgs, action_msgs, geometry_msgs, sensor_msgs, std_msgs, map_msgs, control_msgs, irobot_create_msgs" \
 && command -v styri \
 && useradd --system --uid 10001 --home-dir /var/lib/styri --create-home styri
COPY --from=ui /src/dist /opt/styri/ui
# Replaces the base image's: also loads message overlays. Every documented
# `docker exec styri /ros_entrypoint.sh ...` gets them too.
COPY ros_entrypoint.sh /ros_entrypoint.sh

USER 10001
# UDP only: with host networking but no shared /dev/shm, Fast DDS's
# shared-memory transport would discover the robot's nodes and then receive
# nothing.
ENV STYRI_AUDIT_DB=/var/lib/styri/audit.db \
    STYRI_UI_DIR=/opt/styri/ui \
    ROS_LOG_DIR=/tmp/ros-logs \
    FASTDDS_BUILTIN_TRANSPORTS=UDPv4 \
    PYTHONUNBUFFERED=1
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"

# /ros_entrypoint.sh sources the ROS 2 environment before running the command.
ENTRYPOINT ["/ros_entrypoint.sh"]
CMD ["python3", "-m", "styri_bridge"]
