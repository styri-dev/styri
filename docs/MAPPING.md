# Mapping your robot's topics

Styri reads a `sensor_msgs/BatteryState` on `/battery_state` and a
`diagnostic_msgs/DiagnosticArray` on `/diagnostics` out of the box. For any
other robot, describe its topics in one YAML file, `styri.yaml`: which topic
and field is the battery, the voltage, the CPU temperature, the robot's own
status, and up to five more values of your choice. Any message type works:
fields are picked by path.

## Use a file

Mount it at `/etc/styri/styri.yaml`:

```bash
docker run --rm --network host -v "$PWD/styri.yaml:/etc/styri/styri.yaml:ro" ghcr.io/styri-dev/styri-core:v0.3.0
```

or put it anywhere and point `STYRI_CONFIG` at it. Without a file, the
`STYRI_*` environment variables apply as before
([Configuration](DEVELOPMENT.md#configuration)). Styri reads the file once,
at start: restart it after a change.

Three presets ship in the image, under `/opt/styri/presets/` (and in
[`presets/`](../presets/) here), ready to use as they are or to copy:

| Preset | For |
|---|---|
| `generic-battery-state.yaml` | Any robot with `BatteryState` and `DiagnosticArray`: what Styri does with no file, written out |
| `turtlebot4.yaml` | TurtleBot 4, real or in the Nav2 / Gazebo simulation |
| `styri-sim.yaml` | The simulated robot in this repo: every kind of mapping |

```bash
docker run --rm --network host -e STYRI_CONFIG=/opt/styri/presets/turtlebot4.yaml ghcr.io/styri-dev/styri-core:v0.3.0
```

## Check a file before you deploy it

`styri check` loads the file, listens to the live topics for 5 seconds and
prints PASS or FAIL for every mapping, with close matches for topics it can't
find. It exits 0 when everything passes, 1 when a mapping fails and 2 when the
file itself can't be used. Like the panel, it only listens.

```bash
docker run --rm --network host -v "$PWD/styri.yaml:/etc/styri/styri.yaml:ro" ghcr.io/styri-dev/styri-core:v0.3.0 styri check
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

**Field paths** are field names joined by dots, with `[n]` for list items:
`data`, `twist.twist.linear.x`, `status[0].values[1].value`. The Topics tab
shows each topic's latest message, so you can read the path off it.

**Values in YAML:** bare `yes`, `no`, `on`, `off`, `true` and `false` are
read as true/false. For a text field, quote them: `warn: ["OFF"]`.

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
