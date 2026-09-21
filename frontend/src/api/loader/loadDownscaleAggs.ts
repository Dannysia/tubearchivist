import APIClient from '../../functions/APIClient';
import { DownscaleStatus } from './loadDownscaleQueue';

type DownscaleAggsBucket = {
  key: string[];
  key_as_string: string;
  doc_count: number;
};

export type DownscaleAggsType = {
  doc_count_error_upper_bound: number;
  sum_other_doc_count: number;
  buckets: DownscaleAggsBucket[];
};

// encoder is a plain single-field terms agg (no channel-style id/name
// pair), so its bucket key is just the encoder string itself
type DownscaleEncoderAggsBucket = {
  key: string;
  doc_count: number;
};

export type DownscaleEncoderAggsType = {
  doc_count_error_upper_bound: number;
  sum_other_doc_count: number;
  buckets: DownscaleEncoderAggsBucket[];
};

// one disjoint savings band per bucket, keyed by its lower edge as a
// string, plus 'larger' for jobs whose encode came out bigger. The
// dropdown's rungs overlap, so countsBySizeChange sums these rather
// than reading one bucket per rung
export type DownscaleSavedAggsBucket = {
  key: string;
  doc_count: number;
};

export type DownscaleSavedAggsType = {
  buckets: DownscaleSavedAggsBucket[];
};

const loadDownscaleAggs = async (status: DownscaleStatus | null) => {
  const searchParams = new URLSearchParams();
  if (status) searchParams.append('status', status);

  return APIClient<DownscaleAggsType>(
    `/api/downscale/aggs/${searchParams.toString() ? `?${searchParams.toString()}` : ''}`,
  );
};

export const loadDownscaleEncoderAggs = async (status: DownscaleStatus | null) => {
  const searchParams = new URLSearchParams();
  searchParams.append('field', 'encoder');
  if (status) searchParams.append('status', status);

  return APIClient<DownscaleEncoderAggsType>(`/api/downscale/aggs/?${searchParams.toString()}`);
};

export const loadDownscaleSavedAggs = async (status: DownscaleStatus | null) => {
  const searchParams = new URLSearchParams();
  searchParams.append('field', 'saved');
  if (status) searchParams.append('status', status);

  return APIClient<DownscaleSavedAggsType>(`/api/downscale/aggs/?${searchParams.toString()}`);
};

export default loadDownscaleAggs;
