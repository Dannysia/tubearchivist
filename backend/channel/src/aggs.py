from common.src.es_connect import ElasticWrap
from common.src.helper import get_duration_str
from common.src.search_errors import SearchUnavailable
from downscale.src.constants import (
    VIDEO_SIZE_FIELDS,
    downscaled_filter,
    parse_saved_bands,
    parse_transitions,
    saved_percent_agg,
    transition_agg,
)
from video.src.constants import VideoTypeEnum
from video.src.resolution import (
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
    path = "ta_video/_search"

    def __init__(self, channel_id: str):
        self.channel_id = channel_id

    def build_query(self) -> dict:
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
                        "by_transition": transition_agg(),
                        "by_saved": saved_percent_agg(VIDEO_SIZE_FIELDS),
                    },
                },
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
        response, status_code = ElasticWrap(self.path).get(self.build_query())
        if status_code != 200:
            raise SearchUnavailable(
                f"channel aggregation failed, es answered {status_code}"
            )

        aggs = response["aggregations"]

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
        original_size = int(agg["original_size"]["value"])
        new_size = int(agg["new_size"]["value"])

        return {
            "doc_count": agg["doc_count"],
            "original_size": original_size,
            "new_size": new_size,
            "saved": original_size - new_size,
            "by_transition": parse_transitions(agg["by_transition"]),
            "by_saved": parse_saved_bands(agg["by_saved"], agg["doc_count"]),
        }

    @staticmethod
    def _build_bucket(bucket: dict) -> dict:
        duration = int(bucket["duration"]["value"])

        return {
            "doc_count": bucket["doc_count"],
            "media_size": int(bucket["media_size"]["value"]),
            "duration": duration,
            "duration_str": get_duration_str(duration),
        }

    @staticmethod
    def _empty_bucket() -> dict:
        return {
            "doc_count": 0,
            "media_size": 0,
            "duration": 0,
            "duration_str": get_duration_str(0),
        }

    def _parse_type(self, buckets: list[dict]) -> dict:
        parsed = {i: self._empty_bucket() for i in VideoTypeEnum.values()}
        for bucket in buckets:
            parsed[bucket["key"]] = self._build_bucket(bucket)

        return parsed

    def _parse_watched(self, buckets: list[dict], all_duration: int) -> dict:
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
        parsed = {"active": 0, "inactive": 0}
        for bucket in buckets:
            key = "active" if bucket["key_as_string"] == "true" else "inactive"
            parsed[key] = bucket["doc_count"]

        return parsed


class ChannelListAggs:
    path = "ta_video/_search"

    def __init__(self, channel_ids: list[str]):
        self.channel_ids = channel_ids

    def build_query(self) -> dict:
        return {
            "size": 0,
            "query": {"terms": {"channel.channel_id": self.channel_ids}},
            "aggs": {
                "by_channel": {
                    "terms": {
                        "field": "channel.channel_id",
                        "size": max(len(self.channel_ids), 1),
                    },
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
        if not self.channel_ids:
            return {}

        response, status_code = ElasticWrap(self.path).get(self.build_query())
        if status_code != 200:
            raise SearchUnavailable(
                f"channel stats aggregation failed, es answered {status_code}"
            )

        aggs = response["aggregations"]

        return {
            bucket["key"]: self._build_stats(bucket)
            for bucket in aggs["by_channel"]["buckets"]
        }

    @staticmethod
    def _build_stats(bucket: dict) -> dict:
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
        return {
            "doc_count": 0,
            "media_size": 0,
            "duration": 0,
            "duration_str": get_duration_str(0),
            "watch_progress": 0,
            "last_download": None,
            "last_published": None,
        }
