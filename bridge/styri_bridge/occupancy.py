"""A scanned occupancy map, drawn clean: an SVG the panel can show at any zoom.

Scans are noisy: stray returns, gaps in walls, patches the sensor never saw. This keeps what's
really there. Specks go, small gaps close, and the rest is traced into solid shapes, with stairs
and sensor wobble straightened out. Only the picture changes; nothing here steers a robot.

Rows are Python ints, a bit per cell (the leftmost cell is the top bit), so the whole-map steps
are a handful of big-integer operations and only the outlines cost time per cell.
"""

from __future__ import annotations

KNOWN, OCCUPIED = "#ffffff", "#a4a9b0"  # light theme; the panel darkens every floor the same way
SPECK = 0.02   # m²: an occupied patch smaller than this is noise
WOBBLE = 0.75  # cells: outlines may move this far to run straight
RUN = 6        # cells: a line this long is structure; what sticks out of one may be a bump
BUMP = 16      # cells: what sticks out, up to this size, is a bump


def _masks(pixels: bytes, width: int, height: int, top: int, negate: bool, occupied: float, free: float) -> tuple[list[int], list[int]]:
    """(occupied, free) rows, by the thresholds in map.yaml."""
    def p(v: int) -> float:
        return min(v, top) / top if negate else (top - min(v, top)) / top
    occ = bytes(49 if p(v) > occupied else 48 for v in range(256))
    fre = bytes(49 if p(v) < free else 48 for v in range(256))
    rows = [pixels[y * width:(y + 1) * width] for y in range(height)]
    return [int(r.translate(occ), 2) for r in rows], [int(r.translate(fre), 2) for r in rows]


def _grow(rows: list[int], width: int) -> list[int]:
    """Every cell next to a set cell, diagonals too."""
    full = (1 << width) - 1
    wide = [(r | r << 1 | r >> 1) & full for r in rows]
    last = len(rows) - 1
    return [wide[y] | (wide[y - 1] if y else 0) | (wide[y + 1] if y < last else 0) for y in range(len(rows))]


def _flip(rows: list[int], width: int) -> list[int]:
    full = (1 << width) - 1
    return [~r & full for r in rows]


def _close(rows: list[int], width: int, times: int) -> list[int]:
    """Fill gaps up to 2 × `times` cells across."""
    grown = rows
    for _ in range(times):
        grown = _grow(grown, width)
    grown = _flip(grown, width)
    for _ in range(times):
        grown = _grow(grown, width)
    return [r | c for r, c in zip(rows, _flip(grown, width))]


def _open(rows: list[int], width: int, times: int) -> list[int]:
    """Drop anything up to 2 × `times` cells across."""
    return _flip(_close(_flip(rows, width), width, times), width)


def _bits(row: int, width: int) -> list[int]:
    """The columns set in a row."""
    text = format(row, f"0{width}b")
    found, at = [], text.find("1")
    while at >= 0:
        found.append(at)
        at = text.find("1", at + 1)
    return found


def _patches(rows: list[int], width: int) -> list[list[int]]:
    """The connected patches, each a list of cell numbers (see `_around`)."""
    stride = width + 2  # a spare column each side, so neighbours can't wrap a row
    left = {(y + 1) * stride + x + 1 for y, r in enumerate(rows) for x in _bits(r, width)}
    patches = []
    while left:
        seed = left.pop()
        patch, stack = [seed], [seed]
        while stack:
            for there in _around(stack.pop(), stride):
                if there in left:
                    left.remove(there)
                    patch.append(there)
                    stack.append(there)
        patches.append(patch)
    return patches


def _around(cell: int, stride: int) -> tuple[int, ...]:
    return (cell - stride - 1, cell - stride, cell - stride + 1, cell - 1, cell + 1,
            cell + stride - 1, cell + stride, cell + stride + 1)


def _without(rows: list[int], cells: list[int], width: int) -> None:
    for cell in cells:
        y, x = divmod(cell, width + 2)
        rows[y - 1] &= ~(1 << (width - x))


def _despeck(rows: list[int], width: int, smallest: int) -> list[int]:
    """Without the connected patches under `smallest` cells."""
    kept = list(rows)
    for patch in _patches(rows, width):
        if len(patch) < smallest:
            _without(kept, patch, width)
    return kept


def _join(rows: list[int], width: int) -> list[int]:
    """Cells touching only at a corner share a side, so a thin diagonal traces as one shape."""
    full = (1 << width) - 1
    below = rows[1:] + [0]
    return [r | (r >> 1 | r << 1) & b & full & ~(r & b) for r, b in zip(rows, below)]


def _shift(rows: list[int], dx: int, dy: int, width: int) -> list[int]:
    """Every set cell moved by (dx, dy)."""
    full = (1 << width) - 1
    moved = [(r >> dx if dx >= 0 else r << -dx) & full for r in rows]
    blank = [0] * abs(dy)
    return (blank + moved[:len(moved) - dy]) if dy > 0 else (moved[-dy:] + blank) if dy < 0 else moved


def _lines(rows: list[int], dx: int, dy: int, length: int, width: int) -> list[int]:
    """The cells on a run of at least `length` in one direction."""
    starts = rows
    for k in range(1, length):
        starts = [a & b for a, b in zip(starts, _shift(rows, -dx * k, -dy * k, width))]
    runs = starts
    for k in range(1, length):
        runs = [a | b for a, b in zip(runs, _shift(starts, dx * k, dy * k, width))]
    return runs


