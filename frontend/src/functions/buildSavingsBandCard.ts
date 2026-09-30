import { DownscaleSavedBandsType } from '../api/loader/loadStatsDownscale';
import formatNumbers from './formatNumbers';

const buildSavingsBandCard = (bySaved: DownscaleSavedBandsType): Record<string, string> => {
  const card: Record<string, string> = {};

  bySaved.bands.forEach(band => {
    // to === null is the open-ended top band
    const label = band.to === null ? `>${band.from}%` : `${band.from}-${band.to}%`;
    card[label] = formatNumbers(band.doc_count);
  });

  if (bySaved.grew > 0) {
    card['Got Larger'] = formatNumbers(bySaved.grew);
  }

  if (bySaved.unknown > 0) {
    card['Unknown'] = formatNumbers(bySaved.unknown);
  }

  return card;
};

export default buildSavingsBandCard;
