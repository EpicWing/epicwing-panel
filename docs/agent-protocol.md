# Agent protocol (version 1)

The agent connects **outbound** to the panel, so a node needs no open port.
Endpoint: `ws://<panel>/api/agent/ws` (use `wss://` behind a reverse proxy for remote nodes).

## Enrollment (once)

`POST /api/agent/enroll` with `{"token", "public_key", "agent_version"}`.
`public_key` is the raw 32-byte Ed25519 public key, base64 encoded. The private key never
leaves the node. The token is single use and valid for one hour.

## Connection

1. Panel to agent: `{"type": "challenge", "nonce": "<base64, 32 random bytes>"}`
2. Agent to panel: `{"type": "auth", "node_id": "<uuid>", "signature": "<base64>"}`
   - `signature` is the Ed25519 signature over the bytes
     `"epicwing-agent-auth-v1\n" + node_id + "\n" + nonce`
   - `node_id` is the lowercase UUID string returned by the enrollment, `nonce` the decoded bytes
3. Panel to agent: `{"type": "auth_ok"}`. On failure the panel closes with code 1008.
   The node is already marked online when `auth_ok` is sent.
4. Agent to panel, every 10 seconds:
   `{"type": "heartbeat", "cpu_total", "ram_total_mb", "disk_total_mb",
   "cpu_percent", "ram_used_mb", "disk_used_mb", "agent_version"}`
5. Panel to agent: `{"type": "heartbeat_ack"}`, or `{"type": "error", ...}` for an invalid message.

## Rules

- Messages are text frames with at most 16 KiB.
- The panel must receive the auth message within 10 seconds and a message at least every
  30 seconds, otherwise it closes the connection.
- One connection per node, a newer connection replaces the older one (close code 1012).
- A node counts as online while its last heartbeat is at most 30 seconds old.
- After 10 failed authentications from one IP within 15 minutes the panel refuses that IP.

## Commands (panel to agent)

1. Panel to agent: `{"type": "command", "id": "<hex>", "action": "<action>", "params": {...}}`
   with `action` one of `container.create`, `container.start`, `container.stop`,
   `container.remove`. The agent validates `params` itself and never runs anything else.
2. Agent to panel: `{"type": "result", "id": "<same id>", "ok": true, "data": {...}}`
   or `{"type": "result", "id": "...", "ok": false, "error": "<reason>"}`. The panel does
   not acknowledge results.

- The panel accepts a result only from the node the command was sent to and waits at most
  90 seconds. A closed or replaced connection fails all open commands of that node.
- Commands and heartbeats share the connection, so the agent must read while it waits.
