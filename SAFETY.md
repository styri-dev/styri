# Safety

Operator stop is a software stop. It is not an emergency stop or a safety function.

**Styri is not a safety system and has no safety certification.** It's an operator
panel, running on ordinary computers over ordinary networks. Any of them can fail.

Safety-rated stops must be hardware on the robot or part of the site's safety
system. Don't rely on Styri to keep people or equipment safe. Do your own risk
assessment before you turn control on, and keep the robot's own safety
functions in place.

## What Operator stop does

- **ROS 2:** cancels active Nav2 goals, then publishes zero velocity at 10 Hz for
  2 seconds.
- **VDA 5050:** sends `startPause` and `cancelOrder` in one `instantActions`
  message, and repeats it until the vehicle reports it isn't driving.

## What it can't do

- It needs the panel, the network, the bridge and the robot's software all to work.
- It needs a login, like every command.
- A ROS 2 robot may keep moving after the 2 seconds if something else commands it.
- **A VDA 5050 vehicle that has lost the broker keeps driving the route it already
  has.** Styri can't reach it. Keep routes short.
- A VDA 5050 vehicle that doesn't support `startPause` may drive on to its next
  node. Styri warns about this when the factsheet shows it.
- Some VDA 5050 vehicles hold a cancel until they're unpaused. Styri shows "Held,
  cancel pending", and never unpauses a vehicle by itself.

## What Styri does to limit risk

- Control is off by default. Off, Styri sends nothing at all.
- Commands need the admin login and must be on the whitelist in `styri.yaml`.
- Teleop goes out only while the control is held. The bridge caps the speed.
- If the browser or connection drops during teleop, the bridge sends zero velocity
  within 500 ms. The bridge holds that watchdog, not the browser.
- One driver per robot at a time.
- A robot whose data is STALE can't be driven or sent anywhere.
- Every command and refusal goes in a local append-only log.

## On your network

The panel uses plain HTTP, so the admin password crosses the network unencrypted.
Keep it on a network you trust, or put a TLS proxy in front. Until the password
is set, the first person to open the panel can set it: set `STYRI_ADMIN_PASSWORD`
on any shared network.
