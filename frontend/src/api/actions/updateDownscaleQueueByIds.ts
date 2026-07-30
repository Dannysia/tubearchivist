import APIClient from '../../functions/APIClient';

export type DownscaleBulkAction = 'accept' | 'reject' | 'retry' | 'cancel';

export type DownscaleBulkResultType = {
  success: string[];
  failed: { id: string; error: string }[];
};

const updateDownscaleQueueByIds = async (ids: string[], action: DownscaleBulkAction) => {
  return APIClient<DownscaleBulkResultType>('/api/downscale/', {
    method: 'POST',
    body: { ids, action },
  });
};

export default updateDownscaleQueueByIds;
