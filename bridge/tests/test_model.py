"""The unified robot model, the v2 config and the robot cap."""

import time
from types import SimpleNamespace as NS

import pytest

from helpers import run_bridge
from styri_bridge import mapping, model, sitemap
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
    robots, _ = mapping.from_dict({"robots": [{"name": f"r{i}", "namespace": f"/r{i}", "odom": "odom"} for i in range(4)]}, {})
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
    caps = model.capabilities(mapping.RobotMap("x", link=mapping.Link(cmd_vel="/v", odom="/o")), model.Live())
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


def transform(parent, child, x=0.0, y=0.0, yaw_=0.0):
    import math
    return NS(header=NS(frame_id=parent), child_frame_id=child,
              transform=NS(translation=NS(x=x, y=y), rotation=NS(x=0, y=0, z=math.sin(yaw_ / 2), w=math.cos(yaw_ / 2))))


def test_tf_pose_walks_map_to_base():
    import math
    live = model.Live()
    tf = model.TfPose(live)
    tf.message(NS(transforms=[transform("odom", "base_footprint", 1.0, 0.0)]))
    assert live.pose is None  # no way to the map yet
    tf.message(NS(transforms=[transform("map", "odom", 2.0, 3.0, math.pi / 2)]))
    assert abs(live.pose["x"] - 2.0) < 1e-6 and abs(live.pose["y"] - 4.0) < 1e-6
    assert abs(live.pose["theta"] - math.pi / 2) < 1e-6
    tf.message(NS(transforms=[transform("base_footprint", "base_link")]))
    assert abs(live.pose["y"] - 4.0) < 1e-6


def test_pose_tf_in_the_file_taps_both_topics():
    robots, _ = mapping.from_dict({"robots": [{"name": "a", "namespace": "/a", "pose": "tf"}]}, {})
    assert robots[0].link.pose_tf and robots[0].link.pose == "/a/tf"
    cfg = Config(audit_db=":memory:", ui_dir=None, mapping=mapping.Loaded(tuple(robots), "test"))
    server = BridgeServer(cfg, AuditLog(":memory:"))
    assert {"/a/tf", "/a/tf_static"} <= set(server.robots[0].monitor.taps)


def robot_view(**link):
    return model.RobotView(0, "x", "0", Monitor(Quiet(), mapping.RobotMap("x", link=mapping.Link(**link))))


def test_a_stop_goes_sent_then_stopped():
    v = robot_view(cmd_vel="/v", odom="/o")
    assert model.stop_status(v) is None
    model.stop_sent(v.live)
    t = v.live.stop_sent_at
    assert model.stop_status(v, t + 1) == "sent"
    model.saw_motion(v.live, True)
    assert model.stop_status(v, t + 5) == "sent"
    model.saw_motion(v.live, False)
    assert model.stop_status(v) == "stopped"
    assert model.stop_status(v, v.live.stop_done_at + 31) is None


def test_silence_and_still_moving_are_different_messages():
    v = robot_view(cmd_vel="/v", odom="/o")
    model.stop_sent(v.live)
    t = v.live.stop_sent_at
    assert model.stop_status(v, t + 2.9) == "sent"
    assert model.stop_status(v, t + 3.1) == "no_reply"
    model.saw_motion(v.live, True)  # it answered, moving
    assert model.stop_status(v, t + 14.9) == "sent"
    assert model.stop_status(v, t + 15.1) == "not_confirmed"
    model.saw_motion(v.live, False)
    assert model.stop_status(v, t + 16) == "stopped"


def test_a_stop_leaves_the_robots_health_alone():
    v = robot_view(cmd_vel="/v", odom="/o")
    model.stop_sent(v.live)
    model.saw_motion(v.live, True)
    v.live.stop_sent_at -= 20
    snap = {"health": {"level": "ok", "line": "All systems normal."}}
    model.overlay_health(v, snap)
    assert model.stop_status(v) == "not_confirmed" and snap["health"]["level"] == "ok"


def test_no_speed_feedback_means_stop_only():
    link = dict(cmd_vel="/v", nav2_action="/n", pause_topic="/p")
    caps = model.capabilities(mapping.RobotMap("x", link=mapping.Link(**link)), model.Live())
    assert caps == {"can_teleop": False, "can_waypoint": False, "can_pause": False, "can_cancel": False, "can_stop": True}
    v = robot_view(**link)
    model.stop_sent(v.live)
    assert model.stop_status(v) == "cant_confirm"
    assert model.capabilities(mapping.RobotMap("x", link=mapping.Link(velocity="/t", **link)), model.Live())["can_teleop"]


def test_a_velocity_topic_confirms_a_stop():
    v = robot_view(cmd_vel="/v", velocity="/t")
    model.stop_sent(v.live)
    model.ros_velocity(v.live, NS(linear=NS(x=0.0), angular=NS(z=0.0)))
    assert model.stop_status(v) == "stopped"
    model.ros_velocity(v.live, NS(twist=NS(linear=NS(x=0.4), angular=NS(z=0.0))))  # TwistStamped
    assert v.live.driving


def test_a_new_command_clears_the_last_stop():
    v = robot_view(cmd_vel="/v", odom="/o")
    model.stop_sent(v.live)
    model.stop_over(v.live)
    assert model.stop_status(v) is None


def test_each_end_of_a_stop_is_logged_once():
    class Log(Quiet):
        msgs = []

        def add(self, kind, msg, source):
            self.msgs.append(msg)

    server = BridgeServer(four_robots(), AuditLog(":memory:"))
    r = server.robots[0]
    r.monitor.activity = Log()
    server.snapshot(0)
    model.stop_sent(r.live)
    model.saw_motion(r.live, True)
    r.live.stop_sent_at -= 20
    server.fleet()
    server.fleet()
    assert Log.msgs.count("Stop NOT confirmed: still moving") == 1


