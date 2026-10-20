from styri_bridge.monitor import NO_ROBOT_GRACE, Monitor


class Log:
    def __init__(self):
        self.events = []

    def add(self, kind, msg, source):
        self.events.append((kind, msg, source))

    def msgs(self):
        return [m for _, m, _ in self.events]


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make():
    log, clock = Log(), Clock()
    m = Monitor(log, "/battery_state", "/diagnostics", stale_after=5.0, clock=clock)
    m.discovered([("/battery_state", "sensor_msgs/msg/BatteryState"),
                  ("/diagnostics", "diagnostic_msgs/msg/DiagnosticArray"),
                  ("/odom", "nav_msgs/msg/Odometry"), ("/rosout", "rcl_interfaces/msg/Log")], lambda t: True)
    return m, log, clock


def feed(m, clock, battery=76.0, cpu=58.0, seconds=1, hz=10):
    for _ in range(int(seconds * hz)):
        clock.t += 1 / hz
        m.message("/odom", b"x")
        m.message("/battery_state", b"x")
        m.battery_state(battery, 24.5)
        m.diagnostics([("cpu_monitor", 0, "OK", {"temperature": str(cpu)})])


def test_ok_snapshot_and_rates():
    m, log, clock = make()
    feed(m, clock, seconds=3)
    snap = m.evaluate()
    assert snap["health"] == {"level": "ok", "line": "All systems normal."}
    assert snap["battery"]["value"] == 76.0 and snap["cpu_temp"]["source"] == "/diagnostics"
    odom = next(t for t in snap["topics"] if t["name"] == "/odom")
    assert 9.0 <= odom["hz"] <= 11.0
    assert snap["last_message"]["topic"] in ("/odom", "/battery_state")
    assert snap["robot_found"]
    assert "Bridge sees the robot · 4 topics" in log.msgs()


def test_battery_warn_fault_and_hysteresis():
    m, log, clock = make()
    feed(m, clock, battery=30)
    m.evaluate()
    feed(m, clock, battery=20)
    snap = m.evaluate()
    assert snap["health"]["level"] == "warn"
    assert snap["health"]["line"] == "Battery low — 20 %. Send to dock soon."
    assert ("warning", "Battery below 25 %", "/battery_state") in log.events
    assert "Robot status changed OK → WARNING" in log.msgs()
    # 26 % is inside the hysteresis band: still a warning, no flapping.
    feed(m, clock, battery=26)
    assert m.evaluate()["health"]["level"] == "warn"
    feed(m, clock, battery=8)
    snap = m.evaluate()
    assert snap["health"]["level"] == "fault" and "Battery below 10 %" in log.msgs()
    feed(m, clock, battery=60)
    assert m.evaluate()["health"]["level"] == "ok"
    assert log.msgs().count("Battery below 25 %") == 1


def test_cpu_temperature_and_host_fallback():
    m, log, clock = make()
    feed(m, clock, cpu=78)
    snap = m.evaluate()
    assert snap["health"]["line"] == "CPU temperature high — 78.0 °C."
    assert ("warning", "CPU temperature above 75 °C", "/diagnostics") in log.events
    # Without /diagnostics updates, the host's own sensor takes over.
    m.host_vitals(50.0)
    clock.t += 10
    snap = m.evaluate()
    assert snap["cpu_temp"]["source"] == "host" and snap["cpu_temp"]["value"] == 50.0


def test_diagnostics_error_is_a_fault():
    m, log, clock = make()
    feed(m, clock)
    m.diagnostics([("motor_right", 2, "Overcurrent", {})])
    snap = m.evaluate()
    assert snap["health"] == {"level": "fault", "line": "motor_right reports Overcurrent."}
    assert ("warning", "motor_right: Overcurrent", "/diagnostics") in log.events
    m.diagnostics([("motor_right", 0, "OK", {})])
    assert m.evaluate()["health"]["level"] == "ok"
    assert "motor_right back to OK" in log.msgs()


