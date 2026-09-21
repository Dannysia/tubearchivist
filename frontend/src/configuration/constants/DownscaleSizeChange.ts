import { DownscaleSavedAggsType } from '../../api/loader/loadDownscaleAggs';

/**
 * The rungs the downscale queue's size filter offers, mirroring
 * SIZE_CHANGE_VALUES in backend/downscale/src/constants.py. The labels
 * live here only - the backend has no use for them. It validates the
 * values against its own copy, so a rung added here and not there is
 * rejected as an invalid choice rather than silently ignored.
 *
 * 'smaller' and 'larger' predate the rungs and keep their old meaning,
 * so an existing ?size_change=smaller link still resolves.
 */
export type DownscaleSizeChange =
  | 'larger'
  | 'smaller'
  | 'smaller_lt_5'
  | 'smaller_lt_10'
  | 'smaller_gt_5'
  | 'smaller_gt_10'
  | 'smaller_gt_20'
  | 'smaller_gt_30'
  | 'smaller_gt_50';

export const DOWNSCALE_SIZE_CHANGES: { value: DownscaleSizeChange; label: string }[] = [
  { value: 'larger', label: 'got larger' },
  { value: 'smaller', label: 'got smaller' },
  { value: 'smaller_lt_5', label: 'got smaller (<5%)' },
  { value: 'smaller_lt_10', label: 'got smaller (<10%)' },
  { value: 'smaller_gt_5', label: 'got smaller (>5%)' },
  { value: 'smaller_gt_10', label: 'got smaller (>10%)' },
  { value: 'smaller_gt_20', label: 'got smaller (>20%)' },
  { value: 'smaller_gt_30', label: 'got smaller (>30%)' },
  { value: 'smaller_gt_50', label: 'got smaller (>50%)' },
];

export const sizeChangeLabel = (value: string): string =>
  DOWNSCALE_SIZE_CHANGES.find(option => option.value === value)?.label ?? value;

/**
 * How many jobs each rung would match, summed out of the disjoint
 * savings bands the aggs endpoint returns.
 *
 * The bands have to be summed rather than read one-per-rung because the
 * rungs overlap: >5% contains >10%, and 'got smaller' contains all of
 * them. ES cannot express that in a single range agg, so the split
 * lives here.
 *
 * Bands are keyed by their lower edge as a string, plus 'larger' for
 * jobs that grew. A band the backend adds but this does not know about
 * still lands in the 'got smaller' total, so a new edge under-reports a
 * rung rather than vanishing from the page.
 */
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
    smaller_lt_5: atLeast(0) - atLeast(5),
    smaller_lt_10: atLeast(0) - atLeast(10),
    smaller_gt_5: atLeast(5),
    smaller_gt_10: atLeast(10),
    smaller_gt_20: atLeast(20),
    smaller_gt_30: atLeast(30),
    smaller_gt_50: atLeast(50),
  };
};
