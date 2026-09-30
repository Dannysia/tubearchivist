"""steer the exit node of a tailscaled running alongside this container"""

import http.client
import json
import os
import random
import socket

import requests

# the paths the official tailscale image and the system use
SOCKET_CANDIDATES = [
    "/var/run/tailscale/tailscaled.sock",
    "/run/tailscale/tailscaled.sock",
    "/tmp/tailscaled.sock",
]

# the localapi needs a host header it recognises; never resolved
LOCAL_API_HOST = "local-tailscaled.sock"

SOCKET_TIMEOUT = 5
EGRESS_TIMEOUT = 10

MULLVAD_CHECK_URL = "https://am.i.mullvad.net/json"
FALLBACK_CHECK_URL = "https://api.ipify.org?format=json"


class TailscaleError(Exception):
    pass


def socket_path() -> str | None:
    for path in [os.environ.get("TS_SOCKET")] + SOCKET_CANDIDATES:
        if path and os.path.exists(path):
            return path

    return None


def is_available() -> bool:
    return socket_path() is not None


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, sock_path: str):
        super().__init__(LOCAL_API_HOST, timeout=SOCKET_TIMEOUT)
        self.sock_path = sock_path

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(SOCKET_TIMEOUT)
        sock.connect(self.sock_path)
        self.sock = sock


def _request(method: str, path: str, payload: dict | None = None) -> dict:
    sock_path = socket_path()
    if not sock_path:
        raise TailscaleError("no tailscaled socket in this container")

    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Host": LOCAL_API_HOST}
    if body:
        headers["Content-Type"] = "application/json"

    conn = _UnixConnection(sock_path)
    try:
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        raw, status = response.read(), response.status
    except OSError as err:
        raise TailscaleError(f"tailscaled unreachable: {err}") from err
    finally:
        conn.close()

    if status != 200:
        # 403 is the peer credential check: this process is not root in
        # the namespace tailscaled trusts
        detail = raw.decode(errors="replace").strip()
        raise TailscaleError(f"tailscaled returned {status}: {detail}")

    return json.loads(raw) if raw else {}


def _parse_node(peer: dict) -> dict:
    location = peer.get("Location") or {}

    return {
        "node_id": peer.get("ID"),
        "hostname": peer.get("HostName"),
        "country": location.get("Country"),
        "city": location.get("City"),
        "online": bool(peer.get("Online")),
        # only mullvad nodes report a Location
        "is_mullvad": bool(location),
    }


def get_state() -> dict:
    if not is_available():
        return {
            "available": False,
            "routes_all_traffic": False,
            "current": None,
            "nodes": [],
        }

    status = _request("GET", "/localapi/v0/status?peers=true")
    peers = list(status.get("Peer", {}).values())

    current = next(
        (_parse_node(i) for i in peers if i.get("ExitNode")),
        None,
    )
    nodes = [_parse_node(i) for i in peers if i.get("ExitNodeOption")]
    nodes.sort(
        key=lambda i: (
            i["country"] or "",
            i["city"] or "",
            i["hostname"] or "",
        )
    )

    return {
        "available": True,
        # a userspace tailscaled routes only its own proxy
        "routes_all_traffic": bool(status.get("TUN")),
        "current": current,
        "nodes": nodes,
    }


def set_exit_node(node_id: str | None) -> None:
    _request(
        "PATCH",
        "/localapi/v0/prefs",
        {"ExitNodeID": node_id or "", "ExitNodeIDSet": True},
    )


def pick_random(
    nodes: list[dict], exclude_id: str | None = None
) -> dict | None:
    options = [
        i
        for i in nodes
        if i["is_mullvad"] and i["online"] and i["node_id"] != exclude_id
    ]
    if not options:
        return None

    return random.choice(options)


def pick_rotation_target(state: dict) -> dict | None:
    current = state["current"] or {}

    return pick_random(state["nodes"], current.get("node_id"))


def get_egress() -> dict:
    try:
        response = requests.get(MULLVAD_CHECK_URL, timeout=EGRESS_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        return {
            "ip": data.get("ip"),
            "country": data.get("country"),
            "city": data.get("city"),
            "organization": data.get("organization"),
            "is_mullvad": bool(data.get("mullvad_exit_ip")),
            "exit_hostname": data.get("mullvad_exit_ip_hostname") or None,
        }
    except (requests.RequestException, ValueError):
        pass

    # null, not false: a bare ip says nothing about the exit
    try:
        response = requests.get(FALLBACK_CHECK_URL, timeout=EGRESS_TIMEOUT)
        response.raise_for_status()
        return {
            "ip": response.json().get("ip"),
            "country": None,
            "city": None,
            "organization": None,
            "is_mullvad": None,
            "exit_hostname": None,
        }
    except (requests.RequestException, ValueError) as err:
        raise TailscaleError(f"could not determine egress ip: {err}") from err
