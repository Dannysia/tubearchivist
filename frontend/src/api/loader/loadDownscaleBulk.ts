import APIClient from '../../functions/APIClient';
import { DownscaleBulkStateType } from '../actions/updateDownscaleQueueByIds';

const loadDownscaleBulk = async (taskId?: string) => {
  const endpoint = taskId ? `/api/downscale/bulk/${taskId}/` : '/api/downscale/bulk/';
  return APIClient<DownscaleBulkStateType>(endpoint);
};

export default loadDownscaleBulk;
