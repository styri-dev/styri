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
docker run --rm --network host -v "$PWD/styri.yaml:/etc/styri/styri.yaml:ro" ghcr.io/styri-dev/styri-core:v0.3.1
```

or put it anywhere and point `STYRI_CONFIG` at it. Without a file, the
`STYRI_*` environment variables apply as before
([Configuration](DEVELOPMENT.md#configuration)). Styri reads the file once,
at start: restart it after a change.

Four presets ship in the image, under `/opt/styri/presets/` (and in
[`presets/`](../presets/) here), ready to use as they are or to copy:

| Preset | For |
|---|---|
| `generic-battery-state.yaml` | Any robot with `BatteryState` and `DiagnosticArray`: what Styri does with no file, written out |
| `nav2.yaml` | Any robot running Nav2: navigation status (the latest NavigateToPose goal), battery, speed |
| `turtlebot4.yaml` | TurtleBot 4, real or in the Nav2 / Gazebo simulation, including docked or not |
| `styri-sim.yaml` | The simulated robot in this repo: every kind of mapping |

```bash
docker run --rm --network host -e STYRI_CONFIG=/opt/styri/presets/turtlebot4.yaml ghcr.io/styri-dev/styri-core:v0.3.1
```

## Check a file before you deploy it

`styri check` loads the file, listens to the live topics for 5 seconds and
prints PASS or FAIL for every mapping, with close matches for topics it can't
find. It exits 0 when everything passes, 1 when a mapping fails and 2 when the
file itself can't be used. Like the panel, it only listens.

```bash
docker run --rm --network host -v "$PWD/styri.yaml:/etc/styri/styri.yaml:ro" ghcr.io/styri-dev/styri-core:v0.3.1 styri check
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
  fault: [ERROR, ESTOP]       # values that mean FAULT; anything else is shown as it is
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
  ghcr.io/styri-dev/styri-core:v0.3.1
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

## Several robots (Styri Pilot)

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
