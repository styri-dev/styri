# A real Nav2 stack (planner, controller, behavior tree) on a TurtleBot 3, with
# Nav2's loopback simulator in place of Gazebo's physics, so it runs on a laptop.
FROM ros:jazzy-ros-base
RUN apt-get update \
 && apt-get install -y --no-install-recommends ros-jazzy-navigation2 ros-jazzy-nav2-bringup \
      ros-jazzy-nav2-loopback-sim ros-jazzy-nav2-minimal-tb3-sim \
 && rm -rf /var/lib/apt/lists/*
COPY start.sh /start.sh
ENV FASTDDS_BUILTIN_TRANSPORTS=UDPv4 ROS_LOG_DIR=/tmp/ros-logs
ENTRYPOINT ["/ros_entrypoint.sh"]
CMD ["bash", "/start.sh"]
