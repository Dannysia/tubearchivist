# flake8: noqa: E402

import os
from types import SimpleNamespace
from unittest.mock import patch

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from video.src import index


def _video(json_data):
    return SimpleNamespace(
        json_data=json_data,
        youtube_id="abc123xyz00",
        get_from_es=lambda print_error=True: None,
        build_json=lambda: None,
        check_subtitles=lambda: None,
        upload_to_es=lambda: None,
    )


def test_a_redownload_leaves_the_thumbnail_to_the_refresh():
    existing = _video({"vid_thumb_url": "https://i.ytimg.com/vi/x/a.jpg"})
    with patch.object(index, "YoutubeVideo", return_value=existing), patch(
        "appsettings.src.reindex.Reindex"
    ) as reindex, patch.object(index, "ThumbManager") as thumb_manager:
        reindex.return_value.reindex_single_video.return_value = existing
        index.index_new_video("abc123xyz00")

    thumb_manager.assert_not_called()


def test_a_new_video_downloads_its_thumbnail():
    new = _video(None)

    def build_json():
        new.json_data = {"vid_thumb_url": "https://i.ytimg.com/vi/x/a.jpg"}

    new.build_json = build_json
    with patch.object(index, "YoutubeVideo", return_value=new), patch.object(
        index, "ThumbManager"
    ) as thumb_manager:
        index.index_new_video("abc123xyz00")

    thumb_manager.return_value.download_video_thumb.assert_called_once_with(
        url="https://i.ytimg.com/vi/x/a.jpg"
    )
