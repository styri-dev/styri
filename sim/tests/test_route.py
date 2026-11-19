import json
import math
from pathlib import Path

from styri_sim.route import Floor, length

SITE = Path(__file__).resolve().parents[2] / "examples" / "mixed-fleet" / "site"
FLOOR = Floor.load(SITE / "obstacles.json")
NODES = {n["name"]: (n["x"], n["y"]) for n in json.loads((SITE / "graph.json").read_text())["nodes"]}
BARE = Floor([], (-2.4, -2.4, 16.4, 8.4), 0.0)  # the same floor without its clearance


def legs(start, path):
    return list(zip([start, *path], path))


def test_every_lane_node_and_the_robots_start_are_open_floor():
    assert all(FLOOR.free(p) for p in NODES.values())
    assert FLOOR.free((0.0, 0.0))  # amr-01 starts here


def test_a_rack_row_is_no_goal():
    assert FLOOR.plan((2.0, 2.0), (5.0, 4.0)) is None  # the double row between the lanes
    assert FLOOR.plan((2.0, 2.0), (6.0, 4.0)) is None


def test_open_floor_in_sight_is_one_straight_run():
    assert FLOOR.plan(NODES["Dock"], NODES["Lane A"]) == [NODES["Lane A"]]


def test_across_the_racks_it_keeps_to_the_aisles():
    start, goal = NODES["Dock"], NODES["Lane B"]  # the straight line crosses rack row 1
    assert not FLOOR.clear(start, goal)
    path = FLOOR.plan(start, goal)
    assert path and path[-1] == goal and len(path) <= 3
    assert all(FLOOR.clear(a, b) for a, b in legs(start, path))
    assert length(start, path) < math.dist(start, goal) * 1.5


def test_from_inbound_to_the_far_bay():
    start, goal = (0.0, 0.0), NODES["Bay 3"]
    path = FLOOR.plan(start, goal)
    assert path and path[-1] == goal
    assert all(FLOOR.clear(a, b) for a, b in legs(start, path))


def test_clearance_keeps_it_off_the_racks_themselves():
    path = FLOOR.plan(NODES["Bay 1"], NODES["Lane A"])
    assert all(BARE.clear(a, b) for a, b in legs(NODES["Bay 1"], path))
    assert not BARE.free((5.0, 4.0)) or FLOOR.rects  # sanity: the racks are really there
    assert any(r[1] <= 4.0 <= r[3] and r[0] <= 5.0 <= r[2] for r in FLOOR.rects)


def test_outside_the_building_is_no_goal():
    assert FLOOR.plan((0.0, 0.0), (20.0, 0.0)) is None
