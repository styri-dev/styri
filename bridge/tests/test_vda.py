"""styri-vda without a broker: messages in, messages out, the graph."""

import asyncio
import json

import pytest

from styri_bridge import mapping
from styri_bridge.model import Live, RobotView
from styri_bridge.monitor import Monitor
from styri_bridge.sitemap import Graph, GraphError, from_site, to_site
from styri_bridge.vda import broker, orders, schema
from styri_bridge.vda.client import VdaClient, VdaError

GRAPH = {"nodes": [{"id": "a", "x": 0, "y": 0, "map_id": "m"}, {"id": "b", "x": 5, "y": 0, "map_id": "m"},
                   {"id": "c", "x": 5, "y": 5, "map_id": "m"}, {"id": "lone", "x": 9, "y": 9, "map_id": "m"}],
         "edges": [{"id": "ab", "start": "a", "end": "b"}, {"id": "bc", "start": "b", "end": "c"}]}


class Log:
    def __init__(self):
        self.events = []

    def add(self, kind, msg, source):
        self.events.append((kind, msg))


def header(n=0):
    return {"headerId": n, "timestamp": "2026-11-04T10:00:00.000Z", "version": "2.0.0", "manufacturer": "acme",
            "serialNumber": "SN1"}


def state(**over):
    return {**header(), "orderId": "", "orderUpdateId": 0, "lastNodeId": "a", "lastNodeSequenceId": 0, "nodeStates": [],
            "edgeStates": [], "driving": False, "actionStates": [], "operatingMode": "AUTOMATIC", "errors": [],
            "batteryState": {"batteryCharge": 80.0, "charging": False},
            "safetyState": {"eStop": "NONE", "fieldViolation": False},
            "agvPosition": {"x": 0.0, "y": 0.0, "theta": 0.0, "mapId": "m", "positionInitialized": True}, **over}


class Mqtt:
    def __init__(self):
        self.sent = []

    async def publish(self, topic, payload, qos=0):
        self.sent.append((topic, json.loads(payload)))


def client(control=True, actions=mapping.INSTANT_ACTIONS):
    robot = mapping.RobotMap("agv", values=(mapping.Value("battery", "Battery", "state", "batteryState.batteryCharge",
                                                          "%", "number", 1.0, mapping.Rule(warn_below=25), 35.0),),
                             diagnostics_topic=None, stale_after=35.0,
                             link=mapping.Link(protocol="vda5050", manufacturer="acme", serial="SN1",
                                               instant_actions=actions))
    view = RobotView(0, "agv", "0", Monitor(Log(), robot))
    c = VdaClient([view], mapping.Settings(), Log(), Graph.from_dict(GRAPH), control=control)
    c.mqtt = Mqtt()
    return c, view


def feed(c, kind, msg, who="acme/SN1"):
    c.on_message(f"uagv/v2/{who}/{kind}", json.dumps(msg).encode())


def test_state_feeds_the_model():
    c, view = client()
    feed(c, "state", state(driving=True, nodeStates=[{"nodeId": "b", "sequenceId": 2, "released": True}],
                           orderId="o1", paused=False))
    live = view.live
    assert live.online and live.driving and live.task_state == "active" and live.task_id == "o1"
    assert live.route == ["b"] and live.pose["map_id"] == "m"
    snap = view.monitor.evaluate()
    assert snap["battery"]["value"] == 80.0 and snap["health"]["level"] == "ok"


def test_errors_set_the_verdict_and_stops_are_reported():
    c, view = client()
    feed(c, "state", state(errors=[{"errorType": "lidar", "errorLevel": "FATAL", "errorDescription": "blocked"}]))
    snap = view.monitor.evaluate()
    assert snap["health"]["level"] == "fault" and "blocked" in snap["health"]["line"]
    feed(c, "state", state(safetyState={"eStop": "MANUAL", "fieldViolation": False}))
    assert view.live.vehicle_stop and view.monitor.evaluate()["health"]["level"] == "fault"


def test_no_order_to_cancel_is_not_a_fault():
    c, view = client()
    feed(c, "state", state(errors=[{"errorType": "noOrderToCancel", "errorLevel": "WARNING"}]))
    assert view.monitor.evaluate()["health"]["level"] == "ok"


def test_the_first_message_sets_the_version_we_speak():
    c, view = client()
    feed(c, "connection", {**header(), "connectionState": "ONLINE"})
    asyncio.run(c.pause(view))
    assert sent(c, "instantActions")[0]["version"] == "2.0.0"


