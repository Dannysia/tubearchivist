import { VideoResponseType } from '../api/loader/loadVideoById';
import { YouTubeEra } from './youtubeEra';

export const count = (value: number | undefined) => (value ?? 0).toLocaleString('en-US');

const SHORT_UNITS = ['', 'K', 'M', 'B'];

export const shortCount = (value: number | undefined) => {
  let scaled = value ?? 0;
  let unit = 0;
  while (unit < SHORT_UNITS.length - 1 && Number(scaled.toFixed(scaled >= 10 ? 0 : 1)) >= 1000) {
    scaled /= 1000;
    unit += 1;
  }

  const digits = unit === 0 || scaled >= 10 ? 0 : 1;
  return `${Number(scaled.toFixed(digits))}${SHORT_UNITS[unit]}`;
};

export const eraDate = (era: YouTubeEra, published: string) => {
  const longMonth = era === 'original' || era === 'classic';

  return new Date(published).toLocaleDateString('en-US', {
    month: longMonth ? 'long' : 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC',
  });
};

const AGE_UNITS: [string, number][] = [
  ['year', 365 * 24 * 3600],
  ['month', (365 / 12) * 24 * 3600],
  ['week', 7 * 24 * 3600],
  ['day', 24 * 3600],
  ['hour', 3600],
  ['minute', 60],
];

export const relativeAge = (published: string) => {
  const seconds = (Date.now() - new Date(published).getTime()) / 1000;
  const unit = AGE_UNITS.find(([, size]) => seconds >= size);
  if (!unit) {
    return 'just now';
  }

  const amount = Math.floor(seconds / unit[1]);
  return `${amount} ${unit[0]}${amount === 1 ? '' : 's'} ago`;
};

export const starRating = (stats: VideoResponseType['stats']) => {
  if (stats.average_rating) {
    return stats.average_rating;
  }

  const total = stats.like_count + stats.dislike_count;
  return total ? 1 + (4 * stats.like_count) / total : undefined;
};
