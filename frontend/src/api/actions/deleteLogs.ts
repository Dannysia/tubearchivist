import APIClient from '../../functions/APIClient';
import { LogSource } from '../loader/loadLogs';

export type DeleteLogsResponseType = {
  deleted: number;
};

const deleteLogs = async (source: LogSource) => {
  const searchParams = new URLSearchParams();
  searchParams.append('source', source);

  return APIClient<DeleteLogsResponseType>(`/api/log/?${searchParams.toString()}`, {
    method: 'DELETE',
  });
};

export default deleteLogs;
