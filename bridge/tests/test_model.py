"""The unified robot model, the v2 config and the robot cap."""

from types import SimpleNamespace as NS

import pytest

from helpers import run_bridge
from styri_bridge import mapping, model
from styri_bridge.config import Config
from styri_bridge.audit import AuditLog
from styri_bridge.monitor import Monitor
from styri_bridge.server import BridgeServer


class Quiet:
    def add(self, *a):
        pass


FILE = {
    "site": {"name": "plant-a", "graph": "/etc/styri/site/graph.json"},
    "control": {"enabled": True, "session_hours": 4},
    "vda": {"broker": {"bundled": True}, "interface": "uagv"},
    "robots": [
        {"name": "amr-01", "protocol": "ros2", "namespace": "/amr01", "cmd_vel": "/amr01/cmd_vel",
         "nav2_action": "/amr01/navigate_to_pose", "pose": "/amr01/amcl_pose", "max_linear": 0.4, "max_angular": 0.8},
        {"name": "agv-07", "protocol": "vda5050", "manufacturer": "acme", "serial": "SN-0007", "username": "agv07",
         "password_env": "AGV07_PASS", "map_offset": {"x": 1, "y": 2, "theta": 0}},
    ],
}


def test_the_mixed_file_loads(tmp_path):
    path = tmp_path / "styri.yaml"
    import yaml
    path.write_text(yaml.safe_dump(FILE))
    loaded = mapping.load(str(path), env={})
    assert loaded.error is None
    amr, agv = loaded.robots
    assert amr.link.cmd_vel == "/amr01/cmd_vel" and amr.link.max_linear == 0.4
    assert amr.namespace == "/amr01" and amr.link.nav2_status() == "/amr01/navigate_to_pose/_action/status"
    assert agv.link.protocol == "vda5050" and agv.link.serial == "SN-0007" and agv.link.map_offset == (1, 2, 0)
    assert agv.value("battery").field == "batteryState.batteryCharge" and agv.diagnostics_topic is None
    assert agv.stale_after == mapping.VDA_STALE_AFTER
    assert loaded.settings.control and loaded.settings.session_hours == 4 and loaded.settings.site_name == "plant-a"


def test_v1_robot_files_still_load():
    robots, _ = mapping.from_dict({"battery": {"warn_below": 30},
                                   "robots": [{"robot": {"name": "a", "namespace": "/a"}},
                                              {"robot": {"name": "b", "namespace": "/b"}}]}, {})
    assert [r.name for r in robots] == ["a", "b"] and robots[0].link == mapping.Link()
    assert robots[1].value("battery").rule.warn_below == 30


@pytest.mark.parametrize("data, needle", [
    ({"robots": [{"name": "a", "protocol": "mqtt"}]}, "protocol"),
    ({"robots": [{"name": "a", "protocol": "vda5050", "serial": "1"}]}, "manufacturer"),
    ({"robots": [{"name": "a", "protocol": "vda5050", "manufacturer": "m", "serial": "1", "cmd_vel": "/x"}]}, "cmd_vel"),
    ({"robots": [{"name": "a", "manufacturer": "m"}]}, "manufacturer"),
    ({"robots": [{"name": "a"}, {"name": "b", "namespace": "/b"}], "vda": {"broker": {"bundled": True, "url": "mqtt://x"}}},
     "bundled"),
    ({"control": {"enable": True}}, "did you mean"),
])
def test_bad_v2_config_is_named(data, needle):
    with pytest.raises(mapping.ConfigError) as exc:
        mapping.from_dict(data, {})
    assert needle in str(exc.value)


def test_stop_needs_no_login_unless_the_file_says_so(tmp_path):
    assert not mapping.load(None, env={}).settings.stop_requires_login
    path = tmp_path / "styri.yaml"
    path.write_text("control: {enabled: true, stop_requires_login: true}\n")
    assert mapping.load(str(path), env={}).settings.stop_requires_login


def test_control_is_off_unless_asked():
    assert not mapping.load(None, env={}).settings.control
    assert mapping.load(None, env={"STYRI_CONTROL": "1"}).settings.control


