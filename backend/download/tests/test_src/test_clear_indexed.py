"""test clearing the queue entry of a video that is now indexed"""

from unittest.mock import patch

from common.src.es_connect import IndexWriteError
from download.src.queue_interact import PendingInteract


def test_a_failed_clear_is_reported_not_raised(capsys):
    with patch.object(
        PendingInteract, "delete_item", side_effect=IndexWriteError("503")
    ):
        PendingInteract(youtube_id="vid1").clear_indexed()

    assert "vid1: queue entry not cleared" in capsys.readouterr().out


def test_the_entry_is_deleted_quietly():
    with patch.object(PendingInteract, "delete_item") as mock_delete:
        PendingInteract(youtube_id="vid1").clear_indexed()

    mock_delete.assert_called_once_with(print_error=False)
