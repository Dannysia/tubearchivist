from common.src.es_connect import IndexPaginate
from downscale.src.constants import QUEUE_DOC_SOURCE_FIELDS
from downscale.src.downscale import dispatch_pending_downscales
from downscale.src.queue_interact import ALREADY_ACTIVE, DownscaleInteract


class ChannelDownscale:
    def __init__(self, channel_id: str, target_height: int, task=None):
        self.channel_id = channel_id
        self.target_height = target_height
        self.task = task
        self.queued: list[str] = []
        self.skipped: list[str] = []

    def run(self) -> None:
        videos = self._get_videos()
        total = len(videos)
        for idx, video in enumerate(videos, start=1):
            if self.task:
                if self.task.is_stopped():
                    print(f"{self.channel_id}: batch downscale stopped")
                    break

                self._notify(idx, total)

            self._queue_one(video)

        if self.queued:
            dispatch_pending_downscales()

    def _queue_one(self, video: dict) -> None:
        doc_id, reason = DownscaleInteract.enqueue(video, self.target_height)
        if doc_id:
            self.queued.append(video["youtube_id"])
        elif reason == ALREADY_ACTIVE:
            self.skipped.append(video["youtube_id"])

    def _get_videos(self) -> list[dict]:
        data = {
            "query": {
                "term": {"channel.channel_id": {"value": self.channel_id}}
            },
            "_source": QUEUE_DOC_SOURCE_FIELDS,
        }
        return IndexPaginate("ta_video", data).get_results()

    def _notify(self, idx: int, total: int) -> None:
        self.task.send_progress(
            message_lines=[f"Queueing downscale jobs {idx}/{total}"],
            progress=idx / total,
        )