def test_connection_lost_means_stale():
    c, view = client()
    feed(c, "connection", {**header(), "connectionState": "ONLINE"})
    assert view.live.online is True
    feed(c, "connection", {**header(1), "connectionState": "CONNECTIONBROKEN"})
    assert view.live.online is False


def test_invalid_messages_are_flagged_not_fatal():
    c, view = client()
    feed(c, "state", {"nonsense": True})
    c.on_message("uagv/v2/acme/SN1/state", b"\xff not json")
    feed(c, "state", {**state(), "driving": "yes"})
    assert view.live.warnings == ["Invalid state messages from this robot"]
    feed(c, "state", state())
    assert view.live.warnings == []


def test_unconfigured_vehicles_are_noted():
    c, _ = client()
    feed(c, "state", state(), who="other/SN9")
    assert ("other", "SN9") in c.unconfigured


def sent(c, topic):
    return [m for t, m in c.mqtt.sent if t.endswith("/" + topic)]


def test_view_only_can_not_publish():
    c, view = client(control=False)
    with pytest.raises(VdaError):
        asyncio.run(c.pause(view))
    assert c.mqtt.sent == []


def test_order_follows_the_graph_and_validates():
    c, view = client()
    feed(c, "state", state())
    asyncio.run(c.goal(view, node_id="c"))
    (order,) = sent(c, "order")
    assert schema.problems("order", order) == []
    assert [n["nodeId"] for n in order["nodes"]] == ["a", "b", "c"] and [n["sequenceId"] for n in order["nodes"]] == [0, 2, 4]
    assert [e["edgeId"] for e in order["edges"]] == ["ab", "bc"] and [e["sequenceId"] for e in order["edges"]] == [1, 3]
    assert order["version"] == "2.0.0"  # speaks the vehicle's version
    assert c.mqtt.sent[0][0] == "uagv/v2/acme/SN1/order"


def position(x, y):
    return {"x": x, "y": y, "theta": 0.0, "mapId": "m", "positionInitialized": True}


def test_after_a_stop_partway_along_an_edge_the_order_starts_where_the_vehicle_is():
    c, view = client()
    # Last node a, but stopped most of the way to b.
    feed(c, "state", state(agvPosition=position(3.8, 0.0)))
    asyncio.run(c.goal(view, node_id="c"))
    (order,) = sent(c, "order")
    assert schema.problems("order", order) == []
    assert [n["nodeId"] for n in order["nodes"]] == ["b", "c"]
    assert order["nodes"][0]["nodePosition"]["allowedDeviationXY"] > 1.2  # takes in the 1.2 m to b
    assert order["nodes"][1]["nodePosition"]["allowedDeviationXY"] == 0.5


def test_stopped_mid_edge_on_a_long_edge_is_still_on_the_graph():
    c, view = client()
    long_graph = Graph.from_dict({"nodes": [{"id": "a", "x": 0, "y": 0, "map_id": "m"}, {"id": "b", "x": 10, "y": 0, "map_id": "m"}],
                                  "edges": [{"id": "ab", "start": "a", "end": "b"}]})
    c.graph = long_graph
    feed(c, "state", state(agvPosition=position(4.0, 0.1)))  # 4 m from either node, but on the edge
    asyncio.run(c.goal(view, node_id="b"))
    assert [n["nodeId"] for n in sent(c, "order")[0]["nodes"]] == ["a", "b"]
    assert long_graph.off_edges(5, 3) == 3


def test_too_far_from_the_graph_to_join_it():
    c, view = client()
    feed(c, "state", state(agvPosition=position(20.0, 20.0)))
    with pytest.raises(VdaError) as refused:
        asyncio.run(c.goal(view, node_id="a"))
    assert str(refused.value) == ("Robot is 15.6 m from the nearest node. "
                                  "Move it onto the route with its own controls, then retry.")
    assert c.mqtt.sent == []


def test_the_distance_is_a_setting():
    c, view = client()
    c.settings = mapping.Settings(max_off_graph=30.0)
    feed(c, "state", state(agvPosition=position(-20.0, 0.0)))
    asyncio.run(c.goal(view, node_id="c"))
    assert len(sent(c, "order")) == 1
    assert mapping.Settings().max_off_graph == 2.0


def test_a_rejected_order_does_not_show_the_cancelled_one_as_done():
    c, view = client()
    feed(c, "state", state(orderId="o1", nodeStates=[{"nodeId": "b", "sequenceId": 2, "released": True}]))
    asyncio.run(c.cancel(view))
    feed(c, "state", state(orderId="o1"))
    asyncio.run(c.goal(view, node_id="b"))
    feed(c, "state", state(orderId="o1"))  # the vehicle turned the new order down
    assert view.live.task_state == "idle"


