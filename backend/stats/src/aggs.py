"""aggregations"""

from common.src.env_settings import EnvironmentSettings
from common.src.es_connect import ElasticWrap
from common.src.helper import get_duration_str
from django.conf import settings
from downscale.src.constants import downscaled_filter


class AggBase:
    """base class for aggregation calls"""

    path: str = ""
    data: dict = {}
    name: str = ""

    def get(self):
        """make get call"""
        response, _ = ElasticWrap(self.path).get(self.data)
        if settings.DEBUG:
            print(
                f"[agg][{self.name}] took {response.get('took')} ms to process"
            )

        return response.get("aggregations")

    def process(self):
        """implement in subclassess"""
        raise NotImplementedError


class Video(AggBase):
    """get video stats"""

    name = "video_stats"
    path = "ta_video/_search"
    data = {
        "size": 0,
        "aggs": {
            "video_type": {
                "terms": {"field": "vid_type"},
                "aggs": {
                    "media_size": {"sum": {"field": "media_size"}},
                    "duration": {"sum": {"field": "player.duration"}},
                },
            },
            "video_active": {
                "terms": {"field": "active"},
                "aggs": {
                    "media_size": {"sum": {"field": "media_size"}},
                    "duration": {"sum": {"field": "player.duration"}},
                },
            },
            "video_media_size": {"sum": {"field": "media_size"}},
            "video_count": {"value_count": {"field": "youtube_id"}},
            "duration": {"sum": {"field": "player.duration"}},
        },
    }

    def process(self):
        """process aggregation"""
        aggregations = self.get()
        if not aggregations:
            return None

        duration = int(aggregations["duration"]["value"])
        response = {
            "doc_count": aggregations["video_count"]["value"],
            "media_size": int(aggregations["video_media_size"]["value"]),
            "duration": duration,
            "duration_str": get_duration_str(duration),
        }
        for bucket in aggregations["video_type"]["buckets"]:
            duration = int(bucket["duration"].get("value"))
            response.update(
                {
                    f"type_{bucket['key']}": {
                        "doc_count": bucket.get("doc_count"),
                        "media_size": int(bucket["media_size"].get("value")),
                        "duration": duration,
                        "duration_str": get_duration_str(duration),
                    }
                }
            )

        for bucket in aggregations["video_active"]["buckets"]:
            duration = int(bucket["duration"].get("value"))
            response.update(
                {
                    f"active_{bucket['key_as_string']}": {
                        "doc_count": bucket.get("doc_count"),
                        "media_size": int(bucket["media_size"].get("value")),
                        "duration": duration,
                        "duration_str": get_duration_str(duration),
                    }
                }
            )

        return response


class Channel(AggBase):
    """get channel stats"""

    name = "channel_stats"
    path = "ta_channel/_search"
    data = {
        "size": 0,
        "aggs": {
            "channel_count": {"value_count": {"field": "channel_id"}},
            "channel_active": {"terms": {"field": "channel_active"}},
            "channel_subscribed": {"terms": {"field": "channel_subscribed"}},
        },
    }

    def process(self):
        """process aggregation"""
        aggregations = self.get()
        if not aggregations:
            return None

        response = {
            "doc_count": aggregations["channel_count"].get("value"),
        }
        for bucket in aggregations["channel_active"]["buckets"]:
            key = f"active_{bucket['key_as_string']}"
            response.update({key: bucket.get("doc_count")})
        for bucket in aggregations["channel_subscribed"]["buckets"]:
            key = f"subscribed_{bucket['key_as_string']}"
            response.update({key: bucket.get("doc_count")})

        return response


class Playlist(AggBase):
    """get playlist stats"""

    name = "playlist_stats"
    path = "ta_playlist/_search"
    data = {
        "size": 0,
        "aggs": {
            "playlist_count": {"value_count": {"field": "playlist_id"}},
            "playlist_active": {"terms": {"field": "playlist_active"}},
            "playlist_subscribed": {"terms": {"field": "playlist_subscribed"}},
        },
    }

    def process(self):
        """process aggregation"""
        aggregations = self.get()
        if not aggregations:
            return None

        response = {"doc_count": aggregations["playlist_count"].get("value")}
        for bucket in aggregations["playlist_active"]["buckets"]:
            key = f"active_{bucket['key_as_string']}"
            response.update({key: bucket.get("doc_count")})
        for bucket in aggregations["playlist_subscribed"]["buckets"]:
            key = f"subscribed_{bucket['key_as_string']}"
            response.update({key: bucket.get("doc_count")})

        return response


