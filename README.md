<!-- Storefront README for the PUBLIC styri repo. Replace the hero GIF path once recorded. -->

<p align="center">
  <img src="docs/media/hero.gif" alt="Styri: ROS 2 nodes in a terminal on the left, the Styri operator panel showing live robot status on the right" width="900">
</p>

# Styri

**The ROS 2 web dashboard and operator panel that never leaves your network.**

Built for the operators running robots on site, not a cloud dashboard miles away. Open-source ROS 2 operator panel that runs on the robot or any Linux box on its network and works in any browser on the LAN. Fully offline, free from the first robot. One command to start.

[Website](https://styri.dev) · [Quickstart](#quickstart) · [How it compares](#foxglove-in-the-lab-formant-in-the-cloud-styri-on-the-floor) · [Pricing](#editions) · [Help](https://styri.dev/help)

---

## Quickstart

Run it on any ROS 2 machine (Humble or Jazzy, amd64 or arm64):

```bash
docker run --rm --network host ghcr.io/styri-dev/styri-core:v2.0.0
```

Open **http://localhost:8080**. Styri finds your robot's topics over DDS and shows them live.

Host networking lets Styri see DDS discovery on your LAN. Open source: [read the code](.) before you run it.

Deploying to a client fleet? We can set it up for you. [Talk to us](https://styri.dev/#talk)

**On a Mac?** Run Styri on the robot or any Linux machine on its network, and open the panel from any browser, Mac included. Docker on macOS can't see a robot on another machine, but `docker compose up` (below) gives you the full demo with a simulated robot.

**No robot handy?** Run the simulated robot and the panel together:

```bash
docker compose up
```

**A mixed fleet, no hardware?** One ROS 2 robot and two VDA 5050 vehicles on one map, all simulated:

```bash
cd examples/mixed-fleet && docker compose up --build
```

Open **http://localhost:8080** and log in with `styri-demo`. `docker compose down -v` resets the demo, map edits included.

## Control and safety

Styri can command ROS 2 and VDA 5050 robots from one panel: hold-to-drive teleop, waypoints, pause, resume, cancel and Operator stop, per robot and for the whole fleet. It's off by default. Turning it on takes `control.enabled: true` (or `STYRI_CONTROL=1`) and a local admin password. Accounts are viewer, operator or admin, managed on the Users screen or with `styri users`. Viewing stays open on the LAN, and so does stopping: anyone at the panel can press Operator stop, unless you set `control.stop_requires_login: true`. Every other command needs an operator login. All of them must be on the whitelist in your `styri.yaml`, and go in a local append-only audit log.

Operator stop is a software stop. It is not an emergency stop or a safety function. Styri has no safety certification, and safety-rated stops must be hardware on the robot or the site safety system. Read [SAFETY.md](SAFETY.md) before you turn control on.

## What you get

- **Overview** — robot status, battery, voltage, CPU temperature and link health, readable at a glance on a touchscreen
- **Topics** — every discovered topic with its rate and last-message age
- **Activity log** — a local log of connections, warnings and state changes, exportable to CSV
- **Honest data** — every value shows when it goes stale; disconnects are obvious

A fresh install is **view-only**: it never sends anything to your robot. Control is off until you turn it on: see [Control and safety](#control-and-safety).

## Nothing phones home

- Every asset is served locally: fonts, icons, scripts. No CDN.
- No telemetry, no license server, no account.
- Unplug the internet and it still works.

Verify it yourself:

```bash
sudo tcpdump -i any 'not net 10.0.0.0/8 and not net 172.16.0.0/12 and not net 192.168.0.0/16 and not host 127.0.0.1 and not net 224.0.0.0/4'
```

Nothing should appear while Styri runs. (DDS discovery uses LAN multicast, 224.0.0.0/4, which never leaves your network.)

## Foxglove in the lab. Formant in the cloud. Styri on the floor.

| | RViz2 | Foxglove | Formant | Styri |
|---|---|---|---|---|
| Built for | Engineers | Engineers: data visualization and log analysis | Fleet operations teams, remotely from the cloud | Operators running robots on site |
| Runs in | Desktop / X11 on the robot or forwarded | Desktop app on each machine | Cloud web app; self-hosted on your own servers for restricted sites | Any browser on the robot's local network |
| Offline use | Fully local | Free and Pro: account sign-in needs internet. Fully offline via standalone license or on-prem deployment on Enterprise | Standard: agent streams to Formant's cloud; teleop needs Formant and Twilio servers. Air-gapped only via self-hosted on-prem deployment | Fully offline on every tier, including free |
| Install | apt or source build | Desktop install + offline license activation | Agent on each robot (internet needed to install); on-prem means running Formant's servers | One `docker run` on the robot or any Linux box on its network |
| Source | Open source | Proprietary | Proprietary | Open-source core |

Foxglove helps engineers analyze robot data. Formant runs fleets from the cloud. Styri helps operators run robots on site — fully offline, from the free tier up.

**Already using [rosboard](https://github.com/dheera/rosboard) or another ROS web viewer?** Those are great for engineers exploring topics. Styri adds what operators need on the floor: a clear OK / WARNING / FAULT verdict with the reason, your own thresholds in one `styri.yaml`, values that show their age and turn STALE, `styri check` against the live robot, and a panel that's view-only until you turn control on.

## How it works

```
ROS 2 nodes ──DDS──▶ Styri bridge ──local WebSocket──▶ Styri panel ──LAN──▶ any browser
                         │
                         └──▶ local activity log (SQLite)
```

One container: a small bridge subscribes to your ROS 2 topics and serves a static web panel. Nothing leaves the machine except to browsers on your LAN.

## Configuration

Pass settings as environment variables, for example
`docker run -e ROS_DOMAIN_ID=7 -e STYRI_MIN_VOLTAGE=23.0 --rm --network host ghcr.io/styri-dev/styri-core:v2.0.0`.

| Variable | Default | |
|---|---|---|
| `ROS_DOMAIN_ID` | `0` | Must match the robot |
| `STYRI_ROBOT_NAME` | the host name | Shown in the header |
| `STYRI_BATTERY_TOPIC` | `/battery_state` | A `sensor_msgs/BatteryState` topic |
| `STYRI_DIAGNOSTICS_TOPIC` | `/diagnostics` | A `diagnostic_msgs/DiagnosticArray` topic |
| `STYRI_MIN_VOLTAGE` | unset | Volts. Below this the Voltage tile turns amber and the status shows a low-voltage warning, whatever the charge reads. Unset, voltage is shown but never judged. |

### Map your robot's topics

Different topic names, another message type, the robot's own status, or a few
values of your own? Describe them in one `styri.yaml` and mount it:

```yaml
robot: {name: amr-01, namespace: /robot1}
battery: {topic: battery, percentage: charge, percentage_scale: 1, warn_below: 30}
status: {topic: mode, field: data, fault: [ERROR, STOPPED]}
fields:
  - {label: Motor current, topic: motor/current, field: data, unit: A, warn_above: 12}
```

```bash
docker run --rm --network host -v "$PWD/styri.yaml:/etc/styri/styri.yaml:ro" ghcr.io/styri-dev/styri-core:v2.0.0 styri check
```

`styri check` tests the file against the live robot and names anything it can't
find, with close matches. Presets for Nav2 (navigation status), TurtleBot 4
and generic `BatteryState` robots ship in the image, along with Nav2's and
other common message types. Your robot's own message types load as an
[overlay](docs/MAPPING.md#your-own-message-types). The full reference:
[docs/MAPPING.md](docs/MAPPING.md).

All settings: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#configuration). What works with what: [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md). Something not showing up? See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Roadmap

- **Multi-robot missions, local users and a tamper-evident audit log.**
- **Air-gapped delivery** — signed offline install package, SBOM and compliance audit exports.

## Editions

| | Core | Commercial Pilot | Air-Gapped Enterprise |
|---|---|---|---|
| Price | Free (open source) | $360/mo or $3,600/yr | Contact us |
| Status | Available now | Available now | Coming soon |
| Robots | 1 | Up to 5 | Unlimited |
| Network | Local LAN | Local LAN | Air-gapped site, site-wide |
| Includes | Read-only operator panel, live telemetry, local activity log | Everything in Core, plus fleet view across robots and direct support | Everything in Pilot, plus offline Zarf package, compliance audit log exports, offline hardware-locked license |
| | You're here | [Buy or talk to us](https://styri.dev/#pricing) | [Contact us](https://styri.dev/#talk) |

Running more than one robot? Styri Pilot is the public `ghcr.io/styri-dev/styri-pro` image plus a license file: [docs/PILOT.md](docs/PILOT.md). Deploying to a site without internet? [Talk to us](https://styri.dev/#talk).

## Contributing

Issues and pull requests are welcome. See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) to build and test locally.

## License

Apache-2.0. See [LICENSE](LICENSE). Bundled third-party software is listed in [NOTICE](NOTICE). Styri comes with no warranty and no safety certification: see [SAFETY.md](SAFETY.md).
