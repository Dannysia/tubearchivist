import APIClient from '../../functions/APIClient';
import { ExtractionItemType, ExtractionStatus } from '../loader/loadExtractionQueue';

const deleteExtractionQueueByFilter = async (
  filter: ExtractionStatus,
  itemType: ExtractionItemType | null,
) => {
  const searchParams = new URLSearchParams();
  searchParams.append('filter', filter);
  if (itemType) searchParams.append('item_type', itemType);

  return APIClient(`/api/download/extraction/?${searchParams.toString()}`, {
    method: 'DELETE',
  });
};

export default deleteExtractionQueueByFilter;
