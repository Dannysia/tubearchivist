"""channel aggregations"""

from common.src.es_connect import ElasticWrap
from common.src.helper import get_duration_str
from downscale.src.constants import downscaled_filter
from video.src.constants import VideoTypeEnum
from video.src.resolution import (
    empty_resolution,
    parse_resolution,
    resolution_agg,
)

# without this ES falls back to the mapping's first format (epoch_second)
DATE_FMT = {"format": "strict_date_optional_time"}

DATE_KEYS = [
    "published_first",
    "published_last",
    "downloaded_first",
    "downloaded_last",
]


class ChannelAggs:
    """get aggregations for a single channel"""

    path = "ta_video/_search"

    def __init__(self, channel_id: str):
        self.channel_id = channel_id

    def build_query(self) -> dict:
        """build aggregation query"""
        sub_aggs = {
            "media_size": {"sum": {"field": "media_size"}},
            "duration": {"sum": {"field": "player.duration"}},
        }

        return {
            "size": 0,
            "query": {
                "term": {"channel.channel_id": {"value": self.channel_id}}
            },
            "aggs": {
                "total_items": {"value_count": {"field": "youtube_id"}},
                "total_size": {"sum": {"field": "media_size"}},
                "total_duration": {"sum": {"field": "player.duration"}},
                "by_type": {
                    "terms": {"field": "vid_type"},
                    "aggs": sub_aggs,
                },
                "by_watched": {
                    "terms": {"field": "player.watched"},
                    "aggs": sub_aggs,
                },
                "by_resolution": resolution_agg(),
                "by_active": {"terms": {"field": "active"}},
                "downscale": {
                    "filter": downscaled_filter(),
                    "aggs": {
                        "original_size": {
                            "sum": {"field": "downscale.original_size"}
                        },
                        "new_size": {"sum": {"field": "downscale.new_size"}},
                    },
                },
                # full timestamps, not yyyy-MM-dd: the frontend renders these
                # in the viewer's timezone like every other date in the app
                "published_first": {"min": {"field": "published", **DATE_FMT}},
                "published_last": {"max": {"field": "published", **DATE_FMT}},
                "downloaded_first": {
                    "min": {"field": "date_downloaded", **DATE_FMT}
                },
                "downloaded_last": {
                    "max": {"field": "date_downloaded", **DATE_FMT}
                },
            },
        }

    def process(self) -> dict:
        """run query, build response"""
        response, _ = ElasticWrap(self.path).get(self.build_query())
        aggs = response.get("aggregations")
        if not aggs:
            return self._empty()

        total_duration = int(aggs["total_duration"]["value"])

        return {
            "total_items": {"value": int(aggs["total_items"]["value"])},
            "total_size": {"value": int(aggs["total_size"]["value"])},
            "total_duration": {
                "value": total_duration,
                "value_str": get_duration_str(total_duration),
            },
            "by_type": self._parse_type(aggs["by_type"]["buckets"]),
            "by_resolution": parse_resolution(aggs["by_resolution"]),
            "watch_progress": self._parse_watched(
                aggs["by_watched"]["buckets"], total_duration
            ),
            "availability": self._parse_active(aggs["by_active"]["buckets"]),
            "downscale": self._parse_downscale(aggs["downscale"]),
            "date_range": {
                key: aggs[key].get("value_as_string") for key in DATE_KEYS
            },
        }

    @staticmethod
    def _parse_downscale(agg: dict) -> dict:
        """parse the downscale filter bucket"""
        original_size = int(agg["original_size"]["value"])
        new_size = int(agg["new_size"]["value"])

        return {
            "doc_count": agg["doc_count"],
            "original_size": original_size,
            "new_size": new_size,
            "saved": original_size - new_size,
        }

    @staticmethod
    def _empty_downscale() -> dict:
        """downscale bucket for a channel with nothing downscaled"""
        return {
            "doc_count": 0,
            "original_size": 0,
            "new_size": 0,
            "saved": 0,
        }

    @staticmethod
    def _build_bucket(bucket: dict) -> dict:
        """parse a bucket sharing the media_size/duration sub aggs"""
        duration = int(bucket["duration"]["value"])

        return {
            "doc_count": bucket["doc_count"],
            "media_size": int(bucket["media_size"]["value"]),
            "duration": duration,
            "duration_str": get_duration_str(duration),
        }

    @staticmethod
    def _empty_bucket() -> dict:
        """zeroed bucket for a type with no videos"""
        return {
            "doc_count": 0,
            "media_size": 0,
            "duration": 0,
            "duration_str": get_duration_str(0),
        }

    def _parse_type(self, buckets: list[dict]) -> dict:
        """parse vid_type buckets, keep every type so totals reconcile"""
        parsed = {i: self._empty_bucket() for i in VideoTypeEnum.values()}
        for bucket in buckets:
            parsed[bucket["key"]] = self._build_bucket(bucket)

        return parsed

    def _parse_watched(self, buckets: list[dict], all_duration: int) -> dict:
        """parse watched buckets"""
        parsed = {
            "watched": self._empty_bucket(),
            "unwatched": self._empty_bucket(),
        }
        for bucket in buckets:
            is_watched = bucket["key_as_string"] == "true"
            key = "watched" if is_watched else "unwatched"
            parsed[key] = self._build_bucket(bucket)

        watched_duration = parsed["watched"]["duration"]
        parsed["progress"] = (
            watched_duration / all_duration if all_duration else 0
        )

        return parsed

    @staticmethod
    def _parse_active(buckets: list[dict]) -> dict:
        """parse active buckets"""
        parsed = {"active": 0, "inactive": 0}
        for bucket in buckets:
            key = "active" if bucket["key_as_string"] == "true" else "inactive"
            parsed[key] = bucket["doc_count"]

        return parsed

    def _empty(self) -> dict:
        """response shape for a channel without videos"""
        return {
            "total_items": {"value": 0},
            "total_size": {"value": 0},
            "total_duration": {"value": 0, "value_str": get_duration_str(0)},
            "by_type": {
                i: self._empty_bucket() for i in VideoTypeEnum.values()
            },
            "by_resolution": empty_resolution(),
            "watch_progress": {
                "watched": self._empty_bucket(),
                "unwatched": self._empty_bucket(),
                "progress": 0,
            },
            "availability": {"active": 0, "inactive": 0},
            "downscale": self._empty_downscale(),
            "date_range": {key: None for key in DATE_KEYS},
        }


