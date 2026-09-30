import APIClient from '../../functions/APIClient';
import { DownscaleStatus } from './loadDownscaleQueue';
import { DownscaleSizeChange } from '../../configuration/constants/DownscaleSizeChange';

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

type DownscaleEncoderAggsBucket = {
  key: string;
  doc_count: number;
};

export type DownscaleEncoderAggsType = {
  doc_count_error_upper_bound: number;
  sum_other_doc_count: number;
  buckets: DownscaleEncoderAggsBucket[];
};

export type DownscaleSavedAggsBucket = {
  key: string;
  doc_count: number;
};

export type DownscaleSavedAggsType = {
  buckets: DownscaleSavedAggsBucket[];
};

export type DownscaleAggsFilters = {
  status: DownscaleStatus | null;
  channel: string | null;
  search: string;
  sizeChange: DownscaleSizeChange | null;
  encoder: string | null;
};

const aggsEndpoint = (field: string, filters: DownscaleAggsFilters) => {
  const searchParams = new URLSearchParams();
  searchParams.append('field', field);
  if (filters.status) searchParams.append('status', filters.status);
  if (filters.channel) searchParams.append('channel', filters.channel);
  if (filters.search) searchParams.append('q', filters.search);
  if (filters.sizeChange) searchParams.append('size_change', filters.sizeChange);
  if (filters.encoder) searchParams.append('encoder', filters.encoder);

  return `/api/downscale/aggs/?${searchParams.toString()}`;
};

const loadDownscaleAggs = async (filters: DownscaleAggsFilters) => {
  return APIClient<DownscaleAggsType>(aggsEndpoint('channel', filters));
};

export const loadDownscaleEncoderAggs = async (filters: DownscaleAggsFilters) => {
  return APIClient<DownscaleEncoderAggsType>(aggsEndpoint('encoder', filters));
};

export const loadDownscaleSavedAggs = async (filters: DownscaleAggsFilters) => {
  return APIClient<DownscaleSavedAggsType>(aggsEndpoint('saved', filters));
};

export default loadDownscaleAggs;
