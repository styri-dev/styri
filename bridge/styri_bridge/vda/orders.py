"""Build the VDA 5050 messages Styri sends. No I/O."""

from __future__ import annotations

import datetime
import uuid

from ..sitemap import Edge, Node, from_site

# Instant actions Styri sends, all non-blocking: they must never wait on the vehicle.
BLOCKING = "NONE"
DEVIATION = 0.5  # metres


def timestamp() -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def action(action_type: str) -> dict:
    return {"actionType": action_type, "actionId": str(uuid.uuid4()), "blockingType": BLOCKING}


def instant(*types: str) -> dict:
    """The body of an instantActions message; list order is the order the vehicle runs them."""
    return {"actions": [action(t) for t in types]}


def order(order_id: str, nodes: list[Node], edges: list[Edge], offset=(0.0, 0.0, 0.0),
          start_deviation: float = 0.0) -> dict:
    """A route, all released: nodes take even sequence ids and edges odd ones.

    The graph is in site coordinates; the vehicle gets them in its own frame. The
    first node must take in where the vehicle stands, by `start_deviation` metres.
    """
    def position(n: Node, deviation: float) -> dict:
        x, y, _ = from_site(n.x, n.y, 0.0, offset)
        return {"x": x, "y": y, "mapId": n.map_id, "allowedDeviationXY": deviation}

    body_nodes = [{"nodeId": n.id, "sequenceId": 2 * i, "released": True, "actions": [],
                   "nodePosition": position(n, max(DEVIATION, start_deviation) if i == 0 else DEVIATION)}
                  for i, n in enumerate(nodes)]
    body_edges = [{"edgeId": e.id, "sequenceId": 2 * i + 1, "released": True, "startNodeId": nodes[i].id,
                   "endNodeId": nodes[i + 1].id, "actions": []} for i, e in enumerate(edges)]
    return {"orderId": order_id, "orderUpdateId": 0, "nodes": body_nodes, "edges": body_edges}
