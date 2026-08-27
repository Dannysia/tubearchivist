"""test exit node selection

the localapi itself is not exercised here - these cover the decisions
made around it, above all that a rotate never lands on one of the user's
own tailnet machines, whose address would not change at all
"""

import pytest
import requests
from appsettings.src import tailscale


def mullvad_peer(node_id, host, country, city, online=True):
    """a peer as the localapi reports a mullvad exit node"""
    return {
        "ID": node_id,
        "HostName": host,
        "Online": online,
        "ExitNodeOption": True,
        # CountryCode is what the localapi really sends and _parse_node
        # deliberately drops, so the fixture keeps it: a peer here should
        # look like a peer, not like the subset we happen to read
        "Location": {
            "Country": country,
            "CountryCode": country[:2].upper(),
            "City": city,
        },
    }


def tailnet_peer(node_id, host, online=True):
    """a peer as the localapi reports a self hosted exit node"""
    return {
        "ID": node_id,
        "HostName": host,
        "Online": online,
        "ExitNodeOption": True,
    }


NODES = [
    tailscale._parse_node(
        mullvad_peer("n1", "us-den-wg-101", "USA", "Denver")
    ),
    tailscale._parse_node(
        mullvad_peer("n2", "us-lax-wg-402", "USA", "Los Angeles")
    ),
    tailscale._parse_node(
        mullvad_peer("n3", "se-sto-wg-001", "Sweden", "Stockholm")
    ),
    tailscale._parse_node(
        mullvad_peer("n4", "us-nyc-wg-777", "USA", "New York", online=False)
    ),
    tailscale._parse_node(tailnet_peer("n5", "DannyNAS2")),
]


class TestParseNode:
    """the fields a picker reads off a peer"""

    def test_mullvad_carries_a_location(self):
        parsed = tailscale._parse_node(
            mullvad_peer("n1", "us-den-wg-101", "USA", "Denver")
        )
        assert parsed["node_id"] == "n1"
        assert parsed["hostname"] == "us-den-wg-101"
        assert parsed["country"] == "USA"
        assert parsed["city"] == "Denver"
        assert parsed["is_mullvad"] is True

    def test_tailnet_node_has_no_location(self):
        """which is exactly what marks it as not a vpn exit"""
        parsed = tailscale._parse_node(tailnet_peer("n5", "DannyNAS2"))
        assert parsed["is_mullvad"] is False
        assert parsed["country"] is None
        assert parsed["city"] is None


class TestPickRandom:
    """rotation, which ranges over the whole tailnet"""

    def test_never_picks_a_tailnet_node(self):
        """the user's own machines share the address being rotated away
        from, so drawing one would silently do nothing"""
        for _ in range(50):
            picked = tailscale.pick_random(NODES)
            assert picked["is_mullvad"] is True

    def test_never_picks_an_offline_node(self):
        for _ in range(50):
            assert tailscale.pick_random(NODES)["online"] is True

    def test_ranges_across_countries(self):
        """rotation is global - narrowing to one country is what picking
        a node from the list is for"""
        seen = {tailscale.pick_random(NODES)["country"] for _ in range(100)}
        assert seen == {"USA", "Sweden"}

    def test_excludes_the_current_node(self):
        """rotating onto the node already in use is the one useless
        outcome"""
        for _ in range(50):
            picked = tailscale.pick_random(NODES, exclude_id="n1")
            assert picked["node_id"] != "n1"

    def test_sole_option_returns_that_node(self):
        """rather than failing, when there is nowhere else to go"""
        only = [i for i in NODES if i["node_id"] == "n3"]
        assert tailscale.pick_random(only, exclude_id="n3")["node_id"] == "n3"

    def test_no_mullvad_nodes_returns_none(self):
        only_tailnet = [i for i in NODES if not i["is_mullvad"]]
        assert tailscale.pick_random(only_tailnet) is None


class TestSocketDiscovery:
    """when present, and where"""

    def test_absent_when_no_socket(self, monkeypatch):
        monkeypatch.delenv("TS_SOCKET", raising=False)
        monkeypatch.setattr(
            tailscale, "SOCKET_CANDIDATES", ["/nope/tailscaled.sock"]
        )
        assert tailscale.socket_path() is None
        assert tailscale.is_available() is False

    def test_env_var_wins(self, monkeypatch, tmp_path):
        preferred = tmp_path / "custom.sock"
        preferred.touch()
        fallback = tmp_path / "standard.sock"
        fallback.touch()
        monkeypatch.setenv("TS_SOCKET", str(preferred))
        monkeypatch.setattr(tailscale, "SOCKET_CANDIDATES", [str(fallback)])
        assert tailscale.socket_path() == str(preferred)

    def test_falls_through_to_a_candidate(self, monkeypatch, tmp_path):
        found = tmp_path / "tailscaled.sock"
        found.touch()
        monkeypatch.delenv("TS_SOCKET", raising=False)
        monkeypatch.setattr(
            tailscale, "SOCKET_CANDIDATES", ["/nope/one.sock", str(found)]
        )
        assert tailscale.socket_path() == str(found)


