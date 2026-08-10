"""
tests for _release_lock() - shared by dispatch_pending_downscales(),
_reserve_slot(), and worker.claim(), all of which do real work under
DISPATCH_LOCK_KEY in a try/finally. redis-py raises LockError from
release() if the lock's TTL already expired before release() runs; left
uncaught, that would replace an in-flight `return` value in the calling
`finally` block (or crash a request after it already made a successful
change) purely because of lock-cleanup timing, not anything wrong with
the actual work done under the lock.
"""

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
    """
    a TTL that lapsed before release() ran must not raise out of the
    caller's finally block - the critical section already finished
    """
    lock = MagicMock()
    lock.release.side_effect = exc

    _release_lock(lock)  # must not raise


def test_release_lock_does_not_swallow_unrelated_errors():
    """only the lock-ownership case is expected; anything else surfaces"""
    lock = MagicMock()
    lock.release.side_effect = RuntimeError("something else broke")

    with pytest.raises(RuntimeError):
        _release_lock(lock)
