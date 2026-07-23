import APIClient from '../../functions/APIClient';
import { ExtractionResponseType } from '../../pages/Extraction';

export type ExtractionStatus = 'pending' | 'extracting' | 'failed';
export type ExtractionItemType = 'video' | 'channel' | 'playlist';

const loadExtractionQueue = async (
  page: number,
  status: ExtractionStatus | null,
  itemType: ExtractionItemType | null,
  search: string,
) => {
  const searchParams = new URLSearchParams();

  if (page) searchParams.append('page', page.toString());
  if (status) searchParams.append('filter', status);
  if (itemType) searchParams.append('item_type', itemType);
  if (search) searchParams.append('q', encodeURIComponent(search));

  const endpoint = `/api/download/extraction/${searchParams.toString() ? `?${searchParams.toString()}` : ''}`;

  return APIClient<ExtractionResponseType>(endpoint);
};

export default loadExtractionQueue;
