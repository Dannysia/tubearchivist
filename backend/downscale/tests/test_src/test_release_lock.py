"""redis-py raises LockError from release() when the lock's TTL lapsed"""

from unittest.mock import MagicMock

import pytest
from downscale.src.downscale import _release_lock
from redis.exceptions import LockError, LockNotOwnedError


def test_release_lock_releases_normally():
    lock = MagicMock()

    _release_lock(lock)

    lock.release.assert_called_once()


@pytest.mark.parametrize("exc", [LockError("gone"), LockNotOwnedError("gone")])
def test_release_lock_swallows_an_expired_lock(exc):
    lock = MagicMock()
    lock.release.side_effect = exc

    _release_lock(lock)  # must not raise


def test_release_lock_does_not_swallow_unrelated_errors():
    lock = MagicMock()
    lock.release.side_effect = RuntimeError("something else broke")

    with pytest.raises(RuntimeError):
        _release_lock(lock)
