import APIClient from '../../functions/APIClient';

export type ChannelAggBucketType = {
  doc_count: number;
  media_size: number;
  duration: number;
  duration_str: string;
};

export type ChannelAggsType = {
  total_items: {
    value: number;
  };
  total_size: {
    value: number;
  };
  total_duration: {
    value: number;
    value_str: string;
  };
  by_type: {
    videos: ChannelAggBucketType;
    shorts: ChannelAggBucketType;
    streams: ChannelAggBucketType;
    unknown: ChannelAggBucketType;
  };
  watch_progress: {
    watched: ChannelAggBucketType;
    unwatched: ChannelAggBucketType;
    progress: number;
  };
  availability: {
    active: number;
    inactive: number;
  };
  downscale: {
    doc_count: number;
    original_size: number;
    new_size: number;
    saved: number;
  };
  date_range: {
    published_first: string | null;
    published_last: string | null;
    downloaded_first: string | null;
    downloaded_last: string | null;
  };
};

const loadChannelAggs = async (channelId: string) => {
  return APIClient<ChannelAggsType>(`/api/channel/${channelId}/aggs/`);
};

export default loadChannelAggs;
