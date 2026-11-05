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
- A ROS 2 robot may keep moving after the 2 seconds if something else commands it.
- **A VDA 5050 vehicle that has lost the broker keeps driving the route it already
  has.** Styri can't reach it. Keep routes short.
- A VDA 5050 vehicle that doesn't support `startPause` may drive on to its next
  node. Styri warns about this when the factsheet shows it.
- Some VDA 5050 vehicles hold a cancel until they're unpaused. Styri shows "Held,
  cancel pending", and never unpauses a vehicle by itself.

## What Styri does to limit risk

- Control is off by default. Off, Styri sends nothing at all.
- Commands need an operator or admin login and must be on the whitelist in `styri.yaml`.
- The one exception is stopping, the safe direction. With control on, anyone who
  can open the panel can press Operator stop or Stop all, so whoever sees a problem
  can act. Those stops are logged as "anonymous", with the browser's address and
  user agent, and limited to one per robot every 2 seconds. Stop all takes a
  one-second press and hold, so a stray tap can't halt the fleet. Undoing a stop
  (resume, a new goal, teleop) always needs an operator login.
- `control.stop_requires_login: true` makes stopping need the login too.
- Teleop goes out only while the control is held. The bridge caps the speed.
- If the browser or connection drops during teleop, the bridge sends zero velocity
  within 500 ms. The bridge holds that watchdog, not the browser.
- One driver per robot at a time.
- A robot whose data is STALE can't be driven or sent anywhere.
- After an Operator stop, a line under the button shows how it went: "Stop sent…",
  then "Stopped", "No reply from robot" (nothing back in 3 seconds), or "Stop NOT
  confirmed: still moving" (still moving after 15 seconds). The last two turn the
  robot's card red. The robot's health status doesn't change: stopping isn't a fault.
- A ROS 2 robot with no speed feedback can't confirm a stop, so it takes no drive or
  send commands, only Operator stop.
- Every command and refusal goes in a local append-only log.

## On your network

Because stopping needs no login, anyone on the network can keep robots stopped. If
that's a concern, set `control.stop_requires_login: true`.

The panel uses plain HTTP, so the admin password crosses the network unencrypted.
Keep it on a network you trust, or put a TLS proxy in front. Until the first password
is set, the first person to open the panel can set it: set `STYRI_ADMIN_PASSWORD`
on any shared network.