class TestGetState:
    """what the panel reads"""

    def test_unavailable_without_a_socket(self, monkeypatch):
        monkeypatch.setattr(tailscale, "is_available", lambda: False)
        state = tailscale.get_state()
        assert state == {
            "available": False,
            "routes_all_traffic": False,
            "current": None,
            "nodes": [],
        }

    def test_reports_current_and_options(self, monkeypatch):
        status = {
            "TUN": True,
            "Peer": {
                "a": mullvad_peer("n1", "us-den-wg-101", "USA", "Denver"),
                "b": mullvad_peer(
                    "n3", "se-sto-wg-001", "Sweden", "Stockholm"
                ),
                "c": {"ID": "n9", "HostName": "emby", "Online": True},
            },
        }
        status["Peer"]["a"]["ExitNode"] = True
        monkeypatch.setattr(tailscale, "is_available", lambda: True)
        monkeypatch.setattr(tailscale, "_request", lambda *a, **kw: status)

        state = tailscale.get_state()
        assert state["available"] is True
        assert state["routes_all_traffic"] is True
        assert state["current"]["hostname"] == "us-den-wg-101"
        # the non exit peer is not selectable
        assert [i["node_id"] for i in state["nodes"]] == ["n3", "n1"]

    def test_unreachable_socket_raises(self, monkeypatch, tmp_path):
        """a socket that is present but will not connect is a different
        state from tailscale being absent, and has to surface as an error
        rather than quietly read as absent"""
        dead = tmp_path / "tailscaled.sock"
        dead.write_text("not a socket")
        monkeypatch.setenv("TS_SOCKET", str(dead))

        with pytest.raises(tailscale.TailscaleError):
            tailscale.get_state()

    def test_userspace_flagged(self, monkeypatch):
        """switching the exit node under userspace networking would not
        move the downloader's traffic, so the panel has to know"""
        monkeypatch.setattr(tailscale, "is_available", lambda: True)
        monkeypatch.setattr(
            tailscale, "_request", lambda *a, **kw: {"TUN": False}
        )
        assert tailscale.get_state()["routes_all_traffic"] is False


class TestSetExitNode:
    """the write"""

    def test_masks_in_only_the_exit_node(self, monkeypatch):
        """anything else in prefs, ExitNodeAllowLANAccess above all, has
        to survive the call untouched"""
        seen = {}

        def fake(method, path, payload=None):
            seen.update(method=method, path=path, payload=payload)
            return {}

        monkeypatch.setattr(tailscale, "_request", fake)
        tailscale.set_exit_node("n1")

        assert seen["method"] == "PATCH"
        assert seen["path"] == "/localapi/v0/prefs"
        assert seen["payload"] == {"ExitNodeID": "n1", "ExitNodeIDSet": True}

    def test_none_clears(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            tailscale,
            "_request",
            lambda method, path, payload=None: seen.update(payload=payload)
            or {},
        )
        tailscale.set_exit_node(None)
        assert seen["payload"] == {"ExitNodeID": "", "ExitNodeIDSet": True}


class FakeResponse:
    """enough of a requests response for the egress check"""

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        """always a 200 here, the fake get raises the failures itself"""

    def json(self):
        return self.payload


class TestGetEgress:
    """confirming a rotate actually moved the address"""

    def test_reports_the_exit_node_behind_the_address(self, monkeypatch):
        payload = {
            "ip": "198.51.100.7",
            "country": "United States",
            "city": "Denver",
            "organization": "Mullvad",
            "mullvad_exit_ip": True,
            "mullvad_exit_ip_hostname": "us-den-wg-101",
        }
        monkeypatch.setattr(
            requests, "get", lambda *a, **kw: FakeResponse(payload)
        )

        egress = tailscale.get_egress()
        assert egress["ip"] == "198.51.100.7"
        assert egress["is_mullvad"] is True
        assert egress["exit_hostname"] == "us-den-wg-101"

    def test_direct_connection_reports_the_real_isp(self, monkeypatch):
        payload = {
            "ip": "203.0.113.9",
            "country": "United States",
            "city": "Seattle",
            "organization": "Wave Broadband",
            "mullvad_exit_ip": False,
        }
        monkeypatch.setattr(
            requests, "get", lambda *a, **kw: FakeResponse(payload)
        )

        egress = tailscale.get_egress()
        assert egress["is_mullvad"] is False
        assert egress["exit_hostname"] is None
        assert egress["organization"] == "Wave Broadband"

    def test_falls_back_to_a_plain_echo(self, monkeypatch):
        """is_mullvad is then unknown rather than false, since a bare ip
        says nothing about how it was reached"""

        def fake_get(url, **kw):
            if url == tailscale.MULLVAD_CHECK_URL:
                raise requests.ConnectionError("blocked")
            return FakeResponse({"ip": "203.0.113.9"})

        monkeypatch.setattr(requests, "get", fake_get)

        egress = tailscale.get_egress()
        assert egress["ip"] == "203.0.113.9"
        assert egress["is_mullvad"] is None

    def test_raises_when_both_checks_fail(self, monkeypatch):
        def fake_get(url, **kw):
            raise requests.ConnectionError("no route")

        monkeypatch.setattr(requests, "get", fake_get)

        with pytest.raises(tailscale.TailscaleError):
            tailscale.get_egress()
