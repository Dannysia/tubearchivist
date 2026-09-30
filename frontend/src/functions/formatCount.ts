import formatNumbers from './formatNumbers';

// -1 is the sentinel for a count that was never captured
const UNKNOWN_COUNT = -1;

export const isKnownCount = (count: number): boolean => count !== UNKNOWN_COUNT;

const formatCount = (count: number): string =>
  isKnownCount(count) ? formatNumbers(count) : 'unknown';

export default formatCount;