def test_a_bad_file_leaves_control_off(tmp_path):
    path = tmp_path / "styri.yaml"
    path.write_text("control: {enabled: true}\nbattery: {nope: 1}\n")
    loaded = mapping.load(str(path), env={"STYRI_CONTROL": "1"})
    assert loaded.error and not loaded.settings.control


def four_robots():
    robots, _ = mapping.from_dict({"robots": [{"name": f"r{i}", "namespace": f"/r{i}"} for i in range(4)]}, {})
    return Config(audit_db=":memory:", ui_dir=None, mapping=mapping.Loaded(tuple(robots), "test"))


def test_core_shows_three_and_lists_the_fourth():
    server = BridgeServer(four_robots(), AuditLog(":memory:"))
    server.build_robots()
    assert [r.name for r in server.robots] == ["r0", "r1", "r2"]
    assert server.not_shown == [{"name": "r3", "protocol": "ros2", "reason": "Not shown: free tier covers 3 robots",
                                 "link": "https://styri.dev/pricing"}]


def test_a_license_raises_the_cap():
    server = BridgeServer(four_robots(), AuditLog(":memory:"))
    server.set_robot_limit(20)
    server.build_robots()
    assert len(server.robots) == 4 and server.not_shown == []


def test_the_fleet_message_has_every_robot():
    async def check(url, server, audit):
        for r in server.robots:
            server.snapshot(r.index)
        fleet = server.fleet()
        assert [r["name"] for r in fleet["robots"]] == ["r0", "r1", "r2"]
        assert fleet["not_shown"][0]["name"] == "r3"
        assert set(fleet["robots"][0]) >= {"id", "protocol", "verdict", "reason", "battery", "voltage", "errors",
                                           "last_seen", "stale", "pose", "velocity", "driving", "paused", "task",
                                           "capabilities"}
    run_bridge(check, cfg=four_robots())


def view(link):
    return model.RobotView(0, "x", "0", Monitor(Quiet(), mapping.RobotMap("x", link=link)))


def test_ros_capabilities_come_from_the_config():
    caps = model.capabilities(mapping.RobotMap("x", link=mapping.Link(cmd_vel="/v")), model.Live())
    assert caps == {"can_teleop": True, "can_waypoint": False, "can_pause": False, "can_cancel": False, "can_stop": True}
    caps = model.capabilities(mapping.RobotMap("x"), model.Live())
    assert not any(caps.values())


def test_vda_capabilities_follow_the_factsheet():
    robot = mapping.RobotMap("x", link=mapping.Link(protocol="vda5050", manufacturer="m", serial="1"))
    assert model.capabilities(robot, model.Live())["can_pause"]
    sheet = {"protocolFeatures": {"agvActions": [{"actionType": "cancelOrder"}]}}
    caps = model.capabilities(robot, model.Live(factsheet=sheet))
    assert not caps["can_pause"] and caps["can_cancel"] and caps["can_stop"]


def test_nav2_status_becomes_the_task():
    live = model.Live()
    uuid = list(range(16))
    model.nav2_status(live, NS(status_list=[NS(status=2, goal_info=NS(goal_id=NS(uuid=uuid)))]))
    assert live.task_state == "active" and live.task_id == "00010203"
    model.nav2_status(live, NS(status_list=[NS(status=6, goal_info=NS(goal_id=NS(uuid=uuid)))]))
    assert live.task_state == "failed"
    model.nav2_status(live, NS(status_list=[]))
    assert live.task_state == "idle"


def test_ros_pose_reads_amcl_shape():
    live = model.Live()
    q = NS(x=0, y=0, z=0.7071068, w=0.7071068)
    model.ros_pose(live, NS(header=NS(frame_id="map"), pose=NS(pose=NS(position=NS(x=1, y=2), orientation=q))))
    assert live.pose["x"] == 1 and abs(live.pose["theta"] - 1.5708) < 1e-3 and live.pose["map_id"] == "map"
