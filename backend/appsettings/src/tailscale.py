"""steer the exit node of a tailscaled running alongside this container

only ever talks to a unix socket in this container, e.g. the one unraid's
tailscale integration injects. no socket means no tailscale, which every
caller has to treat as the feature simply being absent.
"""

import http.client
import json
import os
import random
import socket

import requests

# where a tailscaled socket turns up: the env var the official tailscale
# image sets, then the system path, then that image's own default
SOCKET_CANDIDATES = [
    "/var/run/tailscale/tailscaled.sock",
    "/run/tailscale/tailscaled.sock",
    "/tmp/tailscaled.sock",
]

# the localapi only answers to a host header it recognises, this value is
# not a real name and is never resolved
LOCAL_API_HOST = "local-tailscaled.sock"

SOCKET_TIMEOUT = 5
EGRESS_TIMEOUT = 10

# mullvad's own echo, rather than a plain ip echo, because it also
# reports which exit node the traffic came out of - the thing a rotate
# needs in order to confirm it did anything
MULLVAD_CHECK_URL = "https://am.i.mullvad.net/json"
FALLBACK_CHECK_URL = "https://api.ipify.org?format=json"


class TailscaleError(Exception):
    """tailscaled is there but refused or failed the call"""


def socket_path() -> str | None:
    """first tailscaled socket present, None when tailscale is absent"""
    for path in [os.environ.get("TS_SOCKET")] + SOCKET_CANDIDATES:
        if path and os.path.exists(path):
            return path

    return None


def is_available() -> bool:
    """whether this container has a tailscaled to talk to"""
    return socket_path() is not None


class _UnixConnection(http.client.HTTPConnection):
    """http over a unix socket, which is what the localapi speaks"""

    def __init__(self, sock_path: str):
        super().__init__(LOCAL_API_HOST, timeout=SOCKET_TIMEOUT)
        self.sock_path = sock_path

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(SOCKET_TIMEOUT)
        sock.connect(self.sock_path)
        self.sock = sock


def _request(method: str, path: str, payload: dict | None = None) -> dict:
    """call the tailscaled localapi"""
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
        # 403 here is the peer credential check, i.e. this process is not
        # root in the namespace tailscaled trusts
        detail = raw.decode(errors="replace").strip()
        raise TailscaleError(f"tailscaled returned {status}: {detail}")

    return json.loads(raw) if raw else {}


def _parse_node(peer: dict) -> dict:
    """the subset of a peer that a picker needs"""
    location = peer.get("Location") or {}

    return {
        "node_id": peer.get("ID"),
        "hostname": peer.get("HostName"),
        "country": location.get("Country"),
        "city": location.get("City"),
        "online": bool(peer.get("Online")),
        # only mullvad nodes report a Location, so its presence is what
        # separates a vpn exit from one of the user's own machines
        "is_mullvad": bool(location),
    }


def get_state() -> dict:
    """current exit node plus everything selectable"""
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
        # a userspace tailscaled routes only its own proxy, so switching
        # the exit node there would not move the downloader's traffic
        "routes_all_traffic": bool(status.get("TUN")),
        "current": current,
        "nodes": nodes,
    }


def set_exit_node(node_id: str | None) -> None:
    """pin the exit node, None to go direct

    masks in ExitNodeID alone so nothing else about the tailscale config
    moves - notably ExitNodeAllowLANAccess is left exactly as unraid set
    it.
    """
    _request(
        "PATCH",
        "/localapi/v0/prefs",
        {"ExitNodeID": node_id or "", "ExitNodeIDSet": True},
    )


def pick_random(
    nodes: list[dict], exclude_id: str | None = None
) -> dict | None:
    """any mullvad node to rotate onto, from anywhere

    tailnet exit nodes are the one thing never drawn: they are the user's
    own machines, so they would not change the public address, which is
    the entire point of rotating. picking a particular country is what
    the node list is for.
    """
    options = [i for i in nodes if i["is_mullvad"] and i["online"]]
    if not options:
        return None

    # staying put is only acceptable when it is the one option left
    return random.choice(
        [i for i in options if i["node_id"] != exclude_id] or options
    )


def get_egress() -> dict:
    """what the outside world currently sees this container as"""
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

    # a bare ip is still worth reporting, but nothing about the exit is
    # knowable from it, hence the nulls rather than false
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
