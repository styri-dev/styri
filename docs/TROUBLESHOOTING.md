# Troubleshooting

## "No robot topics found"

The bridge is running but hasn't seen `/battery_state` or `/diagnostics`.
Most first installs fail on one of these three.

1. **`ROS_DOMAIN_ID`.** Styri only sees robots on the same domain. Check the
   robot (`echo $ROS_DOMAIN_ID`) and pass the same value:
   `docker run -e ROS_DOMAIN_ID=7 --rm --network host ghcr.io/styri-dev/styri-core:v0.1.0`
2. **`--network host`.** DDS discovery uses UDP multicast. Without host
   networking the container can't see the robot's nodes. (Docker Desktop on
   macOS and Windows runs containers in a VM, so host networking reaches the
   VM, not your LAN. Use Linux, or Colima/OrbStack with their bridged
   networking, for a robot on another machine.)
3. **Topic names.** Styri looks for `/battery_state` and `/diagnostics`. If your
   robot uses other names (`ros2 topic list | grep -E "battery|diag"`), set
   `STYRI_BATTERY_TOPIC` and `STYRI_DIAGNOSTICS_TOPIC`.

## Topics appear but never get data

- **DDS vendor.** Styri runs Fast DDS by default and also ships Cyclone DDS. Both
  talk to robots on either vendor, but if your site standardises on one, match
  it: `-e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`.
- **Shared memory only.** If the robot's Fast DDS is configured for shared
  memory only, nothing reaches a separate container. Styri uses UDP, which every
  DDS setup supports; allow UDP on the robot.
- **Multicast blocked.** Some Wi-Fi networks and managed switches drop
  multicast. Try a wired connection, or ask for multicast (IGMP) to be allowed
  on the robot's VLAN.
- **Firewall.** DDS uses UDP 7400 and up (by domain). Allow UDP between the
  robot and the machine running Styri.

## A topic says "not readable"

Its message type isn't installed in the image (common for a robot's own
custom messages). Styri still lists it and counts its rate; it just can't show
the contents.

## The panel says "Lost connection to bridge"

The browser can't reach port 8080 on the machine running Styri. Check that the
container is running (`docker ps`) and that nothing else uses port 8080
(`STYRI_PORT` changes it).
