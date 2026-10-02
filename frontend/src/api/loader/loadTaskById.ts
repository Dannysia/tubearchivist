import APIClient from '../../functions/APIClient';

export type TaskStatusType = 'PENDING' | 'STARTED' | 'SUCCESS' | 'FAILURE' | 'RETRY' | 'REVOKED';

export type TaskResultType = {
  status: TaskStatusType;
};

export const FINISHED_TASK_STATUSES: TaskStatusType[] = ['SUCCESS', 'FAILURE', 'REVOKED'];

const loadTaskById = async (taskId: string) => {
  return APIClient<TaskResultType>(`/api/task/by-id/${taskId}/`);
};

export default loadTaskById;
