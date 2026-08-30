import formatNumbers from './formatNumbers';
import humanFileSize from './humanFileSize';
import { ResolutionBucketType, ResolutionStatsType } from '../api/loader/loadStatsResolution';

// the two tiers that are not a rung of the downscale ladder
const BELOW_KEY = 'below';
const UNKNOWN_KEY = 'unknown';

// the tallest rung is the only one anybody calls by a name rather than
// by its height
const TIER_NAMES: Record<string, string> = {
  '2160': '4K',
};

// what each panel reads off a tier, and what its one line says when the
// scope has nothing indexed yet
const PANELS: {
  title: string;
  emptyLabel: string;
  value: (bucket: ResolutionBucketType, useSIUnits: boolean) => string;
}[] = [
  {
    title: 'Count',
    emptyLabel: 'Videos',
    value: bucket => formatNumbers(bucket.doc_count),
  },
  {
    title: 'Duration',
    emptyLabel: 'Duration',
    value: bucket => bucket.duration_str,
  },
  {
    title: 'Media Size',
    emptyLabel: 'Media Size',
    value: (bucket, useSIUnits) => humanFileSize(bucket.media_size, useSIUnits),
  },
];

// nothing indexed anywhere in this scope, including the case where the
// endpoint had no aggregations to parse and returned no tiers at all
const ZERO_TIER: ResolutionBucketType = {
  key: '',
  doc_count: 0,
  media_size: 0,
  duration: 0,
  duration_str: '0s',
};

const tierLabel = (bucket: ResolutionBucketType, smallestTier?: string) => {
  if (bucket.key === UNKNOWN_KEY) return 'Unknown';
  if (bucket.key === BELOW_KEY) return `Below ${smallestTier}p`;

  return TIER_NAMES[bucket.key] ?? `${bucket.key}p`;
};

/**
 * three panels over the same tiers - videos, time and size - so the
 * rows line up across all three. Tallest first, skipping the tiers this
 * scope has nothing in. Shared so the channel about panel and the
 * dashboard break their videos down the same way. Every video is on
 * exactly one line: a 1200p video counts as 1080p, the tier it clears
 */
const buildResolutionPanels = (buckets: ResolutionStatsType, useSIUnits: boolean) => {
  const smallestTier = buckets.filter(bucket => !isNaN(Number(bucket.key))).at(-1)?.key;
  const populated = buckets.filter(bucket => bucket.doc_count > 0);

  return PANELS.map(panel => ({
    title: panel.title,
    // a channel with nothing indexed yet still gets a readable panel
    // rather than a title over an empty table
    data: populated.length
      ? Object.fromEntries(
          populated.map(bucket => [
            tierLabel(bucket, smallestTier),
            panel.value(bucket, useSIUnits),
          ]),
        )
      : { [panel.emptyLabel]: panel.value(ZERO_TIER, useSIUnits) },
  }));
};

export default buildResolutionPanels;
