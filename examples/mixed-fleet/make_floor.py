#!/usr/bin/env python3
"""Draw the demo's floor: site/floor.svg, clean vector art around the demo's route graph.

It's made up, like the robots. Seeded, so running this again gives the same file. The colours
are the light theme's; the panel turns a floor dark the same way for every map.
"""

import random
from pathlib import Path

RES = 0.05  # metres per pixel of the image's nominal size
X0, Y0, X1, Y1 = -3.0, -3.0, 17.0, 9.0  # metres
FLOOR, RACK, WALL, TEXT = "#ffffff", "#dfe2e6", "#868c94", "#6d737b"
rng = random.Random(5050)
out: list[str] = []


def px(x):
    return round((x - X0) * 100)


def py(y):
    return round((Y1 - y) * 100)


def rect(x0, y0, x1, y1, fill, extra=""):
    out.append(f'<rect x="{px(x0)}" y="{py(y1)}" width="{px(x1) - px(x0)}" height="{py(y0) - py(y1)}" fill="{fill}"{extra}/>')


def wall(*points):
    p = " ".join(f"{px(x)},{py(y)}" for x, y in points)
    out.append(f'<polyline points="{p}" fill="none" stroke="{WALL}" stroke-width="12" stroke-linecap="square" stroke-linejoin="miter"/>')


def rack(x0, x1, y, double):
    """A row of bays: uprights front and back, a pallet in most slots, a spine if it's back to back."""
    bay, depth = 0.5, 0.48
    backs = (y - depth, y + 0.02) if double else (y - depth / 2,)
    bays = round((x1 - x0) / bay)
    for k in range(bays):
        for b in backs:
            if rng.random() < 0.82:
                rect(x0 + k * bay + 0.06, b + 0.03, x0 + (k + 1) * bay - 0.06, b + depth - 0.03, RACK)
    rails = (y - depth - 0.03, y + depth + 0.03) if double else (y - depth / 2 - 0.03, y + depth / 2 + 0.03)
    for r in rails:
        out.append(f'<line x1="{px(x0)}" y1="{py(r)}" x2="{px(x1)}" y2="{py(r)}" stroke="{WALL}" stroke-width="2"/>')
        for k in range(bays + 1):
            rect(x0 + k * bay - 0.04, r - 0.04, x0 + k * bay + 0.04, r + 0.04, WALL)
    if double:
        out.append(f'<line x1="{px(x0)}" y1="{py(y)}" x2="{px(x1)}" y2="{py(y)}" stroke="{WALL}" stroke-width="2" opacity="0.6"/>')


def pallets(x0, y0, columns, rows):
    for i in range(columns):
        for j in range(rows):
            if rng.random() < 0.7:
                rect(x0 + i * 0.62, y0 + j * 0.62, x0 + i * 0.62 + 0.5, y0 + j * 0.62 + 0.5, RACK)


def label(x, y, text):
    out.append(f'<text x="{px(x)}" y="{py(y)}" fill="{TEXT}" font-family="ui-monospace, Menlo, Consolas, monospace" font-size="20" letter-spacing="1">{text}</text>')


# The floor, then the building around it, with doors and docks.
rect(-2.4, -2.4, 16.4, 8.4, FLOOR)
wall((4.0, -2.4), (-2.4, -2.4), (-2.4, 3.0))
wall((-2.4, 4.6), (-2.4, 8.4), (6.0, 8.4))
wall((7.6, 8.4), (16.4, 8.4), (16.4, -2.4), (11.6, -2.4))
wall((5.6, -2.4), (10.0, -2.4))
wall((-2.4, 7.0), (0.4, 7.0), (0.4, 7.6))  # the office, with its door

for x in (4.0, 10.0):  # dock levellers
    out.append(f'<rect x="{px(x + 0.1)}" y="{py(-2.46)}" width="140" height="48" fill="none" stroke="{WALL}" stroke-width="3"/>')
    rect(x + 0.45, -2.3, x + 1.15, -2.18, WALL)
for y in (0.6, 1.5):  # chargers
    rect(-2.3, y, -2.14, y + 0.5, WALL)
for x, y in ((1.0, -1.0), (7.0, -1.0), (15.0, 2.0)):  # pillars, clear of the lanes
    rect(x - 0.12, y - 0.12, x + 0.12, y + 0.12, WALL)

# Racks, clear of the lanes (y 2 and 6, x 2, 8 and 12).
for x0, x1 in ((3.0, 7.0), (9.0, 11.0), (13.5, 15.5)):
    rack(x0, x1, 4.0, True)
for x0, x1 in ((3.0, 7.0), (9.0, 15.5)):
    rack(x0, x1, 7.5, False)
    rack(x0, x1, 0.6, False)

pallets(-2.0, -2.0, 4, 2)
pallets(12.3, -2.0, 6, 2)
label(-2.1, 7.55, "OFFICE")
label(3.0, 5.0, "RACK ROWS 1–3")
label(-2.0, -0.55, "INBOUND")
label(4.1, -1.9, "DOCKS")
label(12.3, -0.55, "OUTBOUND")

W, H = round((X1 - X0) / RES), round((Y1 - Y0) / RES)
svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {px(X1)} {py(Y0)}">\n'
       + "\n".join(out) + "\n</svg>\n")
site = Path(__file__).parent / "site"
(site / "floor.svg").write_text(svg, encoding="utf-8")
(site / "floor.yaml").write_text(f"image: floor.svg\nresolution: {RES}\norigin: [{X0}, {Y0}, 0.0]\n")
