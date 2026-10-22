"""Read-only guarantee: the live Styri node has zero publishers and zero services.

Run next to a running Styri on the same ROS_DOMAIN_ID, for example:
  docker compose exec -T styri /ros_entrypoint.sh python3 - < ci/check_readonly.py
Run it from a Jazzy node: Humble cannot read Jazzy's graph info (type hashes).
Exits non-zero (and says why) if Styri could send anything to the robot.
READONLY_NODE=styri_check checks the node `styri check` starts instead (its
name carries a suffix, so this matches by prefix).
"""

import os
import sys
import time

import rclpy
from rclpy.node import Node

TARGET = os.environ.get("READONLY_NODE", "styri_bridge")

rclpy.init()
probe = Node("styri_readonly_probe")
deadline = time.monotonic() + 30
found = False
while time.monotonic() < deadline:
    rclpy.spin_once(probe, timeout_sec=0.2)
    names = probe.get_node_names_and_namespaces()
    match = [(name, ns) for name, ns in names if name == TARGET or name.startswith(TARGET + "_")]
    if match:
        found = True
        TARGET, ns = match[0]
        time.sleep(3)  # let discovery settle so we see every endpoint
        rclpy.spin_once(probe, timeout_sec=0.2)
        pubs = probe.get_publisher_names_and_types_by_node(TARGET, ns)
        services = probe.get_service_names_and_types_by_node(TARGET, ns)
        clients = probe.get_client_names_and_types_by_node(TARGET, ns)
        subs = probe.get_subscriber_names_and_types_by_node(TARGET, ns)
        break

if not found:
    print(f"FAIL: node {TARGET} not found on this ROS_DOMAIN_ID")
    sys.exit(2)
print(f"{TARGET}: {len(subs)} subscriptions, {len(pubs)} publishers, {len(services)} services, {len(clients)} clients")
for kind, items in (("publisher", pubs), ("service", services), ("client", clients)):
    for name, types in items:
        print(f"  {kind}: {name} {types}")
if pubs or services or clients:
    print("FAIL: Styri Core must not be able to send anything to the robot")
    sys.exit(1)
if not subs:
    print("FAIL: no subscriptions; is the bridge discovering topics?")
    sys.exit(1)
print("OK: read-only")
