import formatNumbers from './formatNumbers';
import humanFileSize from './humanFileSize';
import { ResolutionBucketType, ResolutionStatsType } from '../api/loader/loadStatsResolution';

const BELOW_KEY = 'below';
const UNKNOWN_KEY = 'unknown';

// 4K is the only rung called by a name rather than by its height
const TIER_NAMES: Record<string, string> = {
  '2160': '4K',
};

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

const buildResolutionPanels = (buckets: ResolutionStatsType, useSIUnits: boolean) => {
  const smallestTier = buckets.filter(bucket => !isNaN(Number(bucket.key))).at(-1)?.key;
  const populated = buckets.filter(bucket => bucket.doc_count > 0);

  return PANELS.map(panel => ({
    title: panel.title,
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
