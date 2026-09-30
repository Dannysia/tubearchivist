import APIClient from '../../functions/APIClient';

export type ResolutionBucketType = {
  // a ladder rung as a string, or 'below' or 'unknown'
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
