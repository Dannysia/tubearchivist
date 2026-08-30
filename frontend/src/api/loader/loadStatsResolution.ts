import APIClient from '../../functions/APIClient';

export type ResolutionBucketType = {
  // a rung of the downscale ladder as a string, '1440', or one of the
  // two catch-all keys, 'below' and 'unknown'
  key: string;
  doc_count: number;
  media_size: number;
  duration: number;
  duration_str: string;
};

export type ResolutionStatsType = ResolutionBucketType[];

const loadStatsResolution = async () => {
  return APIClient<ResolutionStatsType>('/api/stats/resolution/');
};

export default loadStatsResolution;
