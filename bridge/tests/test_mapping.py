from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from styri_bridge import mapping
from styri_bridge.mapping import ConfigError, extract, from_dict, load, resolve, suggest
from styri_bridge.monitor import MISSING_GRACE, Monitor

from test_monitor import Clock, Log

PRESETS = Path(__file__).resolve().parents[2] / "presets"


def robot(text, env=None):
    robots, _ = from_dict(yaml.safe_load(text), env or {})
    return robots[0]


def problems(text):
    with pytest.raises(ConfigError) as exc:
        from_dict(yaml.safe_load(text), {})
    return exc.value.problems


def test_presets_all_load():
    names = sorted(p.name for p in PRESETS.glob("*.yaml"))
    assert len(names) >= 3
    for p in PRESETS.glob("*.yaml"):
        robots, _ = mapping.load_file(str(p), {})
        assert robots[0].value("battery") is not None, p.name


def test_defaults_match_the_old_behaviour():
    r = robot("{}")
    bat = r.value("battery")
    assert (bat.topic, bat.field, bat.scale) == ("/battery_state", "percentage", 100.0)
    assert (bat.rule.warn_below, bat.rule.fault_below) == (25.0, 10.0)
    cpu = r.value("cpu_temp")
    assert (cpu.topic, cpu.diag_status, cpu.diag_key, cpu.label) == ("/diagnostics", "cpu", "temp", "CPU temp")
    assert r.diagnostics_topic == "/diagnostics" and not r.host_fallback


def test_namespace_and_topic_resolution():
    r = robot("robot: {namespace: /robot1}\nbattery: {topic: battery}\nfields:\n"
              "  - {label: Speed, topic: /odom, field: twist.twist.linear.x}")
    assert r.value("battery").topic == "/robot1/battery"
    assert r.value("field1").topic == "/odom"  # absolute names are kept
    assert resolve("x", "") == "/x" and resolve("x", "a/") == "/a/x"


def test_problems_are_named_and_suggest_fixes():
    found = problems("batery: {}\nbattery: {topic: 5 6}\nfields:\n  - {label: A, topic: x}\n"
                     "  - {label: B, topic: y, field: data, kind: text, warn_above: 3}")
    text = "\n".join(found)
    assert "batery: unknown key (did you mean “battery”?)" in text
    assert "battery.topic: “5 6” is not a ROS topic name" in text
    assert "fields[0].field: required" in text
    assert "fields[1]: warn_above/warn_below are for numbers" in text


def test_yaml_traps_and_limits():
    assert any("in quotes" in p for p in problems("status: {topic: s, warn: [OFF]}"))
    assert any("at most 5" in p for p in problems(
        "fields:\n" + "".join(f"  - {{label: F{i}, topic: t{i}, field: data}}\n" for i in range(6))))
    assert any("not a field path" in p for p in problems("battery: {percentage: 'a..b'}"))


def test_only_safe_yaml(tmp_path):
    f = tmp_path / "styri.yaml"
    f.write_text("battery: !!python/object/apply:os.system ['echo pwned']\n")
    loaded = load(str(f), {})
    assert loaded.error and "not valid YAML" in loaded.error
    assert loaded.robots[0].values == ()  # nothing from the file is used


def test_bad_file_is_reported_not_fatal(tmp_path):
    f = tmp_path / "styri.yaml"
    f.write_text("battery:\n  topic: [unclosed\n")
    loaded = load(str(f), {})
    assert loaded.source == str(f) and "line" in loaded.error
    assert load(str(tmp_path / "missing.yaml"), {}).error.startswith("can't read")


def test_robots_list_with_shared_defaults():
    robots, _ = from_dict(yaml.safe_load("""
battery: {topic: battery_state, warn_below: 30}
robots:
  - robot: {name: amr-1, namespace: /amr1}
  - robot: {name: amr-2, namespace: /amr2}
    battery: {warn_below: 40}
"""), {})
    assert [r.name for r in robots] == ["amr-1", "amr-2"]
    assert robots[0].value("battery").topic == "/amr1/battery_state"
    assert robots[0].value("battery").rule.warn_below == 30
    assert robots[1].value("battery").rule.warn_below == 40


def test_robots_must_be_told_apart():
    found = problems("robots:\n  - robot: {name: a}\n  - robot: {name: b}\n")
    assert any("same namespace and domain_id" in p for p in found)
    assert any("domain_id" in p for p in problems("robot: {domain_id: 400}"))


def test_extract_from_dicts_and_objects():
    msg = SimpleNamespace(twist=SimpleNamespace(twist=SimpleNamespace(linear=SimpleNamespace(x=0.4))),
                          ranges=[1.0, 2.0])
    assert extract(msg, "twist.twist.linear.x") == 0.4
    assert extract(msg, "ranges[1]") == 2.0
    assert extract({"a": [{"b": 3}]}, "a[0].b") == 3
    with pytest.raises(LookupError, match="no field “charge”"):
        extract({"percentage": 1}, "charge")


