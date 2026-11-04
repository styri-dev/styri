# Compatibility

What Styri v2.0 works with, and what it keeps from v1.

## Robots

| | Supported |
|---|---|
| ROS 2 | Humble and Jazzy robots; Fast DDS and Cyclone DDS |
| VDA 5050 | 2.0 and 2.1. Not 1.1 |
| Nav2 | `NavigateToPose`, on Jazzy; goals are cancelled through its standard action |
| Architectures | amd64 and arm64 |

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
