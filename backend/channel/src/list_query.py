"""resolve a page of the channel list"""

from channel.src.aggs import ChannelListAggs
from channel.src.constants import ChannelSortEnum
from common.src.es_connect import ElasticWrap
from common.src.search_processor import SearchProcess


class ChannelListQuery:
    """get a sorted page of channels with their video stats

    the stat sorts are not backed by a field on the channel doc, they get
    resolved from the video index and applied here, everything else is
    sorted and paginated by ES
    """

    path = "ta_channel/_search"

    def __init__(
        self,
        query_filter: str | None,
        sort_by: ChannelSortEnum,
        order: str,
    ):
        self.query = self._build_query(query_filter)
        self.sort_by = sort_by
        self.order = order

    @staticmethod
    def _build_query(query_filter: str | None) -> dict:
        """build channel filter query"""
        must_list = []
        if query_filter is not None:
            must_list.append(
                {
                    "term": {
                        "channel_subscribed": {
                            "value": query_filter == "subscribed"
                        }
                    }
                }
            )

        return {"bool": {"must": must_list}}

    def get_page(self, page_from: int, page_size: int) -> tuple[list, int]:
        """get channels of the page and the total hits"""
        if self.sort_by.is_stat:
            return self._by_stat(page_from, page_size)

        return self._by_field(page_from, page_size)

    def _by_field(self, page_from: int, page_size: int) -> tuple[list, int]:
        """sort and paginate on a field of the channel doc"""
        data = {
            "query": self.query,
            "sort": [{self.sort_by.value: {"order": self.order}}],
            "from": page_from,
            "size": page_size,
        }
        response, _ = ElasticWrap(self.path).get(data)
        if not response.get("hits"):
            return [], 0

        channels = SearchProcess(response).process()
        total_hits = response["hits"]["total"]["value"]

        # only the channels of this page need their stats looked up
        ids = [i["channel_id"] for i in channels]
        self._attach_stats(channels, ChannelListAggs(ids).process())

        return channels, total_hits

    def _by_stat(self, page_from: int, page_size: int) -> tuple[list, int]:
        """sort on the video aggregation, paginate here"""
        all_ids = self._get_all_ids()
        stats = ChannelListAggs().process()
        # the ids come in name order and sort is stable, so channels
        # sharing a value, zero included, stay alphabetical
        all_ids.sort(key=self._build_sort_key(stats), reverse=self._reverse)

        page_to = page_from + page_size
        page_ids = all_ids[page_from:page_to]
        channels = self._get_by_ids(page_ids)
        self._attach_stats(channels, stats)

        return channels, len(all_ids)

    @property
    def _reverse(self) -> bool:
        """python sort direction"""
        return self.order == "desc"

    def _get_all_ids(self) -> list[str]:
        """get every matching channel id, in name order"""
        data = {
            "query": self.query,
            "sort": [{ChannelSortEnum.NAME.value: {"order": "asc"}}],
            "_source": False,
            "size": ChannelListAggs.MAX_CHANNELS,
        }
        response, _ = ElasticWrap(self.path).get(data)
        if not response.get("hits"):
            return []

        return [i["_id"] for i in response["hits"]["hits"]]

    def _build_sort_key(self, stats: dict[str, dict]):
        """sort channel ids by their aggregated value"""
        field = self.sort_by.value
        empty = ChannelListAggs.empty_stats()

        def sort_key(channel_id: str):
            value = stats.get(channel_id, empty)[field]
            # dates are null until a channel has videos, sort them lowest
            return "" if value is None else value

        return sort_key

    def _get_by_ids(self, channel_ids: list[str]) -> list:
        """get channel docs, restore the requested order"""
        if not channel_ids:
            return []

        data = {
            "query": {"ids": {"values": channel_ids}},
            "size": len(channel_ids),
        }
        response, _ = ElasticWrap(self.path).get(data)
        if not response.get("hits"):
            return []

        channels = SearchProcess(response).process()
        by_id = {i["channel_id"]: i for i in channels}

        return [by_id[i] for i in channel_ids if i in by_id]

    @staticmethod
    def _attach_stats(channels: list, stats: dict[str, dict]) -> None:
        """add the video stats to every channel of the page"""
        for channel in channels:
            channel["channel_stats"] = stats.get(
                channel["channel_id"], ChannelListAggs.empty_stats()
            )