def test_suggestions():
    seen = ["/robot1/battery_state", "/odom", "/robot1/odom", "/diagnostics"]
    assert suggest("/battery_state", seen)[0] == "/robot1/battery_state"
    assert suggest("/diagnostic", seen)[0] == "/diagnostics"


# ---- the monitor with a mapping -------------------------------------------

def sim_monitor():
    log, clock = Log(), Clock()
    robots, _ = mapping.load_file(str(PRESETS / "styri-sim.yaml"), {})
    m = Monitor(log, robots[0], clock=clock)
    m.discovered([("/battery_state", "sensor_msgs/msg/BatteryState"), ("/robot_status", "std_msgs/msg/String"),
                  ("/odom", "nav_msgs/msg/Odometry"), ("/diagnostics", "diagnostic_msgs/msg/DiagnosticArray")],
                 lambda t: True)
    return m, log, clock


def feed_sim(m, clock, status="IDLE", speed=0.0, temp=33.0, present=True, seconds=1):
    for _ in range(seconds * 10):
        clock.t += 0.1
        for topic, msg in (("/battery_state", {"percentage": 0.9, "voltage": 24.9, "temperature": temp,
                                              "present": present}),
                           ("/robot_status", {"data": status}),
                           ("/odom", {"twist": {"twist": {"linear": {"x": speed}}}}),
                           ("/diagnostics", {"status": [{"name": "cpu_monitor", "level": b"\x00", "message": "OK",
                                                         "values": [{"key": "temperature", "value": "52.0"}]}]})):
            m.message(topic, b"x")
            m.mapped(topic, msg)


def test_status_and_custom_fields():
    m, log, clock = sim_monitor()
    feed_sim(m, clock, speed=0.42)
    snap = m.evaluate()
    assert snap["health"]["level"] == "ok"
    assert snap["status"]["value"] == "IDLE" and snap["status"]["kind"] == "text"
    fields = {f["label"]: f for f in snap["fields"]}
    assert fields["Speed"]["value"] == 0.42 and fields["Speed"]["unit"] == "m/s"
    assert fields["Battery present"]["value"] is True
    assert all(r["status"] == "ok" for r in snap["mappings"]), snap["mappings"]

    feed_sim(m, clock, status="LOW_BATTERY")
    snap = m.evaluate()
    assert snap["health"] == {"level": "warn", "line": "Status reports LOW_BATTERY."}
    assert "Status: LOW_BATTERY" in log.msgs()

    feed_sim(m, clock, temp=47.0)
    snap = m.evaluate()
    assert snap["health"]["line"] == "Battery temperature high — 47 °C."
    assert "Battery temperature above 45 °C" in log.msgs()

    feed_sim(m, clock, present=False)
    assert m.evaluate()["health"] == {"level": "fault", "line": "Battery present reports false."}


def test_unlisted_text_is_plain():
    m, _, clock = sim_monitor()
    feed_sim(m, clock, status="DOCKING")
    snap = m.evaluate()
    assert snap["status"]["value"] == "DOCKING" and snap["status"]["level"] == "ok"


def test_custom_fields_go_stale_after_3_s_by_default():
    m, _, clock = sim_monitor()
    feed_sim(m, clock)
    for _ in range(35):  # everything but /odom keeps publishing for 3.5 s
        clock.t += 0.1
        m.mapped("/battery_state", {"percentage": 0.9, "voltage": 24.9, "temperature": 33.0, "present": True})
        m.mapped("/robot_status", {"data": "IDLE"})
    snap = m.evaluate()
    speed = next(f for f in snap["fields"] if f["label"] == "Speed")
    assert speed["stale"] and not snap["battery"]["stale"]
    assert snap["health"]["line"] == "Robot healthy. One value is stale — see Speed."
    row = next(r for r in snap["mappings"] if r["label"] == "Speed")
    assert row["status"] == "stale" and "stale after 3 s" in row["detail"]


def test_missing_topic_and_wrong_field_are_reported():
    log, clock = Log(), Clock()
    r = robot("robot: {namespace: /robot1}\nbattery: {topic: battery_state, percentage: charge_level}")
    m = Monitor(log, r, clock=clock)
    m.discovered([("/battery_state", "sensor_msgs/msg/BatteryState")], lambda t: True)
    rows = {row["key"]: row for row in m.evaluate()["mappings"]}
    assert rows["battery"]["status"] == "waiting"  # still discovering
    clock.t += MISSING_GRACE + 1
    rows = {row["key"]: row for row in m.evaluate()["mappings"]}
    assert rows["battery"]["status"] == "missing"
    assert rows["battery"]["suggestions"] == ["/battery_state"]
    assert "Mapped topic /robot1/battery_state not found. Did you mean /battery_state?" in log.msgs()

    m.discovered([("/robot1/battery_state", "sensor_msgs/msg/BatteryState")], lambda t: True)
    m.message("/robot1/battery_state", b"x")
    m.mapped("/robot1/battery_state", {"percentage": 0.5, "voltage": 24.0})
    rows = {row["key"]: row for row in m.evaluate()["mappings"]}
    assert rows["battery"]["status"] == "error" and "no field “charge_level”" in rows["battery"]["detail"]
    assert rows["voltage"]["status"] == "ok"
    assert any(msg.startswith("Battery: can't read /robot1/battery_state · charge_level") for msg in log.msgs())


