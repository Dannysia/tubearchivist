/** decimal (SI) prefixes, powers of 1000 */
function humanBitRate(bitsPerSecond: number, dp = 1) {
  const thresh = 1000;

  if (Math.abs(bitsPerSecond) < thresh) {
    return bitsPerSecond + ' bps';
  }

  const units = ['kbps', 'Mbps', 'Gbps', 'Tbps'];
  let u = -1;
  const r = 10 ** dp;
  let value = bitsPerSecond;

  do {
    value /= thresh;
    ++u;
  } while (Math.round(Math.abs(value) * r) / r >= thresh && u < units.length - 1);

  return value.toFixed(dp) + ' ' + units[u];
}

export default humanBitRate;
