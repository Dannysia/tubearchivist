"""test the offline metadata merge for manual import

A video removed by YouTube does not return nothing, it returns a stub.
That stub is truthy, so a hand written info.json used to be discarded
for exactly the videos it exists to rescue - see the ValueError from
_build_published on the null upload_date
"""

import pytest
from video.src.index import YoutubeVideo

VIDEO_ID = "ibyCDgITtxg"

# what yt-dlp actually returned for a video removed for violating
# community guidelines, with ignore_no_formats_error set
REMOVED_STUB = {
    "id": VIDEO_ID,
    "title": f"youtube video #{VIDEO_ID}",
    "upload_date": None,
    "timestamp": None,
    "channel_id": None,
    "uploader": None,
    "thumbnail": f"https://i.ytimg.com/vi_webp/{VIDEO_ID}/maxresdefault.webp",
    "formats": [],
}


def build_info_json(**overwrites):
    """a generated import metadata file"""
    info_json = {
        "id": VIDEO_ID,
        "title": "Firing a minigun from a Helicopter",
        "channel_id": "UC0RBTQIYLEQbcahZWkmzeTQ",
        "uploader": "Garand Thumb",
        "upload_date": "20200211",
        "description": "big daddy unlimited link",
        "thumbnail": "",
        "view_count": 240756,
        "like_count": 15391,
    }
    info_json.update(overwrites)

    return info_json


def test_file_fills_in_what_the_stub_left_null():
    """the fields the import path raises on"""
    merged = YoutubeVideo._merge_offline_meta(REMOVED_STUB, build_info_json())

    assert merged["upload_date"] == "20200211"
    assert merged["channel_id"] == "UC0RBTQIYLEQbcahZWkmzeTQ"
    assert merged["uploader"] == "Garand Thumb"


def test_file_replaces_the_placeholder_title():
    """
    the stub title is truthy, so a gap fill alone would index the video
    as "youtube video #<id>"
    """
    merged = YoutubeVideo._merge_offline_meta(REMOVED_STUB, build_info_json())

    assert merged["title"] == "Firing a minigun from a Helicopter"


def test_blank_file_field_keeps_what_the_stub_had():
    """
    YT still serves a thumbnail for a removed video, and the form writes
    an empty string when no url is given
    """
    merged = YoutubeVideo._merge_offline_meta(REMOVED_STUB, build_info_json())

    assert merged["thumbnail"] == REMOVED_STUB["thumbnail"]


def test_zero_counts_do_not_clobber():
    """0 is a real value in the file, not an absent one"""
    merged = YoutubeVideo._merge_offline_meta(
        REMOVED_STUB, build_info_json(view_count=0)
    )

    assert merged["view_count"] == 0


def test_keys_only_in_the_stub_survive():
    """the file carries a subset, it does not replace the whole dict"""
    stub = dict(REMOVED_STUB, categories=["Entertainment"])
    merged = YoutubeVideo._merge_offline_meta(stub, build_info_json())

    assert merged["categories"] == ["Entertainment"]


def test_without_a_file_the_stub_is_untouched():
    """no info.json staged, nothing to merge"""
    assert YoutubeVideo._merge_offline_meta(REMOVED_STUB, False) == (
        REMOVED_STUB
    )


def test_the_merge_does_not_mutate_either_input():
    """both dicts belong to the caller"""
    stub = dict(REMOVED_STUB)
    info_json = build_info_json()
    YoutubeVideo._merge_offline_meta(stub, info_json)

    assert stub == REMOVED_STUB
    assert info_json["thumbnail"] == ""


def test_merged_upload_date_is_what_build_published_parses():
    """
    the failure was a ValueError out of _build_published, so pin the
    format it needs rather than just that the key is set
    """
    merged = YoutubeVideo._merge_offline_meta(REMOVED_STUB, build_info_json())
    # __init__ reads the app config out of ES, which a unit test has no
    # business needing for a date format assertion
    video = YoutubeVideo.__new__(YoutubeVideo)
    video.youtube_meta = merged
    video.youtube_id = VIDEO_ID

    assert video._build_published() == "2020-02-11"


def test_the_stub_alone_still_raises():
    """
    without a file there is nothing to rescue the import with, and the
    error stays the one that was reported
    """
    video = YoutubeVideo.__new__(YoutubeVideo)
    video.youtube_meta = REMOVED_STUB
    video.youtube_id = VIDEO_ID

    with pytest.raises(ValueError):
        video._build_published()
