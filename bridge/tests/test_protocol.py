import pytest

from styri_bridge import protocol


def test_parse_and_validate():
    assert protocol.parse('{"action": "PING", "t": 1}') == ("PING", {"action": "PING", "t": 1})
    assert protocol.ping({"t": 2.5}).t == 2.5
    assert protocol.select({"topic": "/odom"}).topic == "/odom"


@pytest.mark.parametrize("raw", ["nope", "[]", "{}", '{"action": 1}'])
def test_parse_rejects(raw):
    with pytest.raises(protocol.ProtocolError):
        protocol.parse(raw)


@pytest.mark.parametrize("data", [{"t": "x"}, {"t": True}, {"t": float("inf")}])
def test_ping_rejects(data):
    with pytest.raises(protocol.ProtocolError):
        protocol.ping(data)


@pytest.mark.parametrize("data", [{}, {"topic": ""}, {"topic": 3}, {"topic": "/" + "a" * 300}])
def test_select_rejects(data):
    with pytest.raises(protocol.ProtocolError):
        protocol.select(data)
