from tests.test_agent_ws import HEARTBEAT, WS_URL, _enroll_node, _login_agent


def test_detail_contains_history(client, user):
    node_id, key = _enroll_node(client, user)
    with client.websocket_connect(WS_URL) as ws:
        _login_agent(ws, node_id, key)
        for _ in range(2):
            ws.send_json(HEARTBEAT)
            assert ws.receive_json() == {"type": "heartbeat_ack"}
        history = client.get(f"/api/nodes/{node_id}").json()["history"]
        assert len(history) == 2
        assert history[0]["cpu"] == 12.5
        assert history[0]["ram"] == 25.0


def test_history_is_empty_without_connection(client, user):
    node_id, _key = _enroll_node(client, user)
    assert client.get(f"/api/nodes/{node_id}").json()["history"] == []
