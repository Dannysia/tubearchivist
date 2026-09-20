import { DownscaleTransitionsType } from '../api/loader/loadStatsDownscale';
import formatNumbers from './formatNumbers';

// The global stats page and the channel about panel both show this, so
// the row labels and the remainder wording are built once rather than
// written out in each - the two panels report on the same set and
// should read the same way.
const buildTransitionCard = (byTransition: DownscaleTransitionsType): Record<string, string> => {
  const card: Record<string, string> = {};

  byTransition.transitions.forEach(transition => {
    const label = `${transition.original_height}p → ${transition.new_height}p`;
    card[label] = formatNumbers(transition.doc_count);
  });

  // the backend caps the pairs it returns, so say what is not shown
  // instead of letting the rows quietly undercount the total
  if (byTransition.other_count > 0) {
    card['Other'] = formatNumbers(byTransition.other_count);
  }

  return card;
};

export default buildTransitionCard;
