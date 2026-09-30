from common.src.es_connect import IndexPaginate
from downscale.src.constants import QUEUE_DOC_SOURCE_FIELDS
from downscale.src.downscale import dispatch_pending_downscales
from downscale.src.queue_interact import DownscaleInteract


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
        youtube_id = video["youtube_id"]
        streams = video.get("streams") or []
        heights = [s["height"] for s in streams if s["type"] == "video"]
        current_height = max(heights) if heights else None

        if not current_height or self.target_height >= current_height:
            return

        if DownscaleInteract.get_active_for_video(youtube_id):
            self.skipped.append(youtube_id)
            return

        DownscaleInteract().create(
            DownscaleInteract.build_queued_doc(
                youtube_id=youtube_id,
                video_json_data=video,
                current_height=current_height,
                target_height=self.target_height,
            )
        )
        self.queued.append(youtube_id)

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
