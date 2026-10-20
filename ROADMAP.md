# Roadmap

What comes after Styri Core v0.1, in the order we expect to work on it. No
dates. Ideas and requests: [hello@styri.dev](mailto:hello@styri.dev).

## Controls (the Controls tab)

Today the tab is a disabled preview and Core is read-only. The planned panel:

- **Software stop.** One tap publishes a stop on a whitelisted topic, with
  hold-to-reset and an audit entry for every press. Software stop. Does not
  replace the robot's hardware E-stop.
- **Drive joystick.** Touch teleop on `/cmd_vel` with a dead-man hold (release
  or a dropped connection sends zero), speed limits, and one driver at a time.
- **Waypoints.** Send saved Nav2 goals from the touchscreen, with
  confirmation before dispatch.
- **Operator sign-in.** Viewer and operator roles; every command is logged
  with who sent it.

## Fleet view

Many robots, one screen.

## Air-gapped delivery

A signed offline install package with SBOM, and compliance audit-log exports.

## Core

- A `styri.yaml` file for topic mapping and thresholds, alongside env vars.
- HTTPS for the panel with a site-provided certificate.
- Mount your robot's custom message packages so the Topics tab can read them.
- A ROS package index listing for the bridge.
