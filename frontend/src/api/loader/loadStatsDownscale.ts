import APIClient from '../../functions/APIClient';

export type DownscaleSavingsType = {
  doc_count: number;
  original_size: number;
  new_size: number;
  saved: number;
  saved_percent: number;
};

export type DownscaleStatsType = DownscaleSavingsType & {
  by_encoder: (DownscaleSavingsType & { encoder: string })[];
};

const loadStatsDownscale = async () => {
  return APIClient<DownscaleStatsType>('/api/stats/downscale/');
};

export default loadStatsDownscale;
