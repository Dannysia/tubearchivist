import json
from datetime import datetime

from common.src.es_connect import ElasticWrap
from common.src.queue_interact import QueueDocMissing, QueueWriteError
from common.src.urlparser import ParsedURLType
from download.src.extraction_interact import ExtractionInteract
from download.src.queue import PendingList
from video.src.constants import VideoTypeEnum


class _StopRun(Exception):
    pass


class ExtractionQueue:
    ACTIVE_STATUSES = ["pending", "extracting"]

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
        """returns how many were added"""
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
            extraction_id = self._build_id(
                entry["type"], entry["url"], vid_type
            )
            action = {
                "index": {"_index": "ta_extraction", "_id": extraction_id}
            }
            bulk_list.append(json.dumps(action))
            bulk_list.append(json.dumps(doc))

        bulk_list.append("\n")
        query_str = "\n".join(bulk_list)
        response, status_code = ElasticWrap("_bulk?refresh=true").post(
            query_str, ndjson=True
        )
        if status_code not in [200, 201] or response.get("errors"):
            raise QueueWriteError(
                f"ta_extraction: adding {len(entries)} entries failed, "
                f"es answered {status_code}"
            )

        return len(entries)

    @staticmethod
    def _build_id(item_type: str, youtube_id: str, vid_type) -> str:
        return f"{item_type}_{youtube_id}_{vid_type or 'na'}"

    def run_queue(self) -> tuple[int, int, bool]:
        """returns (resolved, failed, any_auto_start)"""
        warm = PendingList(youtube_ids=[], task=self.task)
        warm.get_download()
        warm.get_indexed()
        warm.get_channels()

        resolved = 0
        failed = 0
        any_auto_start = False

        try:
            while True:
                entry_id, entry_doc = self._get_next()
                if self.task and self.task.is_stopped():
                    break
                if not entry_doc:
                    break

                interact = ExtractionInteract(entry_id)
                if not self._write_state(interact.mark_extracting):
                    continue

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

                handler.parse_url_list(
                    status=entry_doc.get("target_status", "pending")
                )
                if self.task and self.task.is_stopped():
                    self._write_state(interact.mark_pending)
                    break

                if handler.extraction_failed:
                    failed += 1
                    self._write_state(
                        interact.mark_failed, "extraction failed, see logs"
                    )
                else:
                    resolved += 1
                    if entry_doc["auto_start"]:
                        any_auto_start = True
                    self._write_state(interact.delete_item)

                warm.get_download()
        except _StopRun:
            pass

        return resolved, failed, any_auto_start

    @staticmethod
    def _write_state(write, *args) -> bool:
        try:
            write(*args)
        except QueueDocMissing as err:
            print(f"[extraction] skipping, {err}")
            return False
        except QueueWriteError as err:
            print(f"[extraction] stopping the run, {err}")
            raise _StopRun from err

        return True

    @classmethod
    def has_work(cls) -> bool:
        data = {"size": 0, "query": {"terms": {"status": cls.ACTIVE_STATUSES}}}
        response, _ = ElasticWrap("ta_extraction/_search").get(data=data)
        total = response.get("hits", {}).get("total", {})
        return bool(total.get("value"))

    @classmethod
    def _get_next(cls) -> tuple[str | None, dict | None]:
        data = {
            "size": 1,
            "query": {"terms": {"status": cls.ACTIVE_STATUSES}},
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
