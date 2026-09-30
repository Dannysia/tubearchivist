import { DownscaleTransitionsType } from '../api/loader/loadStatsDownscale';
import formatNumbers from './formatNumbers';

const buildTransitionCard = (byTransition: DownscaleTransitionsType): Record<string, string> => {
  const card: Record<string, string> = {};

  byTransition.transitions.forEach(transition => {
    const label = `${transition.original_height}p → ${transition.new_height}p`;
    card[label] = formatNumbers(transition.doc_count);
  });

  if (byTransition.other_count > 0) {
    card['Other'] = formatNumbers(byTransition.other_count);
  }

  return card;
};

export default buildTransitionCard;
