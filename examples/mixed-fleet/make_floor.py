#!/usr/bin/env python3
"""Draw the demo's floor as an occupancy grid: site/floor.pgm, in the format a ROS 2 map uses.

It's made up, like the robots: a small warehouse around the demo's route graph, with walls,
racks, pillars and sensor speckle. Seeded, so running this again gives the same file.
"""

import random
from pathlib import Path

RES = 0.05
X0, Y0, X1, Y1 = -3.0, -3.0, 17.0, 9.0  # metres
W, H = round((X1 - X0) / RES), round((Y1 - Y0) / RES)
FREE, WALL, UNKNOWN = 254, 120, 215
rng = random.Random(5050)
grid = [[UNKNOWN] * W for _ in range(H)]


def cell(x, y):
    return round((x - X0) / RES), H - 1 - round((y - Y0) / RES)


def fill(x0, y0, x1, y1, value):
    a, b = cell(x0, y1)
    c, d = cell(x1, y0)
    for j in range(max(0, b), min(H, d + 1)):
        for i in range(max(0, a), min(W, c + 1)):
            grid[j][i] = value


def wall(x0, y0, x1, y1):
    """A rough line, as a scan sees one: a cell thick or two, and wandering a little."""
    steps = int(max(abs(x1 - x0), abs(y1 - y0)) / RES)
    wobble = 0
    for k in range(steps + 1):
        if rng.random() < 0.08:
            wobble = max(-1, min(1, wobble + rng.choice((-1, 1))))
        t = k / max(1, steps)
        i, j = cell(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
        for di in range(2):
            a, b = (i + di, j + wobble) if x0 == x1 else (i + wobble, j + di)
            if 0 <= a < W and 0 <= b < H and rng.random() > 0.03:
                grid[b][a] = WALL


# The floor, then the building around it, with doors and a dock.
fill(-2.4, -2.4, 16.4, 8.4, FREE)
for x0, x1 in ((-2.4, 4.0), (5.6, 10.0), (11.6, 16.4)):
    wall(x0, -2.4, x1, -2.4)
wall(-2.4, 8.4, 6.0, 8.4)
wall(7.6, 8.4, 16.4, 8.4)
wall(-2.4, -2.4, -2.4, 3.0)
wall(-2.4, 4.6, -2.4, 8.4)
wall(16.4, -2.4, 16.4, 8.4)

# An office in the corner, and racks of pallets clear of the lanes (y 2 and 6, x 2, 8 and 12).
wall(-2.4, 7.0, 0.4, 7.0)
wall(0.4, 7.0, 0.4, 8.4)
for row_y in (3.3, 4.7):
    for x_start, x_end in ((3.0, 7.0), (9.0, 11.0)):
        wall(x_start, row_y, x_end, row_y)
        x = x_start
        while x <= x_end + 0.01:
            fill(x - 0.05, row_y - 0.05, x + 0.05, row_y + 0.05, WALL)
            x += 1.0
        x = x_start + 0.15
        while x < x_end - 0.5:
            if rng.random() < 0.8:
                wall(x, row_y + 0.2, x + 0.7, row_y + 0.2)
                wall(x, row_y - 0.2, x + 0.7, row_y - 0.2)
            x += 1.0
for x_start, x_end, y in ((3.0, 7.0, 7.6), (9.0, 15.5, 7.6), (3.0, 7.0, 0.6), (9.0, 15.5, 0.6), (13.6, 15.6, 3.3), (13.6, 15.6, 4.7)):
    wall(x_start, y, x_end, y)
    x = x_start
    while x <= x_end + 0.01:
        fill(x - 0.05, y - 0.05, x + 0.05, y + 0.05, WALL)
        x += 1.0
for x, y in ((5.0, -1.0), (10.0, -1.0), (15.0, -1.0)):
    fill(x - 0.15, y - 0.15, x + 0.15, y + 0.15, WALL)

# What a scanner leaves behind: stray returns, and patches it never saw behind the racks.
walls = [(i, j) for j in range(H) for i in range(W) if grid[j][i] == WALL]
for _ in range(500):
    i, j = rng.choice(walls)
    i, j = i + rng.randint(-5, 5), j + rng.randint(-5, 5)
    if 0 <= i < W and 0 <= j < H and grid[j][i] == FREE:
        grid[j][i] = 170
for _ in range(90):
    i, j = rng.randrange(W), rng.randrange(H)
    if grid[j][i] == FREE:
        grid[j][i] = 170
for x0, y0, x1, y1 in ((3.2, 3.5, 6.8, 4.5), (9.2, 3.5, 10.8, 4.5), (13.8, 3.5, 15.4, 4.5)):
    fill(x0, y0, x1, y1, UNKNOWN)

site = Path(__file__).parent / "site"
(site / "floor.pgm").write_bytes(f"P5\n{W} {H}\n255\n".encode() + bytes(v for row in grid for v in row))
(site / "floor.yaml").write_text(
    f"image: floor.pgm\nresolution: {RES}\norigin: [{X0}, {Y0}, 0.0]\nnegate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n")