def test_stale_topic_and_no_data():
    m, log, clock = make()
    feed(m, clock, seconds=2)
    m.evaluate()
    clock.t += 6  # robot goes quiet
    snap = m.evaluate()
    assert snap["battery"]["stale"] and snap["health"]["level"] == "unknown"
    assert snap["health"]["line"].startswith("No data from the robot for ")
    assert "/odom stopped publishing" in log.msgs()
    feed(m, clock, seconds=1)
    snap = m.evaluate()
    assert snap["health"]["level"] == "ok"
    assert any(msg.startswith("/odom recovered after ") for msg in log.msgs())


def test_no_robot_topics():
    log, clock = Log(), Clock()
    m = Monitor(log, "/battery_state", "/diagnostics", clock=clock)
    m.discovered([("/rosout", "rcl_interfaces/msg/Log")], lambda t: True)
    snap = m.evaluate()
    assert not snap["robot_found"] and snap["seen"] == ["/rosout"]
    clock.t += NO_ROBOT_GRACE + 1
    m.evaluate()
    m.evaluate()
    assert log.msgs().count("No expected robot topics after 30 s") == 1


def test_hot_cpu_is_reported_once():
    m, log, clock = make()
    feed(m, clock, cpu=78)
    m.diagnostics([("cpu_monitor", 1, "High temperature", {"temperature": "78"})])
    snap = m.evaluate()
    assert snap["health"]["line"] == "CPU temperature high — 78.0 °C."
    assert not any("cpu_monitor" in msg for msg in log.msgs())


def make_with_min_voltage(min_voltage):
    log, clock = Log(), Clock()
    m = Monitor(log, "/battery_state", "/diagnostics", min_voltage=min_voltage, clock=clock)
    m.discovered([("/battery_state", "sensor_msgs/msg/BatteryState")], lambda t: True)
    return m, log, clock


def feed_voltage(m, clock, volts, battery=90.0, seconds=1):
    for _ in range(seconds * 10):
        clock.t += 0.1
        m.message("/battery_state", b"x")
        m.battery_state(battery, volts)
        m.host_vitals(50.0)


def test_voltage_drop_is_shown_but_not_judged_without_a_threshold():
    m, log, clock = make_with_min_voltage(None)
    feed_voltage(m, clock, 24.9)
    m.evaluate()
    feed_voltage(m, clock, 22.4)  # battery_sag: voltage falls, charge doesn't
    snap = m.evaluate()
    assert snap["voltage"]["value"] == 22.4
    assert snap["voltage"]["level"] == "ok" and snap["battery"]["level"] == "ok"
    assert snap["health"] == {"level": "ok", "line": "All systems normal."}
    assert not any("Voltage" in msg for msg in log.msgs())


def test_below_min_voltage_warns_until_clearly_recovered():
    m, log, clock = make_with_min_voltage(23.0)
    feed_voltage(m, clock, 24.9)
    assert m.evaluate()["health"]["level"] == "ok"
    feed_voltage(m, clock, 22.4)
    snap = m.evaluate()
    assert snap["voltage"]["level"] == "warn" and snap["battery"]["level"] == "ok"
    assert snap["health"] == {"level": "warn", "line": "Battery voltage low — 22.40 V, below 23.0 V."}
    assert ("warning", "Voltage below 23.0 V", "/battery_state") in log.events
    # 23.1 V is inside the 0.2 V hysteresis band: still a warning, no flapping.
    feed_voltage(m, clock, 23.1)
    assert m.evaluate()["voltage"]["level"] == "warn"
    feed_voltage(m, clock, 24.9)
    assert m.evaluate()["health"]["level"] == "ok"
    assert log.msgs().count("Voltage below 23.0 V") == 1


def test_min_voltage_from_env(monkeypatch):
    from styri_bridge.config import Config
    monkeypatch.delenv("STYRI_MIN_VOLTAGE", raising=False)
    assert Config.from_env().min_voltage is None
    monkeypatch.setenv("STYRI_MIN_VOLTAGE", "")
    assert Config.from_env().min_voltage is None
    monkeypatch.setenv("STYRI_MIN_VOLTAGE", "23.5")
    assert Config.from_env().min_voltage == 23.5
