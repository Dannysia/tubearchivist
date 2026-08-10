import APIClient from '../../functions/APIClient';
import { DownscaleBulkAction, DownscaleBulkResultType } from './updateDownscaleQueueByIds';
import { DownscaleSizeChange, DownscaleStatus } from '../loader/loadDownscaleQueue';

const updateDownscaleQueueByFilter = async (
  action: DownscaleBulkAction,
  status: DownscaleStatus | null,
  channelId: string | null,
  search: string,
  sizeChange: DownscaleSizeChange | null,
  encoder: string | null,
) => {
  const searchParams = new URLSearchParams();
  if (status) searchParams.append('status', status);
  if (channelId) searchParams.append('channel', channelId);
  if (search) searchParams.append('q', search);
  if (sizeChange) searchParams.append('size_change', sizeChange);
  if (encoder) searchParams.append('encoder', encoder);

  const endpoint = `/api/downscale/${searchParams.toString() ? `?${searchParams.toString()}` : ''}`;

  return APIClient<DownscaleBulkResultType>(endpoint, {
    method: 'POST',
    body: { action },
  });
};

export default updateDownscaleQueueByFilter;
