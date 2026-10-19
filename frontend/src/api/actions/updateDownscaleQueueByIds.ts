import APIClient from '../../functions/APIClient';

export type DownscaleBulkAction = 'accept' | 'reject' | 'retry' | 'cancel';

export type DownscaleBulkResultType = {
  success: string[];
  failed: { id: string; error: string }[];
};

export type DownscaleBulkStateType = {
  task_id: string;
  action: 'accept' | 'reject';
  total: number;
  done: number;
  failed: { id: string; error: string }[];
  status: 'queued' | 'running' | 'done' | 'failed';
  stopped: boolean;
  failure: string | null;
};

export type DownscaleBulkResponseType = DownscaleBulkResultType | DownscaleBulkStateType;

const updateDownscaleQueueByIds = async (ids: string[], action: DownscaleBulkAction) => {
  return APIClient<DownscaleBulkResponseType>('/api/downscale/', {
    method: 'POST',
    body: { ids, action },
  });
};

export default updateDownscaleQueueByIds;
