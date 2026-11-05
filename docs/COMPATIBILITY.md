# Compatibility

What Styri v2.0 works with, and what it keeps from v1.

Tested against simulators; real-robot results are added as they're run.

## Robots

| | Supported |
|---|---|
| ROS 2 | Humble and Jazzy robots; Fast DDS and Cyclone DDS |
| VDA 5050 | 2.0 and 2.1. Not 1.1 |
| Nav2 | `NavigateToPose`, on Jazzy; goals are cancelled through its standard action |
| Architectures | amd64 and arm64 |

## VDA 5050 field names

Styri follows the specification's text, for every vehicle: `allowedDeviationXY` and
`actionType`. The schema in VDA 5050's own `2.0.0` tag differs from that text, with
`allowedDeviationXy` and `actionName`; the `release/2.0.0` branch and 2.1.0 match the
text. So a 2.0 vehicle built strictly from the tag's schema may not understand Styri's
messages, and `styri check` flags what it sends back. Try one before you rely on it.

`vda-5050-lib`, which Styri's tests use as a simulated vehicle, reads only
`allowedDeviationXy`, for every version
([issue 54](https://github.com/coatyio/vda-5050-lib.js/issues/54)).

## From v1

- A `styri.yaml` from v1 works unchanged, including the nested
  `robots: [{robot: {name: ...}}]` form.
- A fresh install is view-only, as in v1. Control is off until you turn it on.
- The Activity log now lists only topics the panel relies on. Other topics still
  show STALE in the Topics tab.

## The map editor

- It makes two-way edges. One-way edges are set in the graph's JSON, with
  `"directed": true`, and the editor keeps them when it saves.
- It keeps one graph file per site. If someone saved since you opened the editor,
  your save is refused and you reload.
