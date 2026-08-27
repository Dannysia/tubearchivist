import APIClient from '../../functions/APIClient';
import { PaginationType } from '../../components/Pagination';

export type LogSource = 'notification' | 'application';
export type LogLevel = 'info' | 'error';

export type LogEntryType = {
  id: string;
  timestamp: number;
  source: LogSource;
  level: LogLevel;
  message: string;
  event?: string;
  task_id?: string;
  task_name?: string;
  task_title?: string;
  group?: string;
};

export type LogTaskOptionType = {
  task_name: string;
  task_title: string;
};

export type LogResponseType = {
  data: LogEntryType[];
  paginate: PaginationType;
  tasks: LogTaskOptionType[];
};

const loadLogs = async (
  source: LogSource,
  page: number,
  level: LogLevel | null,
  taskName: string | null,
  search: string,
) => {
  const searchParams = new URLSearchParams();

  searchParams.append('source', source);
  if (page) searchParams.append('page', page.toString());
  if (level) searchParams.append('level', level);
  if (taskName) searchParams.append('task_name', taskName);
  if (search) searchParams.append('q', search);

  return APIClient<LogResponseType>(`/api/log/?${searchParams.toString()}`);
};

export default loadLogs;
