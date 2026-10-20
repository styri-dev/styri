import math

from styri_sim.model import IDLE, LOW_BATTERY, MOVING, SimRobot


def run(robot, seconds, start=0.0, dt=0.02, drive=None):
    t = start
    while t < start + seconds:
        if drive:
            robot.command_velocity(*drive, t)
        robot.step(dt, t)
        t += dt
    return t


def test_cmd_vel_accelerates_then_deadman_stops():
    r = SimRobot()
    t = run(r, 2.0, drive=(0.5, 0.0))
    assert r.status == MOVING
    assert math.isclose(r.v, 0.5, abs_tol=1e-6)  # reached after the accel ramp
    assert r.x > 0.6
    run(r, 2.0, start=t)  # commands stop
    assert r.v == 0.0 and r.status == IDLE


def test_faults():
    r = SimRobot()
    before = r.battery_reading()
    r.inject_fault("overheat", 0)
    r.inject_fault("battery_sag", 0)
    assert r.cpu_temperature() > 75
    assert r.battery_reading()["voltage"] < before["voltage"] - 2
    assert r.diagnostics()[0][1] == 1  # cpu_monitor WARN
    r.inject_fault("motor_fault", 0)
    assert ("motor_right", 2, "Overcurrent", {}) in r.diagnostics()
    r.inject_fault("battery:18", 0)
    assert abs(r.battery - 0.18) < 1e-9
    r.inject_fault("silence:5", 10)
    assert r.silent(12) and not r.silent(16)
    r.inject_fault("clear", 20)
    assert not (r.overheat or r.motor_fault or r.battery_sag)


def test_battery_drains_faster_when_driving_and_reports_low():
    idle, driving = SimRobot(), SimRobot()
    run(idle, 60)
    run(driving, 60, drive=(0.6, 0))
    assert driving.battery < idle.battery < 0.95
    low = SimRobot(battery=0.05)
    run(low, 0.1)
    assert low.status == LOW_BATTERY
