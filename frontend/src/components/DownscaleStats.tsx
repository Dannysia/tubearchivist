import { Fragment } from 'react';
import StatsInfoBoxItem from './StatsInfoBoxItem';
import humanFileSize from '../functions/humanFileSize';
import formatNumbers from '../functions/formatNumbers';
import { DownscaleSavingsType, DownscaleStatsType } from '../api/loader/loadStatsDownscale';
import { ALL_ENCODER_LABELS } from '../configuration/constants/DownscaleEncoders';
import buildTransitionCard from '../functions/buildTransitionCard';
import buildSavingsBandCard from '../functions/buildSavingsBandCard';

// every encoder past the backend's display limit
const OTHER_ENCODER = 'other';

const buildSavingsCard = (savings: DownscaleSavingsType, useSIUnits: boolean) => {
  return {
    Videos: formatNumbers(savings.doc_count),
    ['Original Size']: humanFileSize(savings.original_size, useSIUnits),
    ['Downscaled Size']: humanFileSize(savings.new_size, useSIUnits),
    Saved: humanFileSize(savings.saved, useSIUnits),
  };
};

type DownscaleStatsProps = {
  downscaleStats?: DownscaleStatsType;
  useSIUnits: boolean;
};

const DownscaleStats = ({ downscaleStats, useSIUnits }: DownscaleStatsProps) => {
  if (!downscaleStats) {
    return <p id="loading">Loading...</p>;
  }

  const cards = [
    {
      title: `Total: ${downscaleStats.saved_percent}% Saved`,
      data: buildSavingsCard(downscaleStats, useSIUnits),
    },
    ...downscaleStats.by_encoder.map(encoderStats => {
      const label =
        encoderStats.encoder === OTHER_ENCODER
          ? 'Other Encoders'
          : (ALL_ENCODER_LABELS[encoderStats.encoder] ?? encoderStats.encoder);

      return {
        title: `${label}: ${encoderStats.saved_percent}% Saved`,
        data: buildSavingsCard(encoderStats, useSIUnits),
      };
    }),
    ...(downscaleStats.by_transition.transitions.length > 0
      ? [
          {
            title: 'Downscale Counts',
            data: buildTransitionCard(downscaleStats.by_transition),
          },
        ]
      : []),
    ...(downscaleStats.doc_count > 0
      ? [
          {
            title: 'Savings Distribution',
            data: buildSavingsBandCard(downscaleStats.by_saved),
          },
        ]
      : []),
  ];

  return cards.map(card => {
    return (
      <Fragment key={card.title}>
        <StatsInfoBoxItem title={card.title} card={card.data} />
      </Fragment>
    );
  });
};

export default DownscaleStats;