def test_host_cpu_by_choice_is_labelled():
    m = Monitor(Log(), robot("cpu_temperature: {topic: host}"), clock=Clock())
    m.host_vitals(48.0)
    snap = m.evaluate()
    assert snap["cpu_temp"]["label"] == "Styri host CPU" and snap["cpu_temp"]["value"] == 48.0
    row = next(r for r in snap["mappings"] if r["key"] == "cpu_temp")
    assert row["status"] == "ok" and row["topic"] is None


# ---- Nav2: latest goal, labels, when_empty, never stale -------------------

GOALS = "/navigate_to_pose/_action/status"


def nav2_monitor():
    log, clock = Log(), Clock()
    m = Monitor(log, load(str(PRESETS / "nav2.yaml")).robots[0], clock=clock)
    m.discovered([(GOALS, "action_msgs/msg/GoalStatusArray"), ("/battery_state", "sensor_msgs/msg/BatteryState"),
                  ("/odom", "nav_msgs/msg/Odometry")], lambda t: True)
    return m, log, clock


def goals(*statuses):
    return {"status_list": [{"status": s} for s in statuses]}


def test_negative_index_is_the_last_item():
    assert mapping.parse_path("status_list[-1].status") == ["status_list", -1, "status"]
    assert extract(goals(2, 4, 6), "status_list[-1].status") == 6
    with pytest.raises(mapping.NoItem, match="the list is empty"):
        extract(goals(), "status_list[-1].status")


def test_nav2_preset_shows_the_latest_goal_by_name():
    m, log, clock = nav2_monitor()
    # On the network, nothing published yet (no goal since Nav2 started): IDLE.
    snap = m.evaluate()
    assert snap["status"]["value"] == "IDLE" and snap["status"]["label"] == "Navigation"
    assert next(r for r in snap["mappings"] if r["key"] == "status")["status"] == "ok"

    m.message(GOALS, b"x")
    m.mapped(GOALS, goals(4, 2))
    assert m.evaluate()["status"]["value"] == "NAVIGATING"

    m.mapped(GOALS, goals(4, 6))
    snap = m.evaluate()
    assert snap["status"]["value"] == "FAILED"
    assert snap["health"] == {"level": "warn", "line": "Navigation reports FAILED."}

    m.mapped(GOALS, goals())  # the old goals expired
    assert m.evaluate()["status"]["value"] == "IDLE"

    clock.t += 3600  # published on change only: never stale, and doesn't hold up NO DATA
    snap = m.evaluate()
    assert not snap["status"]["stale"] and snap["status"]["value"] == "IDLE"


def test_unlisted_raw_values_show_as_they_are():
    m, _, _ = nav2_monitor()
    m.mapped(GOALS, goals(9))
    assert m.evaluate()["status"]["value"] == "9"


def test_labels_and_when_empty_are_for_text():
    assert problems("status: {topic: s, kind: bool, labels: {1: ON}}") == \
        ["status: labels and when_empty are for text fields (kind: text)"]
    assert problems("fields: [{label: A, topic: a, field: data, when_empty: X}]") == \
        ["fields[0]: labels and when_empty are for text fields (kind: text)"]
    assert problems("status: {topic: s, labels: [ON]}") == \
        ["status.labels: expected value: word pairs, like {4: SUCCEEDED}"]


def test_stale_after_false_means_never():
    r = robot("status: {topic: s, stale_after: false}\nfields: [{label: A, topic: a, field: data, stale_after: false}]")
    assert r.value("status").stale_after is None and r.value("field1").stale_after is None
    assert problems("status: {topic: s, stale_after: true}") == ["status.stale_after: expected a number"]


def test_unknown_type_points_to_overlays():
    log, clock = Log(), Clock()
    m = Monitor(log, robot("status: {topic: mode}"), clock=clock)
    m.discovered([("/mode", "acme_msgs/msg/Mode"), ("/other", "acme_msgs/msg/Other")], lambda t: False)
    row = next(r for r in m.evaluate()["mappings"] if r["key"] == "status")
    assert row["status"] == "error" and row["missing_type"] == "acme_msgs/msg/Mode"
    assert "overlay" in row["detail"]

    from styri_bridge import check
    assert check.unknown_types([m]) == {"acme_msgs": 2}
    lines = []
    check.report(m.robot, [row], lines.append)
    assert "its type, acme_msgs/msg/Mode, isn't installed here" in lines[1]
    assert lines[2].strip().startswith("Add the acme_msgs package as a message overlay: https://")