def _debump(rows: list[int], width: int) -> list[int]:
    """Without the small lumps on walls. What joins two straight pieces is a wall at an odd angle."""
    straight = [0] * len(rows)
    for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
        straight = [a | b for a, b in zip(straight, _lines(rows, dx, dy, RUN, width))]
    piece = {cell: i for i, patch in enumerate(_patches(straight, width)) for cell in patch}
    kept = list(rows)
    for patch in _patches([r & ~s for r, s in zip(rows, straight)], width):
        joins = {piece[n] for cell in patch for n in _around(cell, width + 2) if n in piece}
        if len(patch) < BUMP and len(joins) < 2:
            _without(kept, patch, width)
    return kept


def _edges(rows: list[int], width: int) -> dict[tuple[int, int], list[tuple[int, int]]]:
    """Each boundary edge of the set cells, directed so the cells are on its right."""
    edges: dict[tuple[int, int], list[tuple[int, int]]] = {}

    def add(a: tuple[int, int], b: tuple[int, int]) -> None:
        edges.setdefault(a, []).append(b)

    for y, r in enumerate(rows):
        above = rows[y - 1] if y else 0
        below = rows[y + 1] if y + 1 < len(rows) else 0
        for x in _bits(r & ~above, width):
            add((x, y), (x + 1, y))
        for x in _bits(r & ~below, width):
            add((x + 1, y + 1), (x, y + 1))
        for x in _bits(r & ~(r >> 1), width):  # nothing to the left
            add((x, y + 1), (x, y))
        for x in _bits(r & ~(r << 1), width):  # nothing to the right
            add((x + 1, y), (x + 1, y + 1))
    return edges


def _loops(rows: list[int], width: int) -> list[list[tuple[int, int]]]:
    """The closed outlines, as corner points in half cells, each corner cut to run diagonally."""
    edges = _edges(rows, width)
    loops = []
    while edges:
        start = next(iter(edges))
        path, here, heading = [start], start, None
        while True:
            options = edges[here]
            there = options.pop()
            if options and heading:  # two ways on: turn right, so touching corners stay apart
                right = (here[0] - heading[1], here[1] + heading[0])
                if right in options:
                    options[options.index(right)] = there
                    there = right
            if not options:
                del edges[here]
            heading = (there[0] - here[0], there[1] - here[1])
            here = there
            if here == start:
                break
            path.append(here)
        # The middle of every unit edge: stairs become diagonals, corners lose half a cell.
        n = len(path)
        mids = [(path[i][0] + path[(i + 1) % n][0], path[i][1] + path[(i + 1) % n][1]) for i in range(n)]
        loops.append(mids)
    return loops


def _straight(points: list[tuple[int, int]], tolerance: float) -> list[tuple[int, int]]:
    """Fewer points: nothing moves further than `tolerance` (Douglas-Peucker, on a closed loop)."""
    if len(points) < 4:
        return points
    far = max(range(len(points)), key=lambda i: (points[i][0] - points[0][0]) ** 2 + (points[i][1] - points[0][1]) ** 2)
    keep = {0, far}
    spans = [(0, far), (far, len(points))]
    while spans:
        a, b = spans.pop()
        if b - a < 2:
            continue
        ax, ay = points[a]
        bx, by = points[b % len(points)]
        dx, dy = bx - ax, by - ay
        length = (dx * dx + dy * dy) ** 0.5 or 1.0
        worst, at = 0.0, -1
        for i in range(a + 1, b):
            d = abs(dy * (points[i][0] - ax) - dx * (points[i][1] - ay)) / length
            if d > worst:
                worst, at = d, i
        if worst > tolerance:
            keep.add(at)
            spans += [(a, at), (at, b)]
    return [points[i] for i in sorted(keep)]


def _square(points: list[tuple[int, int]], tolerance: float) -> list[tuple[int, int]]:
    """A side that's all but level or plumb is made so: walls and pillars mostly are."""
    fixed = [list(p) for p in points]
    for i, a in enumerate(fixed):
        b = fixed[(i + 1) % len(fixed)]
        for axis in (0, 1):
            if abs(a[axis] - b[axis]) <= tolerance < abs(a[1 - axis] - b[1 - axis]):
                a[axis] = b[axis] = (a[axis] + b[axis]) // 2
    return [(x, y) for x, y in fixed]


def _path(rows: list[int], width: int) -> str:
    parts = []
    for loop in _loops(rows, width):
        points = _square(_straight(loop, WOBBLE * 2), WOBBLE * 4)
        if len(points) >= 3:
            parts.append("M" + "L".join(f"{x} {y}" for x, y in points) + "Z")
    return "".join(parts)


def to_svg(pixels: bytes, width: int, height: int, top: int, resolution: float, *,
           negate: bool = False, occupied: float = 0.65, free: float = 0.196) -> bytes:
    """The map as an SVG with the same nominal size in pixels, so it lines up the same."""
    occ, fre = _masks(pixels, width, height, top, negate, occupied, free)
    smallest = max(3, round(SPECK / (resolution * resolution)))
    occ = _despeck(occ, width, 3)  # the worst first, or closing would glue them to the walls
    occ = _close(occ, width, 1)
    occ = _join(_despeck(_debump(occ, width), width, smallest), width)
    known = _open(_close([f | o for f, o in zip(fre, occ)], width, 3), width, 2)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width * 2} {height * 2}">'
            f'<path fill="{KNOWN}" fill-rule="evenodd" d="{_path(known, width)}"/>'
            f'<path fill="{OCCUPIED}" stroke="{OCCUPIED}" stroke-width="1.5" stroke-linejoin="round" fill-rule="evenodd" d="{_path(occ, width)}"/>'
            "</svg>").encode()
