import formatNumbers from './formatNumbers';

// -1 is the sentinel for a count that was never captured, not a zero count:
// appsettings.src.manual.UNKNOWN_COUNT writes it into a generated info.json
// and it is indexed as is. Being in band, formatNumbers would render it as
// "-1" and a truthiness test would treat it as a real count.
const UNKNOWN_COUNT = -1;

export const isKnownCount = (count: number): boolean => count !== UNKNOWN_COUNT;

const formatCount = (count: number): string =>
  isKnownCount(count) ? formatNumbers(count) : 'unknown';

export default formatCount;
