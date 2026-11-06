"""A noisy scan comes out as clean shapes, and a bad one still shows."""

import math
import re

from styri_bridge.occupancy import to_svg
from styri_bridge.sitemap import Site

FREE, WALL, UNKNOWN = 254, 0, 205
W, H = 120, 80


def scan():
    grid = [[UNKNOWN] * W for _ in range(H)]
    for y in range(5, 75):
        for x in range(5, 115):
            grid[y][x] = FREE
    for x in range(5, 115):  # a wall, two cells thick
        grid[5][x] = grid[6][x] = WALL
    return grid


def shapes(svg: bytes) -> tuple[list[str], list[str]]:
    known, occupied = re.findall(rb' d="([^"]*)"', svg)
    return [m for m in known.decode().split("M") if m], [m for m in occupied.decode().split("M") if m]


def render(grid, **kw):
    return to_svg(bytes(v for row in grid for v in row), W, H, 255, 0.05, **kw)


def test_specks_go_and_the_wall_stays():
    grid = scan()
    for x, y in ((30, 40), (60, 50), (90, 30), (31, 8)):
        grid[y][x] = WALL
    _, occupied = shapes(render(grid))
    assert len(occupied) == 1


def test_a_wall_with_gaps_and_lumps_is_one_straight_shape():
    grid = scan()
    grid[5][40] = grid[6][40] = grid[5][41] = grid[6][41] = FREE
    grid[7][70] = grid[7][71] = WALL
    _, occupied = shapes(render(grid))
    assert len(occupied) == 1
    assert occupied[0].count("L") <= 8


def test_a_pillar_stays():
    grid = scan()
    for y in range(40, 46):
        for x in range(60, 66):
            grid[y][x] = WALL
    assert len(shapes(render(grid))[1]) == 2


def test_a_thin_wall_at_an_odd_angle_stays():
    grid = scan()
    for k in range(60):
        x, y = 30 + round(k * math.cos(0.4)), 20 + round(k * math.sin(0.4))
        grid[y][x] = WALL
    assert len(shapes(render(grid))[1]) == 2


def test_small_holes_in_the_floor_close_and_unknown_stays_clear():
    grid = scan()
    grid[40][40] = grid[41][41] = UNKNOWN
    known, _ = shapes(render(grid))
    assert len(known) == 1  # one outline, no holes; what's outside it isn't drawn


def test_thresholds_and_negate_come_from_the_map():
    grid = [[255 - v for v in row] for row in scan()]
    assert len(shapes(render(grid, negate=True))[1]) == 1
    assert not shapes(render(scan(), occupied=1.0))[1]


def test_the_same_size_so_it_lines_up():
    assert render(scan()).startswith(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}"'.encode())


def write_map(tmp_path, body: bytes) -> str:
    (tmp_path / "m.pgm").write_bytes(body)
    (tmp_path / "m.yaml").write_text("image: m.pgm\nresolution: 0.05\norigin: [0, 0, 0]\n")
    return str(tmp_path / "m.yaml")


def test_the_site_serves_the_clean_scan(tmp_path):
    pgm = f"P5\n{W} {H}\n255\n".encode() + bytes(v for row in scan() for v in row)
    site = Site(write_map(tmp_path, pgm), None)
    site.clean_scan()
    body, kind = site.image()
    assert kind == "image/svg+xml" and body.startswith(b"<svg")


def test_a_scan_that_cant_be_cleaned_still_shows(tmp_path, monkeypatch):
    pgm = f"P5\n{W} {H}\n255\n".encode() + bytes(v for row in scan() for v in row)
    monkeypatch.setattr("styri_bridge.sitemap.to_svg", lambda *a, **k: (_ for _ in ()).throw(ValueError("no")))
    site = Site(write_map(tmp_path, pgm), None)
    site.clean_scan()
    assert site.image()[1] == "image/png"


def test_a_vector_floor_is_served_as_it_is(tmp_path):
    (tmp_path / "f.svg").write_text("<svg/>")
    (tmp_path / "f.yaml").write_text("image: f.svg\nresolution: 0.05\norigin: [0, 0, 0]\n")
    assert Site(str(tmp_path / "f.yaml"), None).image() == (b"<svg/>", "image/svg+xml")
