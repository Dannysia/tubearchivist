from appsettings.src import tailscale
from common.src.ta_redis import RedisArchivist

# consecutive rotations not yet followed by a working request; redis
# because it is runtime state, not configuration
ROTATE_COUNT_KEY = "exit_node_rotates"

# unreachable through the api, the serializer always sets a cap
FALLBACK_MAX_ROTATES = 3


def _budget_used() -> int:
    """rotations since the last request that worked"""
    stored = RedisArchivist().get_message_str(ROTATE_COUNT_KEY)

    return int(stored) if stored and stored.isdigit() else 0


def _is_enabled(config) -> bool:
    """no config at all is neither on nor off, and has to read as off"""
    if not config:
        return False

    return bool((config.get("downloads") or {}).get("auto_rotate_exit_node"))


def clear_budget(config=None) -> None:
    """takes the config because this runs after every successful
    request: an install with rotation switched off must not pay a redis
    round trip, or need a redis at all
    """
    if not _is_enabled(config):
        return

    if _budget_used():
        RedisArchivist().del_message(ROTATE_COUNT_KEY)


def rotate_on_bot_block(config) -> str | None:
    """returns a line to log, or None when there is nothing to say

    never raises: a failure to rotate must not replace the bot error
    that is already on its way up.
    """
    if not _is_enabled(config):
        return None

    if not tailscale.is_available():
        return "auto rotate is on but there is no tailscaled to talk to"

    downloads = config.get("downloads") or {}
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
    # deliberately broad: the bot error already on its way up is more
    # useful than anything that fails in here
    except Exception as err:
        return f"exit node rotate failed: {err}"

    RedisArchivist().set_message(ROTATE_COUNT_KEY, str(used + 1), save=True)
    where = ", ".join(i for i in (picked["city"], picked["country"]) if i)

    return (
        f"rotated exit node to {picked['hostname']} ({where}), "
        f"{used + 1} of {allowed} before giving up"
    )