class ChannelListAggs:
    """get per channel video stats for the channel list"""

    path = "ta_video/_search"

    # channel count is orders of magnitude below the video count, this is
    # sized to fit every channel of an archive into a single terms agg
    MAX_CHANNELS = 10000

    def __init__(self, channel_ids: list[str] | None = None):
        # None aggregates every channel, needed to sort the whole list,
        # a list limits the agg to the channels of a single page
        self.channel_ids = channel_ids

    def build_query(self) -> dict:
        """build aggregation query"""
        if self.channel_ids is None:
            query = {"match_all": {}}
            size = self.MAX_CHANNELS
        else:
            query = {"terms": {"channel.channel_id": self.channel_ids}}
            size = max(len(self.channel_ids), 1)

        return {
            "size": 0,
            "query": query,
            "aggs": {
                "by_channel": {
                    "terms": {"field": "channel.channel_id", "size": size},
                    "aggs": {
                        "media_size": {"sum": {"field": "media_size"}},
                        "duration": {"sum": {"field": "player.duration"}},
                        "watched_duration": {
                            "filter": {"term": {"player.watched": True}},
                            "aggs": {
                                "duration": {
                                    "sum": {"field": "player.duration"}
                                }
                            },
                        },
                        "last_download": {
                            "max": {"field": "date_downloaded", **DATE_FMT}
                        },
                        "last_published": {
                            "max": {"field": "published", **DATE_FMT}
                        },
                    },
                }
            },
        }

    def process(self) -> dict[str, dict]:
        """run query, build a channel_id to stats lookup"""
        if self.channel_ids is not None and not self.channel_ids:
            return {}

        response, _ = ElasticWrap(self.path).get(self.build_query())
        aggs = response.get("aggregations")
        if not aggs:
            return {}

        return {
            bucket["key"]: self._build_stats(bucket)
            for bucket in aggs["by_channel"]["buckets"]
        }

    @staticmethod
    def _build_stats(bucket: dict) -> dict:
        """parse a single channel bucket"""
        duration = int(bucket["duration"]["value"])
        watched = int(bucket["watched_duration"]["duration"]["value"])

        return {
            "doc_count": bucket["doc_count"],
            "media_size": int(bucket["media_size"]["value"]),
            "duration": duration,
            "duration_str": get_duration_str(duration),
            "watch_progress": watched / duration if duration else 0,
            # sortable as is, ES returns a fixed width timestamp
            "last_download": bucket["last_download"].get("value_as_string"),
            "last_published": bucket["last_published"].get("value_as_string"),
        }

    @staticmethod
    def empty_stats() -> dict:
        """stats for a channel without indexed videos"""
        return {
            "doc_count": 0,
            "media_size": 0,
            "duration": 0,
            "duration_str": get_duration_str(0),
            "watch_progress": 0,
            "last_download": None,
            "last_published": None,
        }
