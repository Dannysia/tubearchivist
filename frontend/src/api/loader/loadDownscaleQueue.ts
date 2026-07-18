import APIClient from '../../functions/APIClient';
import { DownscaleResponseType } from '../../pages/Downscale';

export type DownscaleStatus = 'running' | 'pending_review' | 'failed' | 'cancelled';

const loadDownscaleQueue = async (page: number, status: DownscaleStatus | null) => {
  const searchParams = new URLSearchParams();

  if (page) searchParams.append('page', page.toString());
  if (status) searchParams.append('status', status);

  const endpoint = `/api/downscale/${searchParams.toString() ? `?${searchParams.toString()}` : ''}`;

  return APIClient<DownscaleResponseType>(endpoint);
};

export default loadDownscaleQueue;
