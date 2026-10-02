export type YouTubeEra = 'original' | 'classic' | 'refresh' | 'watch7' | 'material' | 'modern';

const ERA_STARTS: [number, YouTubeEra][] = [
  [2022, 'modern'],
  [2017, 'material'],
  [2013, 'watch7'],
  [2010, 'refresh'],
  [2007, 'classic'],
];

export const publishedYear = (published: string) => new Date(published).getUTCFullYear();

const youtubeEra = (published: string): YouTubeEra => {
  const year = publishedYear(published);
  const match = ERA_STARTS.find(([start]) => year >= start);

  return match ? match[1] : 'original';
};

export default youtubeEra;
