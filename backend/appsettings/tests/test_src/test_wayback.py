"""test the Internet Archive metadata lookup"""

import pytest
from appsettings.src.wayback import (
    MAX_CHANNEL_NAME,
    MAX_DESCRIPTION,
    MAX_TITLE,
    WaybackMetadata,
)

VIDEO_ID = "A-Yj8lIe7G4"
CHANNEL_ID = "UC0RBTQIYLEQbcahZWkmzeTQ"


REDIRECT_PAGE_CAPTURE = {
    "id": "aaaaaaaaaaa",
    "fulltitle": "Broadcast Yourself.",
    "title": "Broadcast Yourself.",
    "description": "Share your videos with friends and family",
    "extractor": "web.archive:youtube",
}


def build_response(**overwrites):
    response = {
        "id": VIDEO_ID,
        "fulltitle": "Suppressors Will Save Your Life",
        "title": "Suppressors Will Save Your Life",
        "channel_id": CHANNEL_ID,
        "uploader": "Garand Thumb",
        "upload_date": "20210601",
        "description": "Big Daddy Unlimited Link",
        "thumbnail": (
            "https://web.archive.org/web/20220202092837if_/"
            f"https://i.ytimg.com/vi/{VIDEO_ID}/hq720.jpg"
        ),
        "extractor": "web.archive:youtube",
    }
    response.update(overwrites)

    return response


def build(**overwrites):
    return WaybackMetadata(VIDEO_ID)._build(build_response(**overwrites))


def test_maps_onto_the_import_metadata_fields():
    metadata = build()

    assert metadata == {
        "video_id": VIDEO_ID,
        "title": "Suppressors Will Save Your Life",
        "channel_id": CHANNEL_ID,
        "channel_name": "Garand Thumb",
        "upload_date": "2021-06-01",
        "description": "Big Daddy Unlimited Link",
        "thumbnail": (
            "https://web.archive.org/web/20220202092837if_/"
            f"https://i.ytimg.com/vi/{VIDEO_ID}/hq720.jpg"
        ),
        "view_count": None,
        "like_count": None,
    }


def test_no_readable_capture_is_a_miss():
    response = build_response(
        fulltitle=None, title=f"web.archive-youtube video #{VIDEO_ID}"
    )

    assert WaybackMetadata(VIDEO_ID)._build(response) is None


def test_a_capture_of_a_page_that_is_not_the_video_is_a_miss():
    built = WaybackMetadata("aaaaaaaaaaa")._build(dict(REDIRECT_PAGE_CAPTURE))

    assert built is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("channel_id", CHANNEL_ID),
        ("uploader", "Garand Thumb"),
        ("channel", "Garand Thumb"),
        ("upload_date", "20210601"),
        ("release_date", "20210601"),
        ("timestamp", 1622505600),
    ],
)
def test_one_identifying_field_makes_it_the_video_s_own_page(field, value):
    response = dict(REDIRECT_PAGE_CAPTURE)
    response[field] = value

    assert WaybackMetadata("aaaaaaaaaaa")._build(response) is not None


def test_a_long_title_is_capped_at_what_the_save_accepts():
    built = build(fulltitle="x" * (MAX_TITLE + 100))

    assert len(built["title"]) == MAX_TITLE


def test_a_long_channel_name_is_capped_at_what_the_save_accepts():
    built = build(uploader="x" * (MAX_CHANNEL_NAME + 100))

    assert len(built["channel_name"]) == MAX_CHANNEL_NAME


def test_upload_date_is_the_iso_date_a_date_input_takes():
    assert build()["upload_date"] == "2021-06-01"


@pytest.mark.parametrize("raw", [None, "", "not a date", "2021-06-01"])
def test_an_unusable_upload_date_comes_back_blank(raw):
    assert build(upload_date=raw, release_date=None)["upload_date"] == ""


def test_upload_date_falls_back_to_the_release_date():
    metadata = build(upload_date=None, release_date="20210601")

    assert metadata["upload_date"] == "2021-06-01"


def test_channel_name_falls_back_to_the_channel_key():
    metadata = build(uploader=None, channel="Garand Thumb")

    assert metadata["channel_name"] == "Garand Thumb"


@pytest.mark.parametrize("channel_id", ["../../etc", "with/slash", "a", ""])
def test_drops_a_channel_id_that_is_not_a_safe_directory_name(channel_id):
    assert build(channel_id=channel_id)["channel_id"] == ""


def test_keeps_a_real_channel_id():
    assert build()["channel_id"] == CHANNEL_ID


def test_thumbnail_falls_back_to_the_best_of_the_list():
    metadata = build(
        thumbnail=None,
        thumbnails=[{"url": "http://small.jpg"}, {"url": "http://big.jpg"}],
    )

    assert metadata["thumbnail"] == "http://big.jpg"


def test_thumbnail_skips_list_entries_with_no_url():
    metadata = build(
        thumbnail=None, thumbnails=[{"url": "http://only.jpg"}, {"id": "0"}]
    )

    assert metadata["thumbnail"] == "http://only.jpg"


def test_no_thumbnail_anywhere_is_blank_not_missing():
    assert build(thumbnail=None, thumbnails=[])["thumbnail"] == ""


def test_description_is_capped_at_what_the_save_accepts():
    metadata = build(description="x" * (MAX_DESCRIPTION + 100))

    assert len(metadata["description"]) == MAX_DESCRIPTION


def test_counts_pass_through_when_a_capture_had_them():
    metadata = build(view_count=1234, like_count=56)

    assert metadata["view_count"] == 1234
    assert metadata["like_count"] == 56


@pytest.mark.parametrize("video_id", ["", "short", "A-Yj8lIe7G4x", "../../x"])
def test_refuses_anything_that_is_not_a_video_id(video_id):
    with pytest.raises(ValueError):
        WaybackMetadata(video_id).get()
