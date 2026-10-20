# Simulated robot for testing Styri without hardware. Not part of the
# product image. ROS_DISTRO=humble builds it on Humble, to test a Jazzy
# Styri against an older robot.
ARG ROS_DISTRO=jazzy
FROM ros:${ROS_DISTRO}-ros-base
ARG ROS_DISTRO
# Cyclone DDS too, so tests can run the robot on either RMW.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ros-${ROS_DISTRO}-rmw-cyclonedds-cpp \
 && rm -rf /var/lib/apt/lists/*
COPY styri_sim /opt/sim/styri_sim
WORKDIR /opt/sim
ENV PYTHONUNBUFFERED=1 ROS_LOG_DIR=/tmp/ros-logs HOME=/tmp FASTDDS_BUILTIN_TRANSPORTS=UDPv4
USER 10002
ENTRYPOINT ["/ros_entrypoint.sh"]
CMD ["python3", "-m", "styri_sim"]
