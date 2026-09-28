"""test the Internet Archive metadata lookup

the wayback machine's video store and its page captures are indexed
separately, so a response regularly carries a readable watch page and
no formats at all - and sometimes the reverse.
"""

import pytest
from appsettings.src.wayback import (
    MAX_CHANNEL_NAME,
    MAX_DESCRIPTION,
    MAX_TITLE,
    WaybackMetadata,
)

VIDEO_ID = "A-Yj8lIe7G4"
CHANNEL_ID = "UC0RBTQIYLEQbcahZWkmzeTQ"


# measured live for an id whose watch page was never captured: the
# wayback machine answers with a capture of youtube's redirect page, and
# yt-dlp hands that page's title back as the video's
REDIRECT_PAGE_CAPTURE = {
    "id": "aaaaaaaaaaa",
    "fulltitle": "Broadcast Yourself.",
    "title": "Broadcast Yourself.",
    "description": "Share your videos with friends and family",
    "extractor": "web.archive:youtube",
}


def build_response(**overwrites):
    """what yt-dlp's web.archive:youtube extractor returns for a hit"""
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
    """
    YoutubeDL substitutes a generic title for a missing one, so title
    is populated even on a miss; fulltitle is the extractor's own
    """
    response = build_response(
        fulltitle=None, title=f"web.archive-youtube video #{VIDEO_ID}"
    )

    assert WaybackMetadata(VIDEO_ID)._build(response) is None


def test_a_capture_of_a_page_that_is_not_the_video_is_a_miss():
    """for a video removed before its first capture, youtube's redirect
    page is the only thing on that url"""
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
    """any one of these means the capture was of the watch page"""
    response = dict(REDIRECT_PAGE_CAPTURE)
    response[field] = value

    assert WaybackMetadata("aaaaaaaaaaa")._build(response) is not None


def test_a_long_title_is_capped_at_what_the_save_accepts():
    """ImportMetadataSerializer rejects a longer one outright"""
    built = build(fulltitle="x" * (MAX_TITLE + 100))

    assert len(built["title"]) == MAX_TITLE


def test_a_long_channel_name_is_capped_at_what_the_save_accepts():
    """same, and a capture's uploader field is not length checked"""
    built = build(uploader="x" * (MAX_CHANNEL_NAME + 100))

    assert len(built["channel_name"]) == MAX_CHANNEL_NAME


def test_upload_date_is_the_iso_date_a_date_input_takes():
    """yt-dlp spells it YYYYMMDD, the form field wants YYYY-MM-DD"""
    assert build()["upload_date"] == "2021-06-01"


@pytest.mark.parametrize("raw", [None, "", "not a date", "2021-06-01"])
def test_an_unusable_upload_date_comes_back_blank(raw):
    """blank leaves the user a date to fill, a crash leaves nothing"""
    assert build(upload_date=raw, release_date=None)["upload_date"] == ""


def test_upload_date_falls_back_to_the_release_date():
    """a capture can carry one without the other"""
    metadata = build(upload_date=None, release_date="20210601")

    assert metadata["upload_date"] == "2021-06-01"


def test_channel_name_falls_back_to_the_channel_key():
    """uploader is the usual spelling, channel is not always absent"""
    metadata = build(uploader=None, channel="Garand Thumb")

    assert metadata["channel_name"] == "Garand Thumb"


@pytest.mark.parametrize("channel_id", ["../../etc", "with/slash", "a", ""])
def test_drops_a_channel_id_that_is_not_a_safe_directory_name(channel_id):
    """it becomes a directory under the media root on import"""
    assert build(channel_id=channel_id)["channel_id"] == ""


def test_keeps_a_real_channel_id():
    assert build()["channel_id"] == CHANNEL_ID


def test_thumbnail_falls_back_to_the_best_of_the_list():
    """yt-dlp promotes the singular key out of the list only when there
    are formats, and a page-only capture has none"""
    metadata = build(
        thumbnail=None,
        thumbnails=[{"url": "http://small.jpg"}, {"url": "http://big.jpg"}],
    )

    assert metadata["thumbnail"] == "http://big.jpg"


def test_thumbnail_skips_list_entries_with_no_url():
    """yt-dlp builds these from whatever the capture had"""
    metadata = build(
        thumbnail=None, thumbnails=[{"url": "http://only.jpg"}, {"id": "0"}]
    )

    assert metadata["thumbnail"] == "http://only.jpg"


def test_no_thumbnail_anywhere_is_blank_not_missing():
    assert build(thumbnail=None, thumbnails=[])["thumbnail"] == ""


def test_description_is_capped_at_what_the_save_accepts():
    """ImportMetadataSerializer rejects a longer one outright"""
    metadata = build(description="x" * (MAX_DESCRIPTION + 100))

    assert len(metadata["description"]) == MAX_DESCRIPTION


def test_counts_pass_through_when_a_capture_had_them():
    """rare, but the page sometimes still carries them"""
    metadata = build(view_count=1234, like_count=56)

    assert metadata["view_count"] == 1234
    assert metadata["like_count"] == 56


@pytest.mark.parametrize("video_id", ["", "short", "A-Yj8lIe7G4x", "../../x"])
def test_refuses_anything_that_is_not_a_video_id(video_id):
    """the id goes into the url yt-dlp is handed"""
    with pytest.raises(ValueError):
        WaybackMetadata(video_id).get()