def test_a_click_snaps_to_the_nearest_node():
    c, view = client()
    feed(c, "state", state())
    asyncio.run(c.goal(view, x=4.6, y=0.4))
    assert sent(c, "order")[0]["nodes"][-1]["nodeId"] == "b"


@pytest.mark.parametrize("kwargs, needle", [({"node_id": "nope"}, "no node"), ({"node_id": "lone"}, "no route")])
def test_bad_goals_say_why(kwargs, needle):
    c, view = client()
    feed(c, "state", state())
    with pytest.raises(VdaError, match=needle):
        asyncio.run(c.goal(view, **kwargs))
    assert c.mqtt.sent == []


def test_second_order_waits_for_the_first():
    c, view = client()
    feed(c, "state", state(orderId="o1", nodeStates=[{"nodeId": "b", "sequenceId": 2, "released": True}]))
    with pytest.raises(VdaError, match="already has an order"):
        asyncio.run(c.goal(view, node_id="c"))


def test_header_ids_go_up_per_topic():
    c, view = client()
    feed(c, "state", state())

    async def go():
        await c.pause(view)
        await c.resume(view)
        await c.goal(view, node_id="b")
    asyncio.run(go())
    assert [m["headerId"] for m in sent(c, "instantActions")] == [0, 1] and sent(c, "order")[0]["headerId"] == 0


def test_operator_stop_is_one_message_in_order():
    async def go():
        c, view = client()
        feed(c, "state", state(driving=False))
        await c.operator_stop(view)
        await asyncio.sleep(0)
        return c
    c = asyncio.run(go())
    (msg,) = sent(c, "instantActions")
    assert [a["actionType"] for a in msg["actions"]] == ["startPause", "cancelOrder"]
    assert all(a["blockingType"] == "NONE" for a in msg["actions"]) and schema.problems("instantActions", msg) == []


def test_operator_stop_retries_until_stopped_and_never_unpauses(monkeypatch):
    monkeypatch.setattr("styri_bridge.vda.client.STOP_RETRY", 0.01)

    async def go():
        c, view = client()
        feed(c, "state", state(driving=True, orderId="o1"))
        await c.operator_stop(view)
        await asyncio.sleep(0.05)
        count = len(sent(c, "instantActions"))
        feed(c, "state", state(driving=False, paused=True, orderId="o1"))
        await asyncio.sleep(0.05)
        return c, count
    c, count = asyncio.run(go())
    assert count >= 2
    assert len(sent(c, "instantActions")) <= count + 1
    ids = [a["actionId"] for m in sent(c, "instantActions") for a in m["actions"]]
    assert len(ids) == len(set(ids))
    assert all(a["actionType"] != "stopPause" for m in sent(c, "instantActions") for a in m["actions"])


def test_a_held_cancel_is_shown_and_a_cancelled_order_is_idle():
    c, view = client()
    feed(c, "state", state(orderId="o1", nodeStates=[{"nodeId": "b", "sequenceId": 2, "released": True}]))
    asyncio.run(c.cancel(view))
    feed(c, "state", state(orderId="o1", paused=True, actionStates=[
        {"actionId": "x", "actionType": "cancelOrder", "actionStatus": "RUNNING"}]))
    assert "Held, cancel pending" in view.live.warnings
    assert view.live.task_state == "idle"


def test_whitelist_blocks_what_the_file_leaves_out():
    c, view = client(actions=("cancelOrder",))
    with pytest.raises(VdaError, match="startPause"):
        asyncio.run(c.pause(view))
    assert c.mqtt.sent == []


def test_a_factsheet_without_start_pause_warns():
    c, view = client()
    feed(c, "factsheet", {"protocolFeatures": {"agvActions": [{"actionType": "cancelOrder"}]}})
    assert any("startPause" in w for w in view.live.warnings)


def test_invalid_outgoing_is_never_published():
    c, view = client()
    feed(c, "state", state())
    with pytest.raises(VdaError, match="invalid"):
        asyncio.run(c.send(c.vehicle(view), "order", {"orderId": "x"}))
    assert c.mqtt.sent == []


def test_graph_routes_and_refuses_bad_files():
    g = Graph.from_dict(GRAPH)
    nodes, edges = g.route("c", "a")
    assert [n.id for n in nodes] == ["c", "b", "a"] and len(edges) == 2
    assert g.route("a", "lone") is None and g.route("a", "a")[0][0].id == "a"
    with pytest.raises(GraphError, match="isn't in the graph"):
        Graph.from_dict({"nodes": [], "edges": [{"id": "e", "start": "a", "end": "b"}]})
    with pytest.raises(GraphError):
        Graph.from_dict({"nodes": [{"id": "a"}], "edges": []})


