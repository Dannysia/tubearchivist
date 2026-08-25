import { Fragment } from 'react';
import StatsInfoBoxItem from './StatsInfoBoxItem';
import humanFileSize from '../functions/humanFileSize';
import formatNumbers from '../functions/formatNumbers';
import formatDate from '../functions/formatDates';
import { ChannelAggBucketType, ChannelAggsType } from '../api/loader/loadChannelAggs';

const VIDEO_TYPE_TITLES: [keyof ChannelAggsType['by_type'], string][] = [
  ['videos', 'Regular Videos'],
  ['shorts', 'Shorts'],
  ['streams', 'Streams'],
  ['unknown', 'Unknown Type'],
];

const formatOptionalDate = (date: string | null) => {
  if (!date) return 'NA';

  return formatDate(date);
};

const buildBucketCard = (bucket: ChannelAggBucketType, useSIUnits: boolean) => {
  return {
    Videos: formatNumbers(bucket.doc_count),
    ['Media Size']: humanFileSize(bucket.media_size, useSIUnits),
    Duration: bucket.duration_str,
  };
};

type ChannelStatsProps = {
  channelAggs?: ChannelAggsType;
  useSIUnits: boolean;
};

const ChannelStats = ({ channelAggs, useSIUnits }: ChannelStatsProps) => {
  if (!channelAggs) {
    return <p id="loading">Loading...</p>;
  }

  const { by_type, watch_progress, availability, date_range } = channelAggs;
  const watchedPercent = (watch_progress.progress * 100).toFixed(1);

  const cards = [
    {
      title: 'Totals',
      data: {
        Videos: formatNumbers(channelAggs.total_items.value),
        ['Media Size']: humanFileSize(channelAggs.total_size.value, useSIUnits),
        Duration: channelAggs.total_duration.value_str,
      },
    },
    // channels rarely carry every video type, so only show what's populated
    ...VIDEO_TYPE_TITLES.filter(([key]) => by_type[key].doc_count > 0).map(([key, title]) => ({
      title,
      data: buildBucketCard(by_type[key], useSIUnits),
    })),
    {
      title: `Watch Progress: ${watchedPercent}%`,
      data: {
        Watched: formatNumbers(watch_progress.watched.doc_count),
        Unwatched: formatNumbers(watch_progress.unwatched.doc_count),
        ['Watched Duration']: watch_progress.watched.duration_str,
      },
    },
    {
      title: 'Availability',
      data: {
        Active: formatNumbers(availability.active),
        Deactivated: formatNumbers(availability.inactive),
      },
    },
    {
      title: 'Date Range',
      data: {
        ['Oldest Video']: formatOptionalDate(date_range.published_first),
        ['Newest Video']: formatOptionalDate(date_range.published_last),
        ['First Archived']: formatOptionalDate(date_range.downloaded_first),
        ['Last Archived']: formatOptionalDate(date_range.downloaded_last),
      },
    },
  ];

  return cards.map(card => {
    return (
      <Fragment key={card.title}>
        <StatsInfoBoxItem title={card.title} card={card.data} />
      </Fragment>
    );
  });
};

export default ChannelStats;
