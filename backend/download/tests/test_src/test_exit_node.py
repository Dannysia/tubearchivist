"""test rotating the exit node away from a blocked address

the cap is the point of most of this: a block that no address fixes must
stop costing rotations, and a request that works must hand the budget
back.
"""

import pytest
from download.src import exit_node


class FakeRedis:
    """stands in for RedisArchivist, one key is all this needs"""

    def __init__(self, stored=None):
        self.stored = stored
        self.deleted = False

    def get_message_str(self, key):
        assert key == exit_node.ROTATE_COUNT_KEY
        return self.stored

    def set_message(self, key, value, save=False):
        assert key == exit_node.ROTATE_COUNT_KEY
        self.stored = value

    def del_message(self, key, save=False):
        assert key == exit_node.ROTATE_COUNT_KEY
        self.stored = None
        self.deleted = True


def config(enabled=True, allowed=3):
    return {
        "downloads": {
            "auto_rotate_exit_node": enabled,
            "max_exit_node_rotates": allowed,
        }
    }


NODES = [
    {
        "node_id": "n1",
        "hostname": "us-den-wg-101",
        "country": "USA",
        "city": "Denver",
        "online": True,
        "is_mullvad": True,
    },
    {
        "node_id": "n2",
        "hostname": "se-sto-wg-001",
        "country": "Sweden",
        "city": "Stockholm",
        "online": True,
        "is_mullvad": True,
    },
]


@pytest.fixture
def wired(monkeypatch):
    """a reachable tailscale, currently on n1, and a settable redis"""
    redis = FakeRedis()
    switched = []

    monkeypatch.setattr(exit_node, "RedisArchivist", lambda: redis)
    monkeypatch.setattr(exit_node.tailscale, "is_available", lambda: True)
    monkeypatch.setattr(
        exit_node.tailscale,
        "get_state",
        lambda: {
            "available": True,
            "routes_all_traffic": True,
            "current": NODES[0],
            "nodes": NODES,
        },
    )
    monkeypatch.setattr(
        exit_node.tailscale, "set_exit_node", lambda i: switched.append(i)
    )

    return redis, switched


class TestDisabled:
    """nothing happens unless it was asked for"""

    def test_no_config_at_all_is_silent(self, monkeypatch):
        """urlparser builds a YtWrap without one, and that path must not
        need a redis either"""

        def explode():
            raise AssertionError("redis must not be reached when off")

        monkeypatch.setattr(exit_node, "RedisArchivist", explode)
        assert exit_node.rotate_on_bot_block(False) is None

    def test_toggle_off_is_silent(self, wired):
        _, switched = wired
        assert exit_node.rotate_on_bot_block(config(enabled=False)) is None
        assert switched == []

    def test_says_so_when_tailscale_is_missing(self, monkeypatch):
        """on but inert is worth a line, since it looks like it works"""
        monkeypatch.setattr(exit_node.tailscale, "is_available", lambda: False)
        message = exit_node.rotate_on_bot_block(config())
        assert "no tailscaled" in message


class TestRotating:
    """the normal path"""

    def test_switches_away_from_the_current_node(self, wired):
        redis, switched = wired
        message = exit_node.rotate_on_bot_block(config())

        assert switched == ["n2"]
        assert "se-sto-wg-001" in message
        assert "Stockholm, Sweden" in message
        assert redis.stored == "1"

    def test_counts_up_across_blocks(self, wired):
        redis, switched = wired
        for expected in ("1", "2", "3"):
            exit_node.rotate_on_bot_block(config())
            assert redis.stored == expected

        assert len(switched) == 3

    def test_stops_at_the_cap(self, wired):
        redis, switched = wired
        redis.stored = "3"

        message = exit_node.rotate_on_bot_block(config(allowed=3))
        assert switched == []
        assert "not rotating again" in message
        assert redis.stored == "3"

    def test_cap_of_one_allows_exactly_one(self, wired):
        redis, switched = wired
        exit_node.rotate_on_bot_block(config(allowed=1))
        exit_node.rotate_on_bot_block(config(allowed=1))

        assert len(switched) == 1
        assert redis.stored == "1"

    def test_no_mullvad_node_to_move_to(self, monkeypatch, wired):
        redis, switched = wired
        monkeypatch.setattr(
            exit_node.tailscale,
            "get_state",
            lambda: {"current": None, "nodes": []},
        )

        message = exit_node.rotate_on_bot_block(config())
        assert "no mullvad exit node" in message
        # a rotate that did not happen must not cost budget
        assert redis.stored is None
        assert switched == []

    def test_tailscale_failure_does_not_raise(self, monkeypatch, wired):
        """the bot error is already on its way up, and it is the more
        useful of the two"""
        redis, _ = wired

        def boom():
            raise exit_node.tailscale.TailscaleError("socket gone")

        monkeypatch.setattr(exit_node.tailscale, "get_state", boom)

        message = exit_node.rotate_on_bot_block(config())
        assert "socket gone" in message
        assert redis.stored is None

    def test_an_unexpected_error_does_not_raise_either(
        self, monkeypatch, wired
    ):
        """the promise is that nothing in here replaces the bot error,
        not that only TailscaleError is survivable"""
        redis, _ = wired

        def boom():
            raise ValueError("localapi sent something that is not json")

        monkeypatch.setattr(exit_node.tailscale, "get_state", boom)

        message = exit_node.rotate_on_bot_block(config())
        assert "not json" in message
        assert redis.stored is None


class TestBudget:
    """handing it back

    clear_budget runs after every request that works, so what it costs
    when rotation is switched off matters more than what it does when
    switched on
    """

    def test_disabled_never_reaches_redis(self, monkeypatch):
        """the regression: this used to construct a RedisArchivist on
        every successful extract, which needs a REDIS_CON to exist even
        on an install that will never rotate anything"""

        def explode():
            raise AssertionError("redis must not be reached when off")

        monkeypatch.setattr(exit_node, "RedisArchivist", explode)

        exit_node.clear_budget(config(enabled=False))
        exit_node.clear_budget(False)
        exit_node.clear_budget(None)
        exit_node.clear_budget()

    def test_a_working_request_clears_it(self, monkeypatch):
        redis = FakeRedis(stored="2")
        monkeypatch.setattr(exit_node, "RedisArchivist", lambda: redis)

        exit_node.clear_budget(config())
        assert redis.deleted is True

    def test_clearing_an_unused_budget_touches_nothing(self, monkeypatch):
        """so every successful extract is not also a redis write"""
        redis = FakeRedis(stored=None)
        monkeypatch.setattr(exit_node, "RedisArchivist", lambda: redis)

        exit_node.clear_budget(config())
        assert redis.deleted is False

    def test_a_junk_value_reads_as_no_budget_used(self, monkeypatch):
        redis = FakeRedis(stored="not a number")
        monkeypatch.setattr(exit_node, "RedisArchivist", lambda: redis)

        assert exit_node._budget_used() == 0
