"""A path around the floor's obstacles, for the simulated robot's NavigateToPose server.

The floor is a list of rectangles the robot can't drive through (racks, walls, pallets),
from the demo's site/obstacles.json. Plain Python, no ROS: a grid A* with the obstacles
grown by the robot's clearance, then straightened, so the robot drives in straight runs
along the open aisles instead of through the racks. A goal on an obstacle has no path,
as Nav2 refuses a goal inside one.
"""

from __future__ import annotations

import heapq
import json
import math
from pathlib import Path

CELL = 0.1  # metres
CLEARANCE = 0.4  # metres kept from any obstacle
STEP = 0.05  # metres between the points a straight run is checked at

Point = tuple[float, float]
Rect = tuple[float, float, float, float]


class Floor:
    def __init__(self, rects: list[Rect], bounds: Rect, clearance: float = CLEARANCE):
        self.rects = [(x0 - clearance, y0 - clearance, x1 + clearance, y1 + clearance) for x0, y0, x1, y1 in rects]
        self.bounds = bounds

    @classmethod
    def load(cls, path: str | Path, clearance: float = CLEARANCE) -> Floor:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls([tuple(r) for r in data["obstacles"]], tuple(data["bounds"]), clearance)

    def free(self, p: Point) -> bool:
        x0, y0, x1, y1 = self.bounds
        if not (x0 <= p[0] <= x1 and y0 <= p[1] <= y1):
            return False
        return not any(a <= p[0] <= c and b <= p[1] <= d for a, b, c, d in self.rects)

    def clear(self, a: Point, b: Point) -> bool:
        """A straight run from a to b touches no obstacle."""
        n = max(1, math.ceil(math.dist(a, b) / STEP))
        return all(self.free((a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n)) for i in range(n + 1))

    def plan(self, start: Point, goal: Point) -> list[Point] | None:
        """The points to drive through, ending at the goal, or None when the goal can't be reached."""
        if not self.free(goal):
            return None
        if self.clear(start, goal):
            return [goal]
        x0, y0 = self.bounds[0], self.bounds[1]
        cell = lambda p: (round((p[0] - x0) / CELL), round((p[1] - y0) / CELL))  # noqa: E731
        centre = lambda c: (x0 + c[0] * CELL, y0 + c[1] * CELL)  # noqa: E731
        s, g = cell(start), cell(goal)
        # The robot may stand closer to an obstacle than the clearance: it can always leave its own cell.
        came: dict = {s: None}
        cost = {s: 0.0}
        todo = [(math.dist(s, g), s)]
        while todo:
            _, c = heapq.heappop(todo)
            if c == g:
                break
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    n = (c[0] + dx, c[1] + dy)
                    if n == c or not self.free(centre(n)):
                        continue
                    new = cost[c] + math.hypot(dx, dy)
                    if new < cost.get(n, math.inf):
                        cost[n], came[n] = new, c
                        heapq.heappush(todo, (new + math.dist(n, g), n))
        if g not in came:
            return None
        cells = []
        c = g
        while c is not None:
            cells.append(c)
            c = came[c]
        points = [start] + [centre(c) for c in reversed(cells[1:-1])] + [goal]
        return self._straighten(points)

    def _straighten(self, points: list[Point]) -> list[Point]:
        """Keep only the corners: from each point, the farthest one in plain sight."""
        out, i = [], 0
        while i < len(points) - 1:
            j = len(points) - 1
            while j > i + 1 and not self.clear(points[i], points[j]):
                j -= 1
            out.append(points[j])
            i = j
        return out


def length(start: Point, path: list[Point]) -> float:
    return sum(math.dist(a, b) for a, b in zip([start, *path], path))
