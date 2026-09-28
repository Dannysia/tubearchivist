"""YT answers for a removed video with a truthy stub, not nothing"""

from types import SimpleNamespace

import pytest
from appsettings.src.manual import UNKNOWN_COUNT
from common.src import index_generic
from video.src.constants import VideoTypeEnum
from video.src.index import YoutubeVideo

VIDEO_ID = "ibyCDgITtxg"

# what yt-dlp returns for a removed video, ignore_no_formats_error set
REMOVED_STUB = {
    "id": VIDEO_ID,
    "title": f"youtube video #{VIDEO_ID}",
    # measured empty on live removed videos; YoutubeDL substitutes
    # the generic title above
    "fulltitle": "",
    "upload_date": None,
    "timestamp": None,
    "channel_id": None,
    "uploader": None,
    "thumbnail": f"https://i.ytimg.com/vi_webp/{VIDEO_ID}/maxresdefault.webp",
    "formats": [],
}


# age gated or members only: no formats, real metadata intact - the
# case that must not be mistaken for a removed video
AGE_GATED_META = {
    "id": VIDEO_ID,
    "fulltitle": "Members only upload",
    "title": "Members only upload",
    "channel_id": "UC0RBTQIYLEQbcahZWkmzeTQ",
    "uploader": "Garand Thumb",
    "upload_date": "20200211",
    "thumbnail": f"https://i.ytimg.com/vi/{VIDEO_ID}/maxresdefault.jpg",
    "formats": [],
}


def build_info_json(**overwrites):
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
    merged = YoutubeVideo._merge_offline_meta(REMOVED_STUB, build_info_json())

    assert merged["upload_date"] == "20200211"
    assert merged["channel_id"] == "UC0RBTQIYLEQbcahZWkmzeTQ"
    assert merged["uploader"] == "Garand Thumb"


def test_file_replaces_the_placeholder_title():
    """the stub title is truthy, so a gap fill alone would keep it"""
    merged = YoutubeVideo._merge_offline_meta(REMOVED_STUB, build_info_json())

    assert merged["title"] == "Firing a minigun from a Helicopter"


def test_blank_file_field_keeps_what_the_stub_had():
    """YT serves a thumbnail even for a removed video, and the import
    form writes an empty string when no url is given
    """
    merged = YoutubeVideo._merge_offline_meta(REMOVED_STUB, build_info_json())

    assert merged["thumbnail"] == REMOVED_STUB["thumbnail"]


def test_zero_counts_do_not_clobber():
    merged = YoutubeVideo._merge_offline_meta(
        REMOVED_STUB, build_info_json(view_count=0)
    )

    assert merged["view_count"] == 0


def test_keys_only_in_the_stub_survive():
    stub = dict(REMOVED_STUB, categories=["Entertainment"])
    merged = YoutubeVideo._merge_offline_meta(stub, build_info_json())

    assert merged["categories"] == ["Entertainment"]


def test_without_a_file_the_stub_is_untouched():
    assert YoutubeVideo._merge_offline_meta(REMOVED_STUB, False) == (
        REMOVED_STUB
    )


def test_the_merge_does_not_mutate_either_input():
    stub = dict(REMOVED_STUB)
    info_json = build_info_json()
    YoutubeVideo._merge_offline_meta(stub, info_json)

    assert stub == REMOVED_STUB
    assert info_json["thumbnail"] == ""


def test_merged_upload_date_is_what_build_published_parses():
    merged = YoutubeVideo._merge_offline_meta(REMOVED_STUB, build_info_json())
    # __init__ would read the app config out of ES
    video = YoutubeVideo.__new__(YoutubeVideo)
    video.youtube_meta = merged
    video.youtube_id = VIDEO_ID

    assert video._build_published() == "2020-02-11"


def test_the_stub_alone_still_raises():
    video = YoutubeVideo.__new__(YoutubeVideo)
    video.youtube_meta = REMOVED_STUB
    video.youtube_id = VIDEO_ID

    with pytest.raises(ValueError):
        video._build_published()


