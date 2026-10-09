import { DownscaleSavedAggsType } from '../../api/loader/loadDownscaleAggs';

/** mirrors SIZE_CHANGE_VALUES in backend/downscale/src/constants.py */
export type DownscaleSizeChange =
  | 'larger'
  | 'smaller'
  | 'smaller_lt_2'
  | 'smaller_lt_5'
  | 'smaller_lt_10'
  | 'smaller_gt_2'
  | 'smaller_gt_5'
  | 'smaller_gt_10'
  | 'smaller_gt_20'
  | 'smaller_gt_30'
  | 'smaller_gt_50';

export const DOWNSCALE_SIZE_CHANGES: { value: DownscaleSizeChange; label: string }[] = [
  { value: 'larger', label: 'got larger' },
  { value: 'smaller', label: 'got smaller' },
  { value: 'smaller_lt_2', label: 'got smaller (<2%)' },
  { value: 'smaller_lt_5', label: 'got smaller (<5%)' },
  { value: 'smaller_lt_10', label: 'got smaller (<10%)' },
  { value: 'smaller_gt_2', label: 'got smaller (>2%)' },
  { value: 'smaller_gt_5', label: 'got smaller (>5%)' },
  { value: 'smaller_gt_10', label: 'got smaller (>10%)' },
  { value: 'smaller_gt_20', label: 'got smaller (>20%)' },
  { value: 'smaller_gt_30', label: 'got smaller (>30%)' },
  { value: 'smaller_gt_50', label: 'got smaller (>50%)' },
];

export const sizeChangeLabel = (value: string): string =>
  DOWNSCALE_SIZE_CHANGES.find(option => option.value === value)?.label ?? value;

export const countsBySizeChange = (
  aggs: DownscaleSavedAggsType | undefined,
): Partial<Record<DownscaleSizeChange, number>> => {
  if (!aggs?.buckets?.length) {
    return {};
  }

  const larger = aggs.buckets.find(bucket => bucket.key === 'larger')?.doc_count ?? 0;
  const atLeast = (threshold: number) =>
    aggs.buckets
      .filter(bucket => bucket.key !== 'larger' && Number(bucket.key) >= threshold)
      .reduce((total, bucket) => total + bucket.doc_count, 0);

  return {
    larger,
    smaller: atLeast(0),
    smaller_lt_2: atLeast(0) - atLeast(2),
    smaller_lt_5: atLeast(0) - atLeast(5),
    smaller_lt_10: atLeast(0) - atLeast(10),
    smaller_gt_2: atLeast(2),
    smaller_gt_5: atLeast(5),
    smaller_gt_10: atLeast(10),
    smaller_gt_20: atLeast(20),
    smaller_gt_30: atLeast(30),
    smaller_gt_50: atLeast(50),
  };
};
