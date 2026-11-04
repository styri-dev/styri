#!/usr/bin/env bash
# Nav2 needs to be told where the robot is before it will take a goal.
set -e
cp /opt/ros/jazzy/share/nav2_bringup/maps/tb3_sandbox.* /site-map/ 2>/dev/null || true
ros2 launch nav2_bringup tb3_loopback_simulation.launch.py use_rviz:=False &
# It only takes the pose once the robot's own transforms exist, so keep telling it
# until Nav2 is up. It's safe to repeat: nothing has moved yet.
until ros2 lifecycle get /bt_navigator 2>/dev/null | grep -q '^active'; do
  ros2 topic pub --once -w 1 --qos-reliability reliable /initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
    '{header: {frame_id: map}, pose: {pose: {position: {x: -2.0, y: -0.5}, orientation: {w: 1.0}}}}' > /dev/null
  sleep 2
done
echo "Nav2 is up"
wait
