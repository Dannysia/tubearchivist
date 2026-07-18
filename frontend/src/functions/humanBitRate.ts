/**
 * Format bits per second as human-readable text.
 *
 * Always uses decimal (SI) prefixes, powers of 1000, since bit rates are
 * conventionally quoted that way (e.g. network/video bitrates), unlike
 * file sizes where binary (MiB) units are common.
 *
 * @param bitsPerSecond Bit rate in bits per second.
 * @param dp Number of decimal places to display.
 *
 * @return Formatted string, e.g. "1.5 Mbps".
 */
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
