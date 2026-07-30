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

const loadDownscaleAggs = async (status: DownscaleStatus | null) => {
  const searchParams = new URLSearchParams();
  if (status) searchParams.append('status', status);

  return APIClient<DownscaleAggsType>(
    `/api/downscale/aggs/${searchParams.toString() ? `?${searchParams.toString()}` : ''}`,
  );
};

export default loadDownscaleAggs;