class Download(AggBase):
    """get downloads queue stats"""

    name = "download_queue_stats"
    path = "ta_download/_search"
    data = {
        "size": 0,
        "aggs": {
            "status": {"terms": {"field": "status"}},
            "video_type": {
                "filter": {"term": {"status": "pending"}},
                "aggs": {"type_pending": {"terms": {"field": "vid_type"}}},
            },
        },
    }

    def process(self):
        """process aggregation"""
        aggregations = self.get()
        response = {}
        if not aggregations:
            return None

        for bucket in aggregations["status"]["buckets"]:
            response.update({bucket["key"]: bucket.get("doc_count")})

        for bucket in aggregations["video_type"]["type_pending"]["buckets"]:
            key = f"pending_{bucket['key']}"
            response.update({key: bucket.get("doc_count")})

        return response


class WatchProgress(AggBase):
    """get watch progress"""

    name = "watch_progress"
    path = "ta_video/_search"
    data = {
        "size": 0,
        "aggs": {
            name: {
                "terms": {"field": "player.watched"},
                "aggs": {
                    "watch_docs": {
                        "filter": {"terms": {"player.watched": [True, False]}},
                        "aggs": {
                            "true_count": {"value_count": {"field": "_index"}},
                            "duration": {"sum": {"field": "player.duration"}},
                        },
                    },
                },
            },
            "total_duration": {"sum": {"field": "player.duration"}},
            "total_vids": {"value_count": {"field": "_index"}},
        },
    }

    def process(self):
        """make the call"""
        aggregations = self.get()
        response = {}
        if not aggregations:
            return None

        buckets = aggregations[self.name]["buckets"]
        all_duration = int(aggregations["total_duration"].get("value"))
        response.update(
            {
                "total": {
                    "duration": all_duration,
                    "duration_str": get_duration_str(all_duration),
                    "items": aggregations["total_vids"].get("value"),
                }
            }
        )

        for bucket in buckets:
            response.update(self._build_bucket(bucket, all_duration))

        return response

    @staticmethod
    def _build_bucket(bucket, all_duration):
        """parse bucket"""

        duration = int(bucket["watch_docs"]["duration"]["value"])
        duration_str = get_duration_str(duration)
        items = bucket["watch_docs"]["true_count"]["value"]
        if bucket["key_as_string"] == "false":
            key = "unwatched"
        else:
            key = "watched"

        bucket_parsed = {
            key: {
                "duration": duration,
                "duration_str": duration_str,
                "progress": duration / all_duration if all_duration else 0,
                "items": items,
            }
        }

        return bucket_parsed


class DownloadHist(AggBase):
    """get downloads histogram last week"""

    name = "videos_last_week"
    path = "ta_video/_search"
    data = {
        "size": 0,
        "aggs": {
            name: {
                "date_histogram": {
                    "field": "date_downloaded",
                    "calendar_interval": "day",
                    "format": "yyyy-MM-dd",
                    "order": {"_key": "desc"},
                    "time_zone": EnvironmentSettings.TZ,
                },
                "aggs": {
                    "total_videos": {"value_count": {"field": "youtube_id"}},
                    "media_size": {"sum": {"field": "media_size"}},
                },
            }
        },
        "query": {
            "range": {
                "date_downloaded": {
                    "gte": "now-7d/d",
                    "time_zone": EnvironmentSettings.TZ,
                }
            }
        },
    }

    def process(self):
        """process query"""
        aggregations = self.get()
        if not aggregations:
            return None

        buckets = aggregations[self.name]["buckets"]

        response = [
            {
                "date": i.get("key_as_string"),
                "count": i.get("doc_count"),
                "media_size": i["media_size"].get("value"),
            }
            for i in buckets
        ]

        return response


