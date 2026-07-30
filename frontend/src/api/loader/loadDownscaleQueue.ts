import APIClient from '../../functions/APIClient';
import { DownscaleResponseType } from '../../pages/Downscale';

export type DownscaleStatus = 'queued' | 'running' | 'pending_review' | 'failed' | 'cancelled';
export type DownscaleSizeChange = 'smaller' | 'larger';

const loadDownscaleQueue = async (
  page: number,
  status: DownscaleStatus | null,
  channelId: string | null,
  search: string,
  sizeChange: DownscaleSizeChange | null,
) => {
  const searchParams = new URLSearchParams();

  if (page) searchParams.append('page', page.toString());
  if (status) searchParams.append('status', status);
  if (channelId) searchParams.append('channel', channelId);
  if (search) searchParams.append('q', search);
  if (sizeChange) searchParams.append('size_change', sizeChange);

  const endpoint = `/api/downscale/${searchParams.toString() ? `?${searchParams.toString()}` : ''}`;

  return APIClient<DownscaleResponseType>(endpoint);
};

export default loadDownscaleQueue;