def test_the_verdict_on_every_screen_comes_from_the_same_place():
    server = BridgeServer(four_robots(), AuditLog(":memory:"))
    server.robots[0].live.online = False
    assert server.snapshot(0)["health"]["level"] == "unknown"
    assert server.fleet()["robots"][0]["verdict"] == "OFFLINE"


# ---- command steps, for the panel and the log --------------------------------

def snapshot_of(view):
    return view.monitor.evaluate()


def command(action, **over):
    return model.Command(1, action, "m.lind", 0.0, 100.0, **over)


def walk(view, now=100.0):
    step = model.next_step(view, now)
    if step:
        model.advance(view.live.command, *step)
    return view.live.command


def test_a_vda_order_goes_sent_accepted_running_done():
    v = robot_view()
    v.live.command = command("GOAL", order="o1", node="n3")
    assert walk(v).status == "sent"
    v.live.task_id, v.live.task_state = "o1", "active"
    assert walk(v).status == "running"
    assert v.live.command.steps == ["sent", "accepted", "running"]
    v.live.task_state = "done"
    assert walk(v).status == "done"
    assert model.next_step(v, 1000.0) is None  # the end is the end


def test_a_ros_goal_counts_once_a_new_goal_shows_up():
    v = robot_view()
    v.live.task_id, v.live.task_state = "old", "done"
    v.live.command = command("GOAL", before="old", point=(1, 2))
    assert walk(v).status == "sent"
    v.live.task_id, v.live.task_state = "new", "active"
    assert walk(v).status == "running"
    v.live.task_state = "idle"
    assert walk(v).status == "cancelled"


def test_nav2_turning_a_goal_down_is_rejected():
    v = robot_view()
    v.live.command = command("GOAL")
    v.live.goal_rejected = True
    assert walk(v).status == "rejected"


def test_a_vehicle_refusing_an_order_is_rejected_with_its_words():
    v = robot_view()
    v.live.command = command("GOAL", order="o1")
    v.live.errors = [{"type": "noRouteError", "level": "WARNING", "description": "B2 is not in its map"}]
    cmd = walk(v)
    assert (cmd.status, cmd.reason) == ("rejected", "Robot rejected the order: B2 is not in its map")


def test_a_fatal_error_fails_the_order_with_its_words():
    v = robot_view()
    v.live.task_id, v.live.task_state = "o1", "failed"
    v.live.errors = [{"type": "motor", "level": "FATAL", "description": "motor fault"}]
    v.live.command = command("GOAL", order="o1")
    cmd = walk(v)
    assert (cmd.status, cmd.reason) == ("failed", "Robot aborted the order: motor fault")


def test_silence_after_a_command_is_not_confirmed_not_done():
    v = robot_view()
    v.live.command = command("GOAL", order="o1")
    assert walk(v, 100.0 + model.COMMAND_WAIT - 1).status == "sent"
    assert walk(v, 100.0 + model.COMMAND_WAIT).status == "not_confirmed"


def test_pause_is_done_when_the_robot_says_so():
    v = robot_view()
    v.live.command = command("PAUSE")
    assert walk(v).status == "sent"
    v.live.paused = True
    cmd = walk(v)
    assert cmd.status == "done" and cmd.steps == ["sent", "accepted", "running", "done"]


def test_a_stop_ends_in_its_own_words():
    v = robot_view(odom="/odom")
    model.stop_sent(v.live)
    v.live.command = command("OPERATOR_STOP")
    model.saw_motion(v.live, False)
    assert walk(v, time.monotonic()).status == "stopped"


def test_the_model_says_who_paused_it_and_only_while_paused():
    v = robot_view()
    v.live.paused_by = "j.okafor"
    snap = snapshot_of(v)
    assert model.describe(v, snap)["paused_by"] is None
    v.live.paused = True
    assert model.describe(v, snap)["paused_by"] == "j.okafor"


def test_a_stop_says_when_it_stopped():
    v = robot_view(odom="/odom")
    model.stop_sent(v.live)
    assert model.describe(v, snapshot_of(v))["stop_at"] is None
    model.saw_motion(v.live, False)
    assert abs(model.describe(v, snapshot_of(v))["stop_at"] - time.time()) < 5


def test_a_vehicle_off_the_graph_says_how_far():
    graph = sitemap.Graph([sitemap.Node("a", 0, 0, "m"), sitemap.Node("b", 10, 0, "m")], [sitemap.Edge("e", "a", "b")])
    link = NS(protocol="vda5050")
    v = NS(map=NS(link=link))
    assert model.off_graph(v, {"x": 5, "y": 0.2}, graph, 2.0) is None  # on the edge
    assert model.off_graph(v, {"x": 0, "y": 1.0}, graph, 2.0) is None  # near a node
    assert model.off_graph(v, {"x": 5, "y": 3.4}, graph, 2.0) == 3.4
    assert model.off_graph(NS(map=NS(link=NS(protocol="ros2"))), {"x": 5, "y": 3.4}, graph, 2.0) is None


def test_node_names_and_one_way_edges_survive_a_save():
    data = {"nodes": [{"id": "n1", "x": 0, "y": 0, "map_id": "m", "name": "Dock 1"}, {"id": "n2", "x": 1, "y": 0, "map_id": "m"}],
            "edges": [{"id": "e1", "start": "n1", "end": "n2", "directed": True}]}
    assert sitemap.Graph.from_dict(data).to_dict() == data
