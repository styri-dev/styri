# Troubleshooting

## "No robot topics found"

The bridge is running but hasn't seen any of the topics it maps (by default
`/battery_state` and `/diagnostics`). Most first installs fail on one of these
three.

1. **`ROS_DOMAIN_ID`.** Styri only sees robots on the same domain. Check the
   robot (`echo $ROS_DOMAIN_ID`) and pass the same value:
   `docker run -e ROS_DOMAIN_ID=7 --rm --network host ghcr.io/styri-dev/styri-core:v2.0.0`
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
docker run -e STYRI_MIN_VOLTAGE=23.0 --rm --network host ghcr.io/styri-dev/styri-core:v2.0.0
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
the contents. `styri check` names the missing package. To read it, add the
robot's message packages as an overlay:
[MAPPING.md, "Your own message types"](MAPPING.md#your-own-message-types).

## VDA 5050 vehicles

Run `styri check`: it lists the broker, each vehicle, and anything on the broker
that isn't in `styri.yaml`.

- **Broker not reachable.** The bundled broker runs with the panel, so start Styri
  first. If the panel says port 1883 may be in use, the machine already runs a
  broker: stop it, point `vda.broker.url` at it, or change `vda.broker.port`.
- **Vehicle can't connect.** It needs the LAN address in `vda.broker.bind`, and
  its `username` with the password from `password_env`. Without `bind`, the broker
  is on localhost only.
- **"Seen on broker, not configured".** Its manufacturer and serial number don't
  match an entry. Copy them from that line, exactly.
- **Invalid messages.** Styri checks every message against the official schemas,
  warns on that robot and carries on. The log says which field is wrong.
- **No factsheet.** Styri asks for one when control is on. In view-only it shows
  only a retained one.
- **Order refused.** The first node of an order is where the vehicle is, so
  its `lastNodeId` or position must be on the graph, and its `mapId` must match.
- **"This robot is paused. Press Resume first."** An Operator stop leaves a VDA
  5050 vehicle paused. Styri never unpauses it by itself.
- **"Robot is X m from the nearest node."** It's off the graph, and further from a
  node than `site.max_off_graph` (2 m by default). Move it onto the route with its own
  controls: Styri won't send it across floor the graph doesn't cover.
- **"Held, cancel pending".** After an Operator stop, some vehicles keep the
  cancel open until they're unpaused. The vehicle is stopped. Press Resume to
  clear it, once it's safe for the vehicle to move.

## The map editor

- **No Edit graph button.** Log in, and set `site.graph` in `styri.yaml`.
- **"Can't write …".** Saving needs the graph's folder writable by Styri (uid
  10001). Mount the folder, not `:ro`, and not just the file.

## Control

- **No drawer.** Control is off. Set `control.enabled: true` or `STYRI_CONTROL=1`.
- **Forgot the admin password.** Delete `admin.hash` next to the audit database
  and set a new one, or set `STYRI_ADMIN_PASSWORD`, which takes priority.
- **"Log in to control robots" after a restart.** Sessions don't survive a
  restart, on purpose.
- **"Stop already sent."** Without a login, a robot takes one stop every 2 seconds.
  The first one went through.
- **Too many attempts.** Five wrong passwords lock that address out for a minute.
- **Buttons missing.** The panel shows only what a robot supports: a ROS 2 robot
  needs `cmd_vel` for the joystick, `nav2_action` for waypoints and Cancel, and
  `pause_topic` for Pause. A VDA 5050 factsheet can rule actions out.
- **Joystick or waypoints off.** The robot's data is STALE. Operator stop stays.
- **Nav2 isn't answering.** `styri check` shows whether the action server is up.

## The panel says "Lost connection to bridge"

The browser can't reach port 8080 on the machine running Styri. Check that the
container is running (`docker ps`) and that nothing else uses port 8080
(`STYRI_PORT` changes it).
