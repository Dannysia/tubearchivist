import formatNumbers from './formatNumbers';

// A video that is gone from YouTube and was never captured with its view
// or like count has an unknown one, not a zero one. appsettings.src
// .manual.UNKNOWN_COUNT writes this into a generated info.json for a
// count the form left blank, and it is indexed as is.
//
// It is in band, so it only reads correctly where it is checked for:
// formatNumbers would happily render it as "-1", and it is truthy, so a
// plain truthiness test treats it as a count worth showing.
const UNKNOWN_COUNT = -1;

export const isKnownCount = (count: number): boolean => count !== UNKNOWN_COUNT;

// the word, not a hidden row: the archive has the video, it just never
// learned the count, and a hidden row would not say so
const formatCount = (count: number): string =>
  isKnownCount(count) ? formatNumbers(count) : 'unknown';

export default formatCount;
