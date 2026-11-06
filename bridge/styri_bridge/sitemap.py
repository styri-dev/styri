"""The site: a background map, a node graph, and where a robot's pose lands on them.

Graph file (JSON):
    {"nodes": [{"id": "n1", "x": 0, "y": 0, "map_id": "floor1"}, ...],
     "edges": [{"id": "e1", "start": "n1", "end": "n2"}, ...]}

Nodes may carry a `"name"` for people to read. Edges run both ways unless
`"directed": true`. No ROS imports.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import logging
import math
import threading
from dataclasses import dataclass
from pathlib import Path

from .occupancy import to_svg

logger = logging.getLogger(__name__)


ON_EDGE = 0.5  # metres: this close to an edge is on the graph


class GraphError(ValueError):
    """The graph file can't be used. The message says why."""


@dataclass(frozen=True)
class Node:
    id: str
    x: float
    y: float
    map_id: str
    name: str | None = None  # what people call it; the id is what the protocol uses


@dataclass(frozen=True)
class Edge:
    id: str
    start: str
    end: str
    directed: bool = False


class Graph:
    def __init__(self, nodes: list[Node], edges: list[Edge]):
        self.nodes = {n.id: n for n in nodes}
        self.edges = edges
        if len(self.nodes) != len(nodes):
            raise GraphError("two nodes have the same id")
        if len({e.id for e in edges}) != len(edges):
            raise GraphError("two edges have the same id")
        self._next: dict[str, list[tuple[str, Edge]]] = {n: [] for n in self.nodes}
        for e in edges:
            for end in (e.start, e.end):
                if end not in self.nodes:
                    raise GraphError(f"edge {e.id} uses node {end}, which isn't in the graph")
            self._next[e.start].append((e.end, e))
            if not e.directed:
                self._next[e.end].append((e.start, e))

    @classmethod
    def from_dict(cls, data: object) -> "Graph":
        try:
            nodes = [Node(str(n["id"]), float(n["x"]), float(n["y"]), str(n["map_id"]), str(n["name"]) if n.get("name") else None)
                     for n in data["nodes"]]
            edges = [Edge(str(e["id"]), str(e["start"]), str(e["end"]), bool(e.get("directed", False)))
                     for e in data["edges"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise GraphError(f"nodes need id, x, y and map_id; edges need id, start and end ({exc})") from None
        if not all(math.isfinite(n.x) and math.isfinite(n.y) for n in nodes):
            raise GraphError("node positions must be numbers")
        return cls(nodes, edges)

    @classmethod
    def load(cls, path: str) -> "Graph":
        try:
            return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
        except OSError as exc:
            raise GraphError(f"can't read {path}: {exc.strerror or exc}") from None
        except json.JSONDecodeError as exc:
            raise GraphError(f"not valid JSON (line {exc.lineno})") from None

    def to_dict(self) -> dict:
        return {"nodes": [{"id": n.id, "x": n.x, "y": n.y, "map_id": n.map_id, **({"name": n.name} if n.name else {})}
                          for n in self.nodes.values()],
                "edges": [{"id": e.id, "start": e.start, "end": e.end, **({"directed": True} if e.directed else {})}
                          for e in self.edges]}

    def maps(self) -> set[str]:
        return {n.map_id for n in self.nodes.values()}

    def nearest(self, x: float, y: float, map_id: str | None = None) -> Node | None:
        """The closest node, on one map if given."""
        pool = [n for n in self.nodes.values() if map_id is None or n.map_id == map_id]
        return min(pool, key=lambda n: math.hypot(n.x - x, n.y - y), default=None)

    def off_edges(self, x: float, y: float) -> float:
        """How far a point is from the nearest edge, in metres; infinity with no edges."""
        best = math.inf
        for e in self.edges:
            a, b = self.nodes[e.start], self.nodes[e.end]
            dx, dy = b.x - a.x, b.y - a.y
            span = dx * dx + dy * dy
            t = max(0.0, min(1.0, ((x - a.x) * dx + (y - a.y) * dy) / span)) if span else 0.0
            best = min(best, math.hypot(x - a.x - t * dx, y - a.y - t * dy))
        return best

    def off_graph(self, x: float, y: float, limit: float) -> float | None:
        """Metres from the route, for a point that's off every edge and more than `limit` from a node."""
        near = self.nearest(x, y)
        off = self.off_edges(x, y)
        if near is None or not self.edges or off <= ON_EDGE or math.hypot(near.x - x, near.y - y) <= limit:
            return None
        return off

    def route(self, start: str, goal: str) -> tuple[list[Node], list[Edge]] | None:
        """Shortest path as (nodes, edges), or None if there's no way there."""
        if start not in self.nodes or goal not in self.nodes:
            return None
        best = {start: 0.0}
        came: dict[str, tuple[str, Edge]] = {}
        queue = [(0.0, start)]
        while queue:
            dist, here = heapq.heappop(queue)
            if here == goal:
                break
            if dist > best[here]:
                continue
            a = self.nodes[here]
            for there, edge in self._next[here]:
                b = self.nodes[there]
                d = dist + math.hypot(a.x - b.x, a.y - b.y)
                if d < best.get(there, math.inf):
                    best[there], came[there] = d, (here, edge)
                    heapq.heappush(queue, (d, there))
        if goal != start and goal not in came:
            return None
        nodes, edges, here = [self.nodes[goal]], [], goal
        while here != start:
            here, edge = came[here]
            nodes.append(self.nodes[here])
            edges.append(edge)
        return nodes[::-1], edges[::-1]


def to_site(pose: dict | None, offset: tuple[float, float, float]) -> dict | None:
    """A robot's own pose, placed on the site map by its offset (x, y, theta)."""
    if pose is None or offset == (0.0, 0.0, 0.0):
        return pose
    ox, oy, ot = offset
    c, s = math.cos(ot), math.sin(ot)
    return {**pose, "x": ox + c * pose["x"] - s * pose["y"], "y": oy + s * pose["x"] + c * pose["y"],
            "theta": pose["theta"] + ot}


def from_site(x: float, y: float, theta: float, offset: tuple[float, float, float]) -> tuple[float, float, float]:
    """A point on the site map, in the robot's own frame."""
    ox, oy, ot = offset
    c, s = math.cos(ot), math.sin(ot)
    return c * (x - ox) + s * (y - oy), -s * (x - ox) + c * (y - oy), theta - ot


# ---- the background ------------------------------------------------------

@dataclass(frozen=True)
class Background:
    """An image, and where it sits: `scale` metres per pixel, `origin` the bottom-left corner in metres."""
    path: str
    scale: float
    origin: tuple[float, float]
    negate: bool = False
    occupied: float = 0.65
    free: float = 0.196


def load_background(path: str) -> Background:
    """A ROS map.yaml, or a small YAML with `image`, `resolution` and `origin`. Raises GraphError."""
    import yaml
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        image = Path(path).parent / data["image"]
        return Background(str(image), float(data["resolution"]), (float(data["origin"][0]), float(data["origin"][1])),
                          bool(data.get("negate", 0)), float(data.get("occupied_thresh", 0.65)), float(data.get("free_thresh", 0.196)))
    except OSError as exc:
        raise GraphError(f"can't read {path}: {exc.strerror or exc}") from None
    except (KeyError, IndexError, TypeError, ValueError, yaml.YAMLError):
        raise GraphError(f"{path}: needs image, resolution and origin") from None


def read_pgm(raw: bytes) -> tuple[int, int, int, bytes]:
    """A binary PGM (P5) as (width, height, top value, pixels)."""
    import re
    match = re.match(rb"P5(?:\s|#[^\n]*\n)+(\d+)(?:\s|#[^\n]*\n)+(\d+)(?:\s|#[^\n]*\n)+(\d+)\s", raw)
    if not match:
        raise GraphError("not a binary PGM image")
    width, height, top = (int(g) for g in match.groups())
    if top > 255:
        raise GraphError("16-bit PGM images aren't supported")
    pixels = raw[match.end():match.end() + width * height]
    if len(pixels) < width * height:
        raise GraphError("the PGM image is cut short")
    return width, height, top, pixels


def pgm_to_png(raw: bytes) -> bytes:
    """A binary PGM, which browsers can't show, as a greyscale PNG."""
    import struct
    import zlib
    width, height, _, pixels = read_pgm(raw)

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    rows = b"".join(b"\0" + pixels[y * width:(y + 1) * width] for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))


class Site:
    """What the panel draws: the graph and the background. A bad file is a note, never fatal."""

    def __init__(self, map_path: str | None, graph_path: str | None):
        self.graph_path = graph_path
        self.graph: Graph | None = None
        self.background: Background | None = None
        self.problems: list[str] = []
        self.clean: bytes | None = None  # a scan, drawn clean; made once, off the event loop
        if graph_path and not Path(graph_path).exists():
            self.graph = Graph([], [])  # not drawn yet: the editor makes the file
        elif graph_path:
            try:
                self.graph = Graph.load(graph_path)
            except GraphError as exc:
                self.problems.append(f"Node graph not used: {exc}")
        if map_path:
            try:
                self.background = load_background(map_path)
            except GraphError as exc:
                self.problems.append(f"Site map not used: {exc}")
        if self.background and self.background.path.lower().endswith(".pgm"):
            threading.Thread(target=self.clean_scan, daemon=True).start()

    def clean_scan(self) -> None:
        """Until this is done, or if it can't be, the scan shows as it is."""
        b = self.background
        try:
            width, height, top, pixels = read_pgm(Path(b.path).read_bytes())
            self.clean = to_svg(pixels, width, height, top, b.scale, negate=b.negate, occupied=b.occupied, free=b.free)
        except (OSError, GraphError, ValueError) as exc:
            logger.warning("Site map shown as it is: %s", exc)

    def image(self) -> tuple[bytes, str] | None:
        """(bytes, content type) for the browser, or None."""
        if self.background is None:
            return None
        if self.clean is not None:
            return self.clean, "image/svg+xml"
        raw = Path(self.background.path).read_bytes()
        if raw[:2] == b"P5":
            return pgm_to_png(raw), "image/png"
        name = self.background.path.lower()
        if name.endswith(".svg"):
            return raw, "image/svg+xml"
        return raw, "image/jpeg" if name.endswith((".jpg", ".jpeg")) else "image/png"

    @property
    def version(self) -> str | None:
        """Changes with the graph's content: how the editor knows someone else saved first."""
        if self.graph is None:
            return None
        return hashlib.sha256(json.dumps(self.graph.to_dict(), sort_keys=True).encode()).hexdigest()[:16]

    def describe(self) -> dict:
        b = self.background
        return {"graph": self.graph.to_dict() if self.graph else None, "version": self.version,
                "background": {"url": "/site/map", "scale": b.scale, "origin": list(b.origin)} if b else None,
                "editable": bool(self.graph_path), "problems": self.problems}

    def save(self, graph: Graph) -> None:
        """The editor's save: the same JSON, written whole, so a crash can't leave half a file. Raises OSError."""
        if not self.graph_path:
            raise OSError("no graph file: set site.graph in styri.yaml")
        tmp = Path(self.graph_path + ".tmp")
        tmp.write_text(json.dumps(graph.to_dict(), indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.graph_path)
        self.graph = graph
