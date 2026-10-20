# Developing Styri Core

## Layout

| Path | What |
|---|---|
| [`bridge/`](../bridge/) | Python bridge: ROS 2 topic discovery, robot health, activity log; serves the panel and `/ws` |
| [`ui/`](../ui/) | The operator panel: React + TypeScript, built with Vite into the image |
| [`sim/`](../sim/) | A simulated robot as a real ROS 2 node, for testing without hardware |
| [`e2e/`](../e2e/) | Playwright suite that drives the real panel against the sim |
| [`ci/`](../ci/) | CI checks: read-only guarantee, no-egress guard, fresh-machine quickstart |
| [`Dockerfile`](../Dockerfile) | The one image: UI build + bridge on `ros:jazzy-ros-base` |
| [`compose.yaml`](../compose.yaml) | Styri plus the sim, both on host networking |

## Run it against the simulated robot

You need Docker. On macOS: `brew install colima docker docker-compose`, then `colima start`.

```bash
docker compose up --build
```

Open http://localhost:8080. Make the robot misbehave:

```bash
docker compose exec sim /ros_entrypoint.sh python3 -m styri_sim fault battery:18
```

Faults: `battery:<percent>`, `overheat`, `motor_fault`, `battery_sag`,
`silence:<seconds>` (stops publishing), `clear`. `python3 -m styri_sim pose`
prints the robot's position and speed.

The same stack runs the matrix CI uses:

```bash
RMW_IMPLEMENTATION=rmw_cyclonedds_cpp docker compose up --build
```

```bash
SIM_ROS_DISTRO=humble docker compose up --build
```

`SIM_RMW_IMPLEMENTATION` sets the robot's DDS vendor on its own.

## Tests

Unit tests (bridge and sim):

```bash
cd bridge && python3 -m venv .venv && .venv/bin/pip install -e '.[test]' && .venv/bin/pytest
```

```bash
PYTHONPATH=sim bridge/.venv/bin/pytest sim/tests
```

End to end, with the compose stack running:

```bash
cd e2e && npm ci && npx playwright install chromium && npx playwright test
```

The CI checks, against the running stack:

```bash
docker compose exec -T styri /ros_entrypoint.sh python3 - < ci/check_readonly.py
```

```bash
docker run --rm --network host -v "$PWD/ci:/ci:ro" --entrypoint python3 styri-core:dev /ci/quickstart_check.py
```

`ci/egress-guard.sh` needs Linux and root (on macOS, run it inside the Colima
VM with `colima ssh`); see the script for usage.

### What CI runs

Every push and pull request runs the unit tests and the e2e suite on x86 and
Arm, with Fast DDS and Cyclone DDS, against a Humble robot, and against a
robot on a different DDS vendor from Styri. Each e2e run also checks that:

- **Styri is read-only.** The `styri_bridge` node has zero publishers,
  services and clients on the robot's graph.
- **Nothing leaves the LAN.** A firewall rule on Styri's user refuses anything
  but loopback, private ranges and multicast, DNS included, and the job fails
  if a single packet is refused.

Pushes to `main` and tags publish the multi-arch image and then run the exact
quickstart command on clean x86 and Arm runners, requiring live data within
60 s. Tags release only if all of it passes.

## UI without Docker

Run the bridge with made-up data, then the Vite dev server, and open
http://localhost:5173:

```bash
STYRI_AUDIT_DB=./audit.db bridge/.venv/bin/python -m styri_bridge --fake
```

```bash
npm --prefix ui run dev
```

## Configuration

Environment variables, for example `docker run -e ROS_DOMAIN_ID=7 …`:

| Variable | Default | |
|---|---|---|
| `ROS_DOMAIN_ID` | `0` | Must match the robot |
| `RMW_IMPLEMENTATION` | `rmw_fastrtps_cpp` | Or `rmw_cyclonedds_cpp` |
| `STYRI_ROBOT_NAME` | the host name | Shown in the header |
| `STYRI_BATTERY_TOPIC` | `/battery_state` | A `sensor_msgs/BatteryState` topic |
| `STYRI_DIAGNOSTICS_TOPIC` | `/diagnostics` | A `diagnostic_msgs/DiagnosticArray` topic |
| `STYRI_STALE_AFTER` | `5` | Seconds before a value counts as stale |
| `STYRI_PORT` | `8080` | |
| `STYRI_AUDIT_DB` | `/var/lib/styri/audit.db` | Mount a volume here to keep the log |

Health comes from `/battery_state` (warning below 25 %, fault below 10 %), CPU
temperature (warning at 75 °C, fault at 85 °C; from a `cpu`-named status in
`/diagnostics`, or the host's own sensor) and any `/diagnostics` status at
WARN or ERROR.

## Protocol

The panel talks to the bridge over one WebSocket at `/ws`. Server to client:

```jsonc
{"type": "hello", "version": "0.1.0", "robot": "amr-01", "domain": "0", "stale_after": 5, "controls": false}
{"type": "activity", "events": [{"id": 12, "ts": 1792500000.1, "kind": "warning", "msg": "Battery below 25 %", "source": "/battery_state"}]}
{"type": "event", "event": {…}}
{"type": "snapshot", "health": {"level": "ok", "line": "All systems normal."}, "battery": {…}, "topics": [{"name": "/odom", "type": "nav_msgs/msg/Odometry", "hz": 20.0, "age": 0.04, "stale": false}], …}
{"type": "message", "topic": "/odom", "msg_type": "nav_msgs/msg/Odometry", "text": "pose:\n  …"}
{"type": "pong", "t": 123.4}
```

Client to server: `{"action": "PING", "t": …}` and `{"action": "SELECT", "topic": "/odom"}`.
Anything else is refused and logged.

## Extensions

`styri_bridge.extensions` loads functions registered under the
`styri.extensions` entry-point group, which other editions use to add to the
bridge. Core ships none, and with none installed the bridge has no publishers.
