import { DownscaleSavedBandsType } from '../api/loader/loadStatsDownscale';
import formatNumbers from './formatNumbers';

// How many videos landed in each savings band, biggest saving first.
// The backend orders the bands; this only labels them, so the panel and
// the queue's size filter stay in the same categories.
const buildSavingsBandCard = (bySaved: DownscaleSavedBandsType): Record<string, string> => {
  const card: Record<string, string> = {};

  bySaved.bands.forEach(band => {
    // the top band is open ended - it has no ceiling to name. Reads
    // ">50%" to match the wording of the queue's size filter rung that
    // selects the same set
    const label = band.to === null ? `>${band.from}%` : `${band.from}-${band.to}%`;
    card[label] = formatNumbers(band.doc_count);
  });

  // Both of these should be zero on a healthy archive, so they earn a
  // row only when they are not: an accepted downscale that came out
  // bigger is a decision worth seeing, and an unplaceable one means the
  // sizes behind the panel are incomplete. Shown when non-zero, the
  // rows also keep the panel adding up to the downscaled total - the
  // same contract the transition panel's Other row holds to.
  if (bySaved.grew > 0) {
    card['Got Larger'] = formatNumbers(bySaved.grew);
  }

  if (bySaved.unknown > 0) {
    card['Unknown'] = formatNumbers(bySaved.unknown);
  }

  return card;
};

export default buildSavingsBandCard;
