import formatNumbers from './formatNumbers';

const humanFileSizeMB = (bytes: number, si = false) => {
  const thresh = si ? 1000 : 1024;
  const units = si ? ['B', 'kB', 'MB'] : ['B', 'KiB', 'MiB'];
  let u = 0;

  while (Math.abs(bytes) >= thresh && u < units.length - 1) {
    bytes /= thresh;
    ++u;
  }

  const dp = u > 0 && Math.abs(bytes) < 999.95 ? 1 : 0;
  const value = formatNumbers(bytes, { minimumFractionDigits: dp, maximumFractionDigits: dp });

  return value + ' ' + units[u];
};

export default humanFileSizeMB;
