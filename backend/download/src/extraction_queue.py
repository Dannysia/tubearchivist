"""
Functionality:
- handle extraction queue
- resolve videos/channels/playlists into the download queue
- linked with ta_extraction index
"""

import json
from datetime import datetime

from common.src.es_connect import ElasticWrap
from common.src.urlparser import ParsedURLType
from download.src.extraction_interact import ExtractionInteract
from download.src.queue import PendingList
from video.src.constants import VideoTypeEnum


class ExtractionQueue:
    """manage the extraction queue"""

    def __init__(self, task=None):
        self.task = task

    def add_to_queue(
        self,
        entries: list[ParsedURLType],
        auto_start: bool = False,
        flat: bool = False,
        force: bool = False,
        target_status: str = "pending",
    ) -> int:
        """bulk add entries to the extraction queue"""
        if not entries:
            return 0

        bulk_list = []
        for entry in entries:
            vid_type = entry.get("vid_type")
            if isinstance(vid_type, VideoTypeEnum):
                vid_type = vid_type.value

            doc = {
                "youtube_id": entry["url"],
                "item_type": entry["type"],
                "vid_type": vid_type,
                "limit": entry.get("limit"),
                "status": "pending",
                "target_status": target_status,
                "auto_start": auto_start,
                "flat": flat,
                "force": force,
                "timestamp": int(datetime.now().timestamp()),
            }
            extraction_id = self._build_id(entry["type"], entry["url"], vid_type)
            action = {"index": {"_index": "ta_extraction", "_id": extraction_id}}
            bulk_list.append(json.dumps(action))
            bulk_list.append(json.dumps(doc))

        bulk_list.append("\n")
        query_str = "\n".join(bulk_list)
        response, status_code = ElasticWrap("_bulk?refresh=true").post(
            query_str, ndjson=True
        )
        if status_code not in [200, 201]:
            print(response)
            return 0

        return len(entries)

    @staticmethod
    def _build_id(item_type: str, youtube_id: str, vid_type) -> str:
        """build deterministic composite id, avoid collisions on multi-tab
        channel scans reusing the same channel_id"""
        return f"{item_type}_{youtube_id}_{vid_type or 'na'}"

    def run_queue(self) -> tuple[int, int, bool]:
        """resolve all pending/extracting entries, returns (resolved, failed, any_auto_start)"""
        warm = PendingList(youtube_ids=[], task=self.task)
        warm.get_download()
        warm.get_indexed()
        warm.get_channels()

        resolved = 0
        failed = 0
        any_auto_start = False

        while True:
            entry_id, entry_doc = self._get_next()
            if self.task and self.task.is_stopped():
                break
            if not entry_doc:
                break

            ExtractionInteract(entry_id).mark_extracting()
            parsed_entry: ParsedURLType = {
                "type": entry_doc["item_type"],
                "url": entry_doc["youtube_id"],
                "vid_type": entry_doc.get("vid_type"),
                "limit": entry_doc.get("limit"),
            }

            handler = PendingList(
                youtube_ids=[parsed_entry],
                task=self.task,
                auto_start=entry_doc["auto_start"],
                flat=entry_doc["flat"],
                force=entry_doc["force"],
            )
            handler.all_pending = warm.all_pending
            handler.all_ignored = warm.all_ignored
            handler.to_skip = list(warm.to_skip)
            handler.all_videos = warm.all_videos
            handler.all_channels = warm.all_channels
            handler.channel_overwrites = warm.channel_overwrites

            handler.parse_url_list(status=entry_doc.get("target_status", "pending"))

            if handler.extraction_failed:
                failed += 1
                ExtractionInteract(entry_id).mark_failed(
                    "extraction failed, see logs"
                )
                continue

            resolved += 1
            if entry_doc["auto_start"]:
                any_auto_start = True
            ExtractionInteract(entry_id).delete_item()

        return resolved, failed, any_auto_start

    @staticmethod
    def _get_next() -> tuple[str | None, dict | None]:
        """get next pending/extracting item in the extraction queue"""
        data = {
            "size": 1,
            "query": {"terms": {"status": ["pending", "extracting"]}},
            "sort": [
                {"auto_start": {"order": "desc"}},
                {"timestamp": {"order": "asc"}},
            ],
        }
        path = "ta_extraction/_search"
        response, _ = ElasticWrap(path).get(data=data)
        hits = response["hits"]["hits"]
        if not hits:
            return None, None

        hit = hits[0]
        return hit["_id"], hit["_source"]
