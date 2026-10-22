# Troubleshooting

## "No robot topics found"

The bridge is running but hasn't seen any of the topics it maps (by default
`/battery_state` and `/diagnostics`). Most first installs fail on one of these
three.

1. **`ROS_DOMAIN_ID`.** Styri only sees robots on the same domain. Check the
   robot (`echo $ROS_DOMAIN_ID`) and pass the same value:
   `docker run -e ROS_DOMAIN_ID=7 --rm --network host ghcr.io/styri-dev/styri-core:v0.2.1`
2. **`--network host`.** DDS discovery uses UDP multicast. Without host
   networking the container can't see the robot's nodes. On macOS and
   Windows, Docker (Docker Desktop, Colima, OrbStack) runs containers in a VM
   behind the computer's own network, so `--network host` doesn't reach your
   LAN either. For a robot on another machine, run Styri on Linux: the robot
   itself, a Linux box on the same network, or a Linux VM with bridged
   networking (for example UTM's "Bridged (Advanced)" mode).
3. **Topic names.** Without a mapping file Styri looks for `/battery_state` and
   `/diagnostics`. If your robot uses other names
   (`ros2 topic list | grep -E "battery|diag"`), map them in a `styri.yaml`
   ([MAPPING.md](MAPPING.md)) and test it with `styri check`.

## "Mapped values aren't coming through"

The Overview banner and the Configuration tab say which mapping and why:

- **Not found:** the topic isn't on the network. Check the name and the
  namespace (relative names get `robot.namespace` in front); the close matches
  listed are topics Styri can see.
- **Can't read:** the topic is there but the field path doesn't fit its
  message. The message lists the fields it does have; the Topics tab shows the
  whole latest message.
- **Waiting:** on the network, but nothing published yet.
- **Configuration file not used:** the file has a mistake, so none of it
  applies. The Configuration tab and `styri check` list every problem with the
  key it's in.

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

## Battery voltage

**The voltage dropped but Styri still says OK.** That's the default: Styri
shows the pack voltage but only judges the reported charge (warning below
25 %). A pack can sag under load, or age, and still report plenty of charge.
To be warned about that, set the lowest voltage you consider safe for your
pack:

```bash
docker run -e STYRI_MIN_VOLTAGE=23.0 --rm --network host ghcr.io/styri-dev/styri-core:v0.2.1
```

Below that, the Voltage tile turns amber, the status shows "Battery voltage
low", and the Activity log records "Voltage below 23.0 V". The warning
clears once the voltage is 0.2 V above the threshold, so it doesn't flicker
on and off at the limit.

**A low-voltage warning won't go away.** Check the robot's actual pack voltage
(`ros2 topic echo /battery_state --field voltage`). If it's normal for your
pack and still below the threshold, the threshold is set too high for it:
lower `STYRI_MIN_VOLTAGE`, or unset it.

## A topic says "not readable"

Its message type isn't installed in the image (common for a robot's own
custom messages). Styri still lists it and counts its rate; it just can't show
the contents.

## The panel says "Lost connection to bridge"

The browser can't reach port 8080 on the machine running Styri. Check that the
container is running (`docker ps`) and that nothing else uses port 8080
(`STYRI_PORT` changes it).
