"""test the offline metadata merge for manual import

A video removed by YouTube does not return nothing, it returns a stub.
That stub is truthy, so a hand written info.json used to be discarded
for exactly the videos it exists to rescue - see the ValueError from
_build_published on the null upload_date
"""

from types import SimpleNamespace

import pytest
from appsettings.src.manual import UNKNOWN_COUNT
from common.src import index_generic
from video.src.constants import VideoTypeEnum
from video.src.index import YoutubeVideo

VIDEO_ID = "ibyCDgITtxg"

# what yt-dlp actually returned for a video removed for violating
# community guidelines, with ignore_no_formats_error set
REMOVED_STUB = {
    "id": VIDEO_ID,
    "title": f"youtube video #{VIDEO_ID}",
    # the title before YoutubeDL substitutes the generic one above.
    # Measured empty on live removed videos, not assumed
    "fulltitle": "",
    "upload_date": None,
    "timestamp": None,
    "channel_id": None,
    "uploader": None,
    "thumbnail": f"https://i.ytimg.com/vi_webp/{VIDEO_ID}/maxresdefault.webp",
    "formats": [],
}


# what YT returns for an age gated or members only video: no formats to
# download, but the video's real metadata intact. The case that must not
# be mistaken for a removed one
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


class TestUnknownCounts:
    """UNKNOWN_COUNT has to reach the index intact

    It is an in band sentinel, so every hop between the info.json and
    stats.view_count has to leave it alone. _add_stats in particular
    only passes it through because -1 is truthy - a rewrite of that line
    to something like max(0, ...) would silently turn every unknown
    count into a claimed zero, which is what these pin against.
    """

    @staticmethod
    def add_stats(youtube_meta: dict) -> dict:
        """_add_stats on its own, it reads and writes nothing else"""
        video = object.__new__(YoutubeVideo)
        video.youtube_meta = youtube_meta
        video.json_data = {}
        video._add_stats()

        return video.json_data["stats"]

    def test_the_merge_keeps_the_sentinel(self):
        """it is a set value in the file, not a blank one"""
        merged = YoutubeVideo._merge_offline_meta(
            REMOVED_STUB,
            build_info_json(
                view_count=UNKNOWN_COUNT, like_count=UNKNOWN_COUNT
            ),
        )

        assert merged["view_count"] == UNKNOWN_COUNT
        assert merged["like_count"] == UNKNOWN_COUNT

    def test_the_sentinel_reaches_stats(self):
        """what actually gets indexed, and read back by StatsSerializer"""
        stats = self.add_stats(
            {"view_count": UNKNOWN_COUNT, "like_count": UNKNOWN_COUNT}
        )

        assert stats["view_count"] == UNKNOWN_COUNT
        assert stats["like_count"] == UNKNOWN_COUNT

    def test_a_real_zero_still_reaches_stats_as_zero(self):
        """the sentinel must not swallow a genuine zero"""
        stats = self.add_stats({"view_count": 0, "like_count": 0})

        assert stats["view_count"] == 0
        assert stats["like_count"] == 0

    def test_a_missing_count_is_still_zero_for_a_live_video(self):
        """
        the sentinel is written by the import form only. A video YT
        serves without a count is unchanged, zero as it has always been
        """
        stats = self.add_stats({"title": "still on youtube"})

        assert stats["view_count"] == 0
        assert stats["like_count"] == 0