class BiggestChannel(AggBase):
    """get channel aggregations"""

    def __init__(self, order):
        self.data["aggs"][self.name]["multi_terms"]["order"] = {order: "desc"}

    name = "channel_stats"
    path = "ta_video/_search"
    data = {
        "size": 0,
        "aggs": {
            name: {
                "multi_terms": {
                    "terms": [
                        {"field": "channel.channel_name.keyword"},
                        {"field": "channel.channel_id"},
                    ],
                    "order": {"doc_count": "desc"},
                },
                "aggs": {
                    "doc_count": {"value_count": {"field": "_index"}},
                    "duration": {"sum": {"field": "player.duration"}},
                    "media_size": {"sum": {"field": "media_size"}},
                },
            },
        },
    }
    order_choices = ["doc_count", "duration", "media_size"]

    def process(self):
        """process aggregation, order_by validated in the view"""

        aggregations = self.get()
        if not aggregations:
            return None

        buckets = aggregations[self.name]["buckets"]

        response = [
            {
                "id": i["key"][1],
                "name": i["key"][0].title(),
                "doc_count": i["doc_count"]["value"],
                "duration": i["duration"]["value"],
                "duration_str": get_duration_str(int(i["duration"]["value"])),
                "media_size": i["media_size"]["value"],
            }
            for i in buckets
        ]

        return response


class Downscale(AggBase):
    """get downscale savings stats"""

    name = "downscale_stats"
    path = "ta_video/_search"

    # how many encoder panels to break the savings down into. The set of
    # distinct encoder strings is naturally small - six local encoders
    # plus whatever remote workers report - and does not grow with the
    # archive the way channels or days do, so this is a defensive bound
    # rather than a real ceiling. Anything past it is folded into a
    # single OTHER_ENCODER entry, so the panels always reconcile with
    # the total instead of silently dropping savings.
    ENCODER_LIMIT = 8
    OTHER_ENCODER = "other"

    _size_aggs = {
        "original_size": {"sum": {"field": "downscale.original_size"}},
        "new_size": {"sum": {"field": "downscale.new_size"}},
    }
    data = {
        "size": 0,
        "query": downscaled_filter(),
        "aggs": {
            **_size_aggs,
            # AggBase.get() returns only the aggregations, so the hit
            # total is not available - count here instead
            "video_count": {"value_count": {"field": "youtube_id"}},
            "by_encoder": {
                # ordered by the data each encoder actually processed,
                # so a truncated tail is the least significant one
                "terms": {
                    "field": "downscale.encoder",
                    "size": ENCODER_LIMIT,
                    "order": {"original_size": "desc"},
                },
                "aggs": _size_aggs,
            },
        },
    }

    def process(self):
        """process aggregation"""
        aggregations = self.get()
        if not aggregations:
            return None

        response = self._build_totals(
            int(aggregations["video_count"]["value"]), aggregations
        )
        by_encoder = [
            self._build_totals(bucket["doc_count"], bucket, bucket["key"])
            for bucket in aggregations["by_encoder"]["buckets"]
        ]
        remainder = self._build_remainder(response, by_encoder)
        if remainder:
            by_encoder.append(remainder)

        response["by_encoder"] = by_encoder

        return response

    @classmethod
    def _build_remainder(cls, total: dict, shown: list[dict]) -> dict | None:
        """
        fold every encoder past ENCODER_LIMIT into one entry. Derived by
        subtracting what is shown from the total rather than from the
        dropped buckets themselves, which the terms agg never returns,
        so it stays exact however many encoders were left out
        """
        doc_count = total["doc_count"] - sum(i["doc_count"] for i in shown)
        if doc_count <= 0:
            return None

        original_size = total["original_size"] - sum(
            i["original_size"] for i in shown
        )
        new_size = total["new_size"] - sum(i["new_size"] for i in shown)
        saved = original_size - new_size

        return {
            "encoder": cls.OTHER_ENCODER,
            "doc_count": doc_count,
            "original_size": original_size,
            "new_size": new_size,
            "saved": saved,
            "saved_percent": (
                round(saved / original_size * 100, 2) if original_size else 0
            ),
        }

    @staticmethod
    def _build_totals(
        doc_count: int, agg: dict, encoder: str | None = None
    ) -> dict:
        """build the savings numbers shared by the total and each encoder"""
        original_size = int(agg["original_size"]["value"])
        new_size = int(agg["new_size"]["value"])
        saved = original_size - new_size

        totals = {
            "doc_count": doc_count,
            "original_size": original_size,
            "new_size": new_size,
            "saved": saved,
            # of the original size, so a 76% saving means the archive
            # now holds 24% of what these videos used to take
            "saved_percent": (
                round(saved / original_size * 100, 2) if original_size else 0
            ),
        }
        if encoder is not None:
            totals["encoder"] = encoder

        return totals