def test_non_numbers_are_refused():
    with pytest.raises(GraphError, match="numbers"):
        Graph.from_dict({"nodes": [{"id": "a", "x": float("nan"), "y": 0, "map_id": "m"}], "edges": []})


def test_a_graph_file_not_made_yet_is_an_empty_graph(tmp_path):
    from styri_bridge.sitemap import Site
    site = Site(None, str(tmp_path / "new.json"))
    assert site.graph.nodes == {} and site.problems == []
    site.save(Graph.from_dict(GRAPH))
    assert Site(None, str(tmp_path / "new.json")).graph.route("a", "c")
    assert not list(tmp_path.glob("*.tmp"))


def test_directed_edges_run_one_way():
    g = Graph.from_dict({"nodes": GRAPH["nodes"][:2], "edges": [{"id": "ab", "start": "a", "end": "b", "directed": True}]})
    assert g.route("a", "b") and g.route("b", "a") is None


def test_offsets_round_trip():
    off = (1.0, 2.0, 1.5708)
    p = to_site({"x": 1.0, "y": 0.0, "theta": 0.0, "map_id": "m"}, off)
    assert abs(p["x"] - 1) < 1e-3 and abs(p["y"] - 3) < 1e-3
    x, y, t = from_site(p["x"], p["y"], p["theta"], off)
    assert abs(x - 1) < 1e-6 and abs(y) < 1e-6 and abs(t) < 1e-6


def test_the_bundled_broker_never_bridges_and_scopes_each_vehicle():
    robot = mapping.RobotMap("agv", link=mapping.Link(protocol="vda5050", manufacturer="acme", serial="SN1", username="u"))
    conf = broker.config(mapping.Broker(bind="10.0.0.5"), "uagv", [robot], "/tmp/x")
    assert "listener 1883 127.0.0.1\nallow_anonymous true" in conf
    assert "listener 1883 10.0.0.5\nallow_anonymous false" in conf
    assert "connection " not in conf and "address " not in conf
    assert "topic readwrite uagv/+/acme/SN1/#" in broker.acl("uagv", [robot])


def test_localhost_only_without_a_bind():
    assert broker.config(mapping.Broker(), "uagv", [], "/tmp/x").count("listener ") == 1


def test_check_lines_for_a_good_and_a_silent_vehicle():
    from styri_bridge.check import vehicle_lines
    c, view = client()
    v = c.vehicle(view)
    assert [ok for ok, _, _ in vehicle_lines(v, 5)] == [False, False, True, False]
    feed(c, "connection", {**header(), "connectionState": "ONLINE"})
    feed(c, "state", state())
    feed(c, "factsheet", {"protocolFeatures": {"agvActions": []}})
    ok = {what: passed for passed, what, _ in vehicle_lines(v, 5)}
    assert ok == {"Connection": True, "State": True, "Schema": False, "Factsheet": True}  # that factsheet is invalid


def test_check_graph_and_control_lines(tmp_path):
    from styri_bridge.check import control_lines, graph_lines
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(GRAPH))
    lines, graph = graph_lines(str(path), {"m"})
    assert all(ok for ok, _, _ in lines) and graph
    assert not graph_lines(str(path), {"other"})[0][1][0]
    assert not graph_lines(str(tmp_path / "nope.json"), set())[0][0][0]

    robot = mapping.RobotMap("a", link=mapping.Link(cmd_vel="/a/cmd_vel", nav2_action="/a/nav"))
    monitor = Monitor(Log(), robot)
    monitor.discovered([("/a/cmd_vell", "t")], lambda _t: True)
    lines = control_lines(mapping.Settings(control=True), [robot], {"a": monitor}, str(tmp_path / "x.db"), env={})
    ok = {what: (passed, detail) for passed, what, detail in lines}
    assert not ok["Admin password"][0]
    assert not ok["a cmd_vel"][0] and "Did you mean /a/cmd_vell" in ok["a cmd_vel"][1]
    assert not ok["a Nav2 action"][0]
    monitor.discovered([("/a/cmd_vel", "t"), ("/a/nav/_action/status", "t")], lambda _t: True)
    lines = control_lines(mapping.Settings(control=True), [robot], {"a": monitor}, "x", env={"STYRI_ADMIN_PASSWORD": "x"})
    assert all(passed for passed, _, _ in lines)