class TestActiveState:
    """a video YT no longer serves is indexed inactive

    active used to be hardcoded true for everything, so a removed video
    went in looking live and stayed that way until a reindex pass picked
    it up and called deactivate. The two offline_import branches mean
    different things though, and only one of them is a gone video
    """

    @staticmethod
    def process(youtube_meta: dict, youtube_answered: bool) -> dict:
        """process_youtube_meta on its own, no youtube and no es"""
        video = object.__new__(YoutubeVideo)
        video.youtube_id = VIDEO_ID
        video.video_type = VideoTypeEnum.VIDEOS
        video.youtube_meta = youtube_meta
        video.youtube_answered = youtube_answered

        video.process_youtube_meta()

        return video.json_data

    @pytest.mark.parametrize("answered", [True, False])
    def test_active_mirrors_whether_youtube_answered(self, answered):
        """
        active used to be hardcoded true here. The cases that decide
        what youtube_answered is are covered by the build_json tests
        below, this just pins that the field follows it
        """
        json_data = self.process(build_info_json(), youtube_answered=answered)

        assert json_data["active"] is answered

    @staticmethod
    def run_build_json(served, overwrite=False, from_file=False):
        """
        build_json as far as the branch that decides this, with youtube,
        es and the media file stubbed out. Driving the real method is
        the point: the three cases differ only in what youtube returned
        """
        video = object.__new__(YoutubeVideo)
        video.youtube_id = VIDEO_ID
        video.video_type = VideoTypeEnum.VIDEOS
        video.offline_import = False
        video.youtube_answered = True
        video.json_data = False
        video.config = {"downloads": {"integrate_ryd": False}}

        def stub(*args, **kwargs):
            """everything past the branch needs youtube, es or a file"""
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
        """the ordinary download path, formats and all"""
        video = self.run_build_json(
            served={"id": VIDEO_ID, "title": "live", "formats": [{}]}
        )

        assert video.youtube_answered is True
        assert video.offline_import is False

    def test_a_failed_lookup_does_not_mark_a_video_gone(self):
        """
        nothing back at all is a network error, a rate limit or a stale
        cookie - a removed video answers with a stub instead. Guessing
        gone here would deactivate a live video on a transient failure,
        with no reindex path back
        """
        video = self.run_build_json(
            served=False, overwrite=build_info_json(), from_file=True
        )

        assert video.youtube_answered is True
        assert video.offline_import is True

    def test_a_removed_video_answers_with_a_stub_not_with_nothing(self):
        """
        the case this is all for, and the one the first attempt at it
        got wrong: YT replies for a removed video, so it never reaches
        the empty-response branch. It lands here with no formats, the
        same branch an age gated video takes
        """
        video = self.run_build_json(
            served=dict(REMOVED_STUB),
            overwrite=build_info_json(),
            from_file=True,
        )

        assert video.offline_import is True
        assert video.youtube_answered is False

    def test_no_streams_is_not_the_same_as_no_video(self):
        """
        age gated and members only videos come back with metadata and no
        formats. They are still on youtube, just not downloadable, so
        they take the offline_import path without being marked removed
        """
        video = self.run_build_json(
            served=dict(AGE_GATED_META),
            overwrite=build_info_json(),
            from_file=True,
        )

        assert video.offline_import is True
        assert video.youtube_answered is True

    def test_the_stub_carries_no_identity_at_all(self):
        """what _youtube_answered keys off, stated as its own fact"""
        assert YoutubeVideo._youtube_answered(REMOVED_STUB) is False

    def test_a_real_response_carries_identity(self):
        """an age gated video still says who and what it is"""
        assert YoutubeVideo._youtube_answered(AGE_GATED_META) is True

    @pytest.mark.parametrize(
        "field",
        ["fulltitle", "channel_id", "uploader", "upload_date", "timestamp"],
    )
    def test_any_single_identifying_field_counts_as_answered(self, field):
        """
        marking a video gone is the damaging direction to get wrong, so
        a partial answer is treated as the video still being there
        """
        partial = dict(REMOVED_STUB)
        partial[field] = "something"

        assert YoutubeVideo._youtube_answered(partial) is True

    def test_the_default_is_active(self, monkeypatch):
        """
        process_youtube_meta has callers that never touch build_json,
        e.g. download.src.subscriptions - they must be unaffected
        """
        # YouTubeItem.__init__ reads the config, which is an es round
        # trip and nothing this cares about
        monkeypatch.setattr(
            index_generic, "AppConfig", lambda: SimpleNamespace(config={})
        )

        video = YoutubeVideo(VIDEO_ID)

        assert video.youtube_answered is True
