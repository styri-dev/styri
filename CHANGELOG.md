# Changelog

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
