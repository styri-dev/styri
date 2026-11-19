# Changelog

## Unreleased

- **Pause on a robot that's already paused is a note, not a warning.** Styri doesn't send it,
  and the robot's card says "Already paused. Nothing sent." in grey for a few seconds; the same
  for Resume on a robot that isn't paused. When two operators, or Styri and a fleet manager,
  pause a VDA 5050 vehicle at nearly the same moment and the vehicle refuses the second
  `startPause`, that refusal no longer turns the robot WARNING: Activity notes it instead.
- **The mixed-fleet example's ROS 2 robot drives around the racks.** Its simulator plans a path
  on open floor from `site/obstacles.json`, which `make_floor.py` now writes, and turns down a
  goal on a rack, which the panel shows as Rejected by robot. It used to drive straight through.
  The simulated VDA 5050 vehicles announce ONLINE again after a reconnect.

## v2.0.1

- **VDA 5050 interface names with several levels work.** `vda.interface: fleet/uagv`, as a
  shared or cloud broker may need (VDA 5050 2.x, section 6.3), used to connect and then
  ignore every message, so the vehicles never showed up and nothing said why. Styri now reads
  topics under any interface name, however many levels it has.
- **Vehicles under another interface name are reported.** When a VDA 5050 vehicle publishes
  under a different interface name than `vda.interface`, Styri logs a warning and shows it in
  Activity, and `styri check` warns about it, instead of the vehicle silently never appearing.
  For this, Styri also subscribes to `connection` under any interface name one to three levels
  deep. A broker that closes the connection over that subscription gets the narrower one.

## v2.0.0

First release of Styri v2: offline control of mixed ROS 2 and VDA 5050 fleets.
