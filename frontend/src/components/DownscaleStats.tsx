import { Fragment } from 'react';
import StatsInfoBoxItem from './StatsInfoBoxItem';
import humanFileSize from '../functions/humanFileSize';
import formatNumbers from '../functions/formatNumbers';
import { DownscaleSavingsType, DownscaleStatsType } from '../api/loader/loadStatsDownscale';
import { ALL_ENCODER_LABELS } from '../configuration/constants/DownscaleEncoders';

// the backend folds every encoder past its display limit into this one
// entry, so it never reads as a real encoder string
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
    // a remote worker reports its own encoder string, so fall back to
    // the raw key for anything ALL_ENCODER_LABELS does not know
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
