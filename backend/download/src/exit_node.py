"""
functionality:
- rotate the tailscale exit node when youtube blocks the address
- cap how often that happens so a total block cannot spin forever
"""

from appsettings.src import tailscale
from common.src.ta_redis import RedisArchivist

# consecutive rotations that have not yet been followed by a working
# request. lives in redis because it is runtime state about right now,
# not configuration
ROTATE_COUNT_KEY = "exit_node_rotates"

# only used if the config somehow carries no cap, the serializer makes
# that unreachable through the api
FALLBACK_MAX_ROTATES = 3


def _budget_used() -> int:
    """rotations since the last request that worked"""
    stored = RedisArchivist().get_message_str(ROTATE_COUNT_KEY)

    return int(stored) if stored and stored.isdigit() else 0


def clear_budget() -> None:
    """a request got through, so the address is fine and the next block
    starts with a full budget again"""
    if _budget_used():
        RedisArchivist().del_message(ROTATE_COUNT_KEY)


def rotate_on_bot_block(config) -> str | None:
    """move to another exit node after youtube called this a bot

    returns a line to log, or None when there is nothing to say. never
    raises: a failure to rotate must not replace the bot error that is
    already on its way up.
    """
    # urlparser builds a YtWrap with no config at all
    if not config:
        return None

    downloads = config.get("downloads") or {}
    if not downloads.get("auto_rotate_exit_node"):
        return None

    if not tailscale.is_available():
        return "auto rotate is on but there is no tailscaled to talk to"

    used = _budget_used()
    allowed = downloads.get("max_exit_node_rotates") or FALLBACK_MAX_ROTATES
    if used >= allowed:
        return (
            f"already rotated {used} times with nothing getting through, "
            "so the block is not about this address. not rotating again "
            "until a request succeeds"
        )

    try:
        picked = tailscale.pick_rotation_target(tailscale.get_state())
        if not picked:
            return "no mullvad exit node available to rotate onto"

        tailscale.set_exit_node(picked["node_id"])
    # deliberately broad. this runs with a bot error already on its way
    # up, and that error is the more useful of the two, so nothing that
    # goes wrong in here is worth replacing it with
    except Exception as err:
        return f"exit node rotate failed: {err}"

    RedisArchivist().set_message(ROTATE_COUNT_KEY, str(used + 1), save=True)
    where = ", ".join(i for i in (picked["city"], picked["country"]) if i)

    return (
        f"rotated exit node to {picked['hostname']} ({where}), "
        f"{used + 1} of {allowed} before giving up"
    )