class TestUnknownCounts:
    """UNKNOWN_COUNT is an in band sentinel: -1 survives _add_stats
    only because it is truthy, so a max(0, ...) there would turn every
    unknown count into a claimed zero
    """

    @staticmethod
    def add_stats(youtube_meta: dict) -> dict:
        video = object.__new__(YoutubeVideo)
        video.youtube_meta = youtube_meta
        video.json_data = {}
        video._add_stats()

        return video.json_data["stats"]

    def test_the_merge_keeps_the_sentinel(self):
        merged = YoutubeVideo._merge_offline_meta(
            REMOVED_STUB,
            build_info_json(
                view_count=UNKNOWN_COUNT, like_count=UNKNOWN_COUNT
            ),
        )

        assert merged["view_count"] == UNKNOWN_COUNT
        assert merged["like_count"] == UNKNOWN_COUNT

    def test_the_sentinel_reaches_stats(self):
        stats = self.add_stats(
            {"view_count": UNKNOWN_COUNT, "like_count": UNKNOWN_COUNT}
        )

        assert stats["view_count"] == UNKNOWN_COUNT
        assert stats["like_count"] == UNKNOWN_COUNT

    def test_a_real_zero_still_reaches_stats_as_zero(self):
        stats = self.add_stats({"view_count": 0, "like_count": 0})

        assert stats["view_count"] == 0
        assert stats["like_count"] == 0

    def test_a_missing_count_is_still_zero_for_a_live_video(self):
        stats = self.add_stats({"title": "still on youtube"})

        assert stats["view_count"] == 0
        assert stats["like_count"] == 0


class TestActiveState:
    """only one of the two offline_import branches is a gone video"""

    @staticmethod
    def process(youtube_meta: dict, youtube_answered: bool) -> dict:
        video = object.__new__(YoutubeVideo)
        video.youtube_id = VIDEO_ID
        video.video_type = VideoTypeEnum.VIDEOS
        video.youtube_meta = youtube_meta
        video.youtube_answered = youtube_answered

        video.process_youtube_meta()

        return video.json_data

    @pytest.mark.parametrize("answered", [True, False])
    def test_active_mirrors_whether_youtube_answered(self, answered):
        json_data = self.process(build_info_json(), youtube_answered=answered)

        assert json_data["active"] is answered

    @staticmethod
    def run_build_json(served, overwrite=False, from_file=False):
        """the real build_json, with youtube, es and the file stubbed"""
        video = object.__new__(YoutubeVideo)
        video.youtube_id = VIDEO_ID
        video.video_type = VideoTypeEnum.VIDEOS
        video.offline_import = False
        video.youtube_answered = True
        video.json_data = False
        video.config = {"downloads": {"integrate_ryd": False}}

        def stub(*args, **kwargs):
            return None

        video.get_from_youtube = stub
        video.youtube_meta = served
        for name in [
            "process_youtube_meta",
            "_add_channel",
            "_add_stats",
            "add_file_path",
            "add_player",
            "add_streams",
        ]:
            setattr(video, name, stub)

        video._check_get_sb = lambda: False
        video.build_json(youtube_meta_overwrite=overwrite, from_file=from_file)

        return video

    def test_a_video_youtube_serves_normally_stays_answered(self):
        video = self.run_build_json(
            served={"id": VIDEO_ID, "title": "live", "formats": [{}]}
        )

        assert video.youtube_answered is True
        assert video.offline_import is False

    def test_a_failed_lookup_does_not_mark_a_video_gone(self):
        """
        nothing back at all is a network error or a stale cookie, not a
        gone video - guessing gone would deactivate a live one
        """
        video = self.run_build_json(
            served=False, overwrite=build_info_json(), from_file=True
        )

        assert video.youtube_answered is True
        assert video.offline_import is True

    def test_a_removed_video_answers_with_a_stub_not_with_nothing(self):
        """
        YT replies for a removed video, so it never reaches the empty
        response branch: it lands with no formats, like an age gated one
        """
        video = self.run_build_json(
            served=dict(REMOVED_STUB),
            overwrite=build_info_json(),
            from_file=True,
        )

        assert video.offline_import is True
        assert video.youtube_answered is False

    def test_no_streams_is_not_the_same_as_no_video(self):
        video = self.run_build_json(
            served=dict(AGE_GATED_META),
            overwrite=build_info_json(),
            from_file=True,
        )

        assert video.offline_import is True
        assert video.youtube_answered is True

    def test_the_stub_carries_no_identity_at_all(self):
        assert YoutubeVideo._youtube_answered(REMOVED_STUB) is False

    def test_a_real_response_carries_identity(self):
        assert YoutubeVideo._youtube_answered(AGE_GATED_META) is True

    @pytest.mark.parametrize(
        "field",
        ["fulltitle", "channel_id", "uploader", "upload_date", "timestamp"],
    )
    def test_any_single_identifying_field_counts_as_answered(self, field):
        """gone is the damaging direction, so a partial answer counts"""
        partial = dict(REMOVED_STUB)
        partial[field] = "something"

        assert YoutubeVideo._youtube_answered(partial) is True

    def test_the_default_is_active(self, monkeypatch):
        # __init__ reads the config out of ES
        monkeypatch.setattr(
            index_generic, "AppConfig", lambda: SimpleNamespace(config={})
        )

        video = YoutubeVideo(VIDEO_ID)

        assert video.youtube_answered is True
