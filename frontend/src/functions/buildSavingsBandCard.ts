import { DownscaleSavedBandsType } from '../api/loader/loadStatsDownscale';
import formatNumbers from './formatNumbers';

// the backend orders the bands, biggest saving first; this only labels them
const buildSavingsBandCard = (bySaved: DownscaleSavedBandsType): Record<string, string> => {
  const card: Record<string, string> = {};

  bySaved.bands.forEach(band => {
    // to === null is the open-ended top band; ">50%" matches the queue's filter
    const label = band.to === null ? `>${band.from}%` : `${band.from}-${band.to}%`;
    card[label] = formatNumbers(band.doc_count);
  });

  // zero on a healthy archive, but when non-zero these rows are what keeps
  // the panel adding up to the downscaled total
  if (bySaved.grew > 0) {
    card['Got Larger'] = formatNumbers(bySaved.grew);
  }

  if (bySaved.unknown > 0) {
    card['Unknown'] = formatNumbers(bySaved.unknown);
  }

  return card;
};

export default buildSavingsBandCard;
