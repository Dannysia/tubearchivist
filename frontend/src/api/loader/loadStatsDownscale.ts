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

export type DownscaleSavedBandType = {
  from: number;
  // null on the open topped band, which has no ceiling to render
  to: number | null;
  doc_count: number;
};

export type DownscaleSavedBandsType = {
  bands: DownscaleSavedBandType[];
  // downscaled videos whose encode came out larger
  grew: number;
  // downscaled videos no band could place, e.g. a missing original size
  unknown: number;
};

export type DownscaleStatsType = DownscaleSavingsType & {
  by_encoder: (DownscaleSavingsType & { encoder: string })[];
  by_transition: DownscaleTransitionsType;
  by_saved: DownscaleSavedBandsType;
};

const loadStatsDownscale = async () => {
  return APIClient<DownscaleStatsType>('/api/stats/downscale/');
};

export default loadStatsDownscale;
