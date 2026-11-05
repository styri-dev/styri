# Mapping your robot's topics

Styri reads a `sensor_msgs/BatteryState` on `/battery_state` and a
`diagnostic_msgs/DiagnosticArray` on `/diagnostics` out of the box. For any
other robot, describe its topics in one YAML file, `styri.yaml`: which topic
and field is the battery, the voltage, the CPU temperature, the robot's own
status, and up to five more values of your choice. Any message type works:
fields are picked by path. Your robot's own message types work too, loaded
as an overlay ([below](#your-own-message-types)).

## Use a file

Mount it at `/etc/styri/styri.yaml`:

```bash
docker run --rm --network host -v "$PWD/styri.yaml:/etc/styri/styri.yaml:ro" ghcr.io/styri-dev/styri-core:v2.0.0
```

or put it anywhere and point `STYRI_CONFIG` at it. Without a file, the
`STYRI_*` environment variables apply as before
([Configuration](DEVELOPMENT.md#configuration)). Styri reads the file once,
at start: restart it after a change.

Five presets ship in the image, under `/opt/styri/presets/` (and in
[`presets/`](../presets/) here), ready to use as they are or to copy:

| Preset | For |
|---|---|
| `generic-battery-state.yaml` | Any robot with `BatteryState` and `DiagnosticArray`: what Styri does with no file, written out |
| `nav2.yaml` | Any robot running Nav2: navigation status (the latest NavigateToPose goal), battery, speed |
| `turtlebot4.yaml` | TurtleBot 4, real or in the Nav2 / Gazebo simulation, including docked or not |
| `styri-sim.yaml` | The simulated robot in this repo: every kind of mapping |
| `mixed-fleet.yaml` | A ROS 2 robot and a VDA 5050 vehicle on one map: copy it and change the names |

```bash
docker run --rm --network host -e STYRI_CONFIG=/opt/styri/presets/turtlebot4.yaml ghcr.io/styri-dev/styri-core:v2.0.0
```

## Check a file before you deploy it

`styri check` loads the file, listens to the live topics for 5 seconds and
prints PASS or FAIL for every mapping, with close matches for topics it can't
find. It exits 0 when everything passes, 1 when a mapping fails and 2 when the
file itself can't be used. Like the panel, it only listens.

```bash
docker run --rm --network host -v "$PWD/styri.yaml:/etc/styri/styri.yaml:ro" ghcr.io/styri-dev/styri-core:v2.0.0 styri check
```

```
amr-01 (namespace /robot1, domain 0)
  PASS  Battery              /robot1/battery_state · percentage  = 76 %
  FAIL  Status               /robot1/robot_state · data  not on the network. Did you mean /robot1/robot_status?
  FAIL  Speed                /robot1/odom · twist.linear.x  Can't read the value: no field “linear” (it has: twist, covariance).
```

The panel says the same: a banner on the Overview names any mapped value that
isn't coming through, and the **Configuration** tab lists where the mapping
came from, the Styri version and every mapping with its status.

## The file

Every section is optional; anything left out keeps its default.

```yaml
robot:
  name: amr-01                # shown in the header (default: STYRI_ROBOT_NAME, then the host name)
  namespace: /robot1          # relative topic names below get this prefix
  domain_id: 0                # optional; overrides ROS_DOMAIN_ID

stale_after: 5                # seconds before a value counts as stale (default 5)

battery:
  topic: battery_state        # default battery_state (relative, so it gets the namespace)
  percentage: percentage      # field path (default percentage)
  percentage_scale: 100       # multiply to get %: 100 for 0–1, 1 if it already sends 0–100
  voltage: voltage            # field path, or false for no voltage tile
  warn_below: 25              # %
  fault_below: 10
  min_voltage: 23.0           # optional: warn below this many volts, whatever the % says
  stale_after: 5

cpu_temperature:
  topic: diagnostics          # default; a DiagnosticArray: pick the entry and key by name ...
  status_name: cpu            # (case-insensitive, part of the name is enough)
  key: temp
  # field: temperature        # ... or any other topic, by field path
  warn_above: 75              # °C
  fault_above: 85
  host_fallback: false        # true: when the robot's figure is missing, show the Styri machine's own CPU

status:                       # the robot's own status, shown as a tile
  topic: robot_status
  field: data
  warn: [DEGRADED, LOW_POWER] # values that mean WARNING
  fault: [ERROR, STOPPED]     # values that mean FAULT; anything else is shown as it is
  # labels: {0: IDLE, 1: DRIVING, 2: ERROR}  # optional: words for coded values; warn/fault use the words
  # when_empty: IDLE          # optional: shown when the path finds no item (an empty list)
  #                           # or the topic hasn't published anything yet
  # stale_after: false        # for topics that publish only on change: never stale

diagnostics:
  topic: diagnostics          # default; WARN and ERROR entries show on the Overview; false to ignore

fields:                       # up to 5 more tiles
  - label: Motor current
    topic: motor/current
    field: data
    unit: A
    warn_above: 12            # numbers: warn_above, fault_above, warn_below, fault_below
    stale_after: 3            # seconds; custom fields default to 3
  - label: Mode
    topic: mode
    field: data
    kind: text                # text: warn / fault value lists, like status
    warn: [MANUAL]
  - label: Docked
    topic: dock_status
    field: is_docked
    kind: bool                # true/false: warn: [false] or fault: [true]
```

Set `battery: false` or `cpu_temperature: false` to leave a tile out. To show
the Styri machine's own CPU temperature on purpose (for example when Styri runs
on the robot), use `cpu_temperature: {topic: host}`. The tile is then labelled
**Styri host CPU**. Styri never swaps it in silently.

**Field paths** are field names joined by dots, with `[n]` for list items
and `[-1]` for the last one: `data`, `twist.twist.linear.x`,
`status[0].values[1].value`, `status_list[-1].status`. The Topics tab shows
each topic's latest message, so you can read the path off it.

**Text values** (`status`, and fields with `kind: text`) can also take
`labels`, words for coded values (`{4: SUCCEEDED, 6: FAILED}`; `warn` and
`fault` then list the words), and `when_empty`, the value to show when the
path finds no item or nothing has been published yet. Any value can take
`stale_after: false` when its topic publishes only on change, so silence is
normal: it never shows STALE.

**Values in YAML:** bare `yes`, `no`, `on`, `off`, `true` and `false` are
read as true/false. For a text field, quote them: `warn: ["OFF"]`.

## Nav2

[`nav2.yaml`](../presets/nav2.yaml) reads navigation status from the
NavigateToPose action's status topic (`navigate_to_pose/_action/status`, an
`action_msgs/GoalStatusArray`). The tile shows the latest goal as IDLE,
NAVIGATING, SUCCEEDED, CANCELED or FAILED, and FAILED turns the robot to
WARNING. Nav2 publishes that topic only when a goal changes state and keeps the
last one for late joiners, so Styri reads it the same way: it sees the
current state as soon as it starts, and the tile never goes stale.

Nav2's own message types (`nav2_msgs`) are in the image, so its other
topics show their contents in the Topics tab and can be mapped too. The
preset has one commented out: distance to the goal, from the action's
feedback.

## Your own message types

The image includes ROS 2 Jazzy's standard message packages (`std_msgs`,
`geometry_msgs`, `sensor_msgs`, `nav_msgs`, `diagnostic_msgs`,
`action_msgs` and the rest of ros-base) plus `nav2_msgs`, `map_msgs`,
`control_msgs` (ros2_control) and `irobot_create_msgs` (iRobot Create 3 and
TurtleBot 4). A topic with any other type, such as a robot's own
`acme_msgs/msg/Mode`, shows in the Topics tab with its rate but not its
contents, and `styri check` says which package is missing:

```
  FAIL  Mode                 /mode · data  its type, acme_msgs/msg/Mode, isn't installed here, so Styri can't read it.
        Add the acme_msgs package as a message overlay: https://github.com/styri-dev/styri/blob/main/docs/MAPPING.md#your-own-message-types
```

To read those topics, give Styri the robot's message packages as an
**overlay**: a colcon `install` folder, built for ROS 2 Jazzy, mounted
read-only at `/opt/styri/overlay`. Styri loads it at start, before anything
else runs. Only the message packages are needed, never the robot's code.

**1. Build the message packages.** Copy them (each folder with its
`package.xml` and `msg/`) into a `src` folder, then build them with the
public ROS 2 Jazzy image. This works whatever ROS 2 version the robot runs,
Humble included, and on any machine with Docker:

```bash
docker run --rm -v "$PWD/src:/ws/src:ro" -v "$PWD/styri-msgs:/ws/install" ros:jazzy-ros-base \
  bash -c 'source /opt/ros/jazzy/setup.bash && cd /ws && colcon build --install-base /ws/install'
```

Build on the same kind of CPU as the machine that will run Styri (amd64 or
arm64), or copy the `src` folder there and build it on that machine. If the
messages depend on other message packages that aren't in the image, put those
in `src` too.

**2. Mount the result** at `/opt/styri/overlay`:

```bash
docker run --rm --network host \
  -v "$PWD/styri-msgs:/opt/styri/overlay:ro" \
  -v "$PWD/styri.yaml:/etc/styri/styri.yaml:ro" \
  ghcr.io/styri-dev/styri-core:v2.0.0
```

**3. Check it.** `styri check` (and the log at start) lists every overlay it
loaded, then tests your mapping:

```
Message overlay: /opt/styri/overlay
...
  PASS  Mode                 /mode · data  = AUTO
```

A robot workspace you already build on ROS 2 Jazzy, for the same CPU, works
as it is: mount its `install` folder. For several overlays, mount each under
`/opt/styri/overlay/<name>`. A package in an overlay takes the place of the
image's own copy, which is how to match a robot whose version of, say,
`nav2_msgs` differs from Jazzy's.

The overlay only adds message definitions: Styri still only subscribes, and
the Styri Pro image loads overlays the same way.

## Mixed fleets

One `styri.yaml` can hold ROS 2 and VDA 5050 robots together, on one site map.
[`mixed-fleet.yaml`](../presets/mixed-fleet.yaml) is an example, and
[`examples/mixed-fleet/`](../examples/mixed-fleet/) runs one with simulated robots.

```yaml
site:
  name: plant-a
  map: /etc/styri/site/map.yaml      # optional background
  graph: /etc/styri/site/graph.json  # node graph for VDA 5050 orders
  max_off_graph: 2                   # metres from a node, off every edge, before an order is refused

control:
  enabled: true                      # off by default: see SAFETY.md
  session_hours: 8                   # a login ends after this long unused
  stop_requires_login: false         # true: Operator stop and Stop all need the login too

vda:
  broker:
    bind: 192.168.1.20               # LAN address for the bundled broker
    # url: mqtt://broker.local:1883  # or a site's own broker; then the bundled one doesn't start
  interface: uagv

robots:
  - name: amr-01
    protocol: ros2
    namespace: /amr01
    cmd_vel: /amr01/cmd_vel          # what control may publish to
    nav2_action: /amr01/navigate_to_pose
    pause_topic: /amr01/pause        # optional std_msgs/Bool; without it, no Pause button
    pose: /amr01/amcl_pose           # or `tf`: map to base_link from /tf
    odom: /amr01/odom                # speed feedback; or `velocity:`, a Twist or TwistStamped topic
    max_linear: 0.5                  # m/s, enforced in the bridge
    max_angular: 1.0                 # rad/s
    points:                          # saved waypoints, on the site map
      - {name: Dock, x: 0, y: 0}
  - name: agv-07
    protocol: vda5050
    manufacturer: acme
    serial: "SN-0007"
    username: agv07                  # its login on the bundled broker
    password_env: AGV07_PASS         # the environment variable holding the password
    map_offset: {x: 0, y: 0, theta: 0}
```

An entry also takes everything a single robot does (`battery:`, `status:`,
`fields:` and so on), and top-level sections are shared defaults. The older
`robots: [{robot: {name: ...}}]` form keeps working.

**Users.** Accounts are viewer, operator or admin. Anyone can view and stop; operators
and admins can send, pause and drive; admins manage users, the map and two live
switches: robot control, and anonymous viewing, which when off means nothing is sent
to a browser until it logs in. Admins do this on the Users screen, or in the terminal
with `styri users`, inside the Styri container. All of it needs `control.enabled: true`.
`STYRI_ADMIN_PASSWORD` sets the `admin` account's password at each start.

**Whitelist.** Control sends only to what the file names: each ROS robot's
`cmd_vel`, `nav2_action` and `pause_topic`, and each VDA robot's
`instant_actions` (default `startPause`, `stopPause`, `cancelOrder`,
`factsheetRequest`). Anything else is refused in the bridge and logged.

**Speed feedback.** A ROS 2 robot needs `odom` or `velocity` to drive or take goals.
That's how Styri confirms a stop. Without one it gets Operator stop only, and
`styri check` warns.

**VDA 5050 robots** are read from their `state` message: battery, errors, pose
and order progress. Versions 2.0 and 2.1 are supported, and Styri speaks whichever
the vehicle does. They count as stale after 35 s without a message (the
standard asks for one every 30 s) or as soon as the vehicle is offline.

**Broker.** Mosquitto ships in the image and starts when the file has a `vda:`
section or VDA 5050 robots. It listens on localhost without a login, for Styri
itself. With `bind`, it also listens on that LAN address, where each vehicle logs
in with its `username` and may use only its own topics. `tls_cert` and `tls_key`
(mounted files) add TLS. It never bridges to another broker. `url` uses a site's
broker instead, with `username` and `password_env` if it needs a login.

**The node graph** is a JSON file:

```json
{"nodes": [{"id": "n1", "x": 2, "y": 2, "map_id": "plant-a"}, {"id": "n2", "x": 8, "y": 2, "map_id": "plant-a"}],
 "edges": [{"id": "e12", "start": "n1", "end": "n2"}]}
```

Edges run both ways unless they have `"directed": true`. You can write the file by
hand, or draw it: on the **Map** tab, log in and press **Edit graph** to add, move,
connect and delete nodes, then **Save graph**. It writes this same JSON, and the
new graph applies at once, with no restart. Orders already running keep their route.
`site.graph` can name a file that doesn't exist yet. To save, the file's folder must
be writable by Styri (uid 10001), so don't mount it `:ro`. Saving replaces the file,
so mount the folder, not the file. The editor makes two-way edges: a one-way edge is
set in the JSON, with `"directed": true`, and the editor keeps it when it saves. If
someone else saved since you opened the editor, Save says so, and you reload.

Tapping the map sends a
ROS 2 robot to that point; a VDA 5050 robot goes to the nearest node, along the
shortest route through the graph.

**The background** is a ROS `map.yaml` with its PGM or PNG, or a small YAML with
`image`, `resolution` (metres per pixel) and `origin`.

**Lining them up.** `map_offset` places a robot's own coordinates on the site map:
rotated by `theta`, then moved by `x` and `y`.

Styri doesn't do traffic management or deadlock avoidance across vendors,
automatic task allocation, or WMS/MES integration.

`styri check` adds the broker, each vehicle (connection, state, schema, factsheet),
vehicles seen on the broker but not configured, the graph, and the control setup.

## Several robots

Styri Core shows the first three robots in the file. The rest are listed as
"Not shown: free tier covers 3 robots". A Styri Pilot license raises that.


A file may list robots instead, each told apart by namespace and/or
`domain_id`. Sections at the top are shared defaults:

```yaml
battery: {topic: battery_state, warn_below: 30}
robots:
  - robot: {name: amr-1, namespace: /amr1}
  - robot: {name: amr-2, namespace: /amr2}
    battery: {warn_below: 40}  # this robot docks earlier
```

Styri Core shows the first robot (the Configuration tab says so); Styri Pilot
shows up to five, with a fleet view. A single-robot file works unchanged in
both.

Styri reads the file with a safe YAML loader (no tags, no code), and nothing
in it can make Styri publish: the bridge only ever subscribes.
