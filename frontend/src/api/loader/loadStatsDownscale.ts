import APIClient from '../../functions/APIClient';

export type DownscaleSavingsType = {
  doc_count: number;
  original_size: number;
  new_size: number;
  saved: number;
  saved_percent: number;
};

export type DownscaleTransitionType = {
  original_height: number;
  new_height: number;
  doc_count: number;
};

export type DownscaleTransitionsType = {
  transitions: DownscaleTransitionType[];
  // downscaled videos outside the top N pairs
  other_count: number;
};

export type DownscaleStatsType = DownscaleSavingsType & {
  by_encoder: (DownscaleSavingsType & { encoder: string })[];
  by_transition: DownscaleTransitionsType;
};

const loadStatsDownscale = async () => {
  return APIClient<DownscaleStatsType>('/api/stats/downscale/');
};

export default loadStatsDownscale;
