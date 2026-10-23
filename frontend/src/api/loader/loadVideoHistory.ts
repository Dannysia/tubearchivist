import APIClient from '../../functions/APIClient';

export type HistoryVersionType = {
  value?: string | null;
  image_url?: string | null;
  first_seen: number | null;
  replaced: number | null;
};

export type HistoryPointType = {
  timestamp: number;
  value: number;
};

export type VideoHistoryType = {
  title: HistoryVersionType[];
  description: HistoryVersionType[];
  thumbnail: HistoryVersionType[];
  views: HistoryPointType[];
  likes: HistoryPointType[];
};

const loadVideoHistory = async (youtubeVideoId: string) => {
  return APIClient<VideoHistoryType>(`/api/video/${youtubeVideoId}/history/`);
};

export default loadVideoHistory;
