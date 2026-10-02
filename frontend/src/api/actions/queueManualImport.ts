import APIClient from '../../functions/APIClient';

export type ManualImportResponseType = {
  task_id: string;
};

const queueManualImport = async (ignore_error: boolean, prefer_local: boolean) => {
  return APIClient<ManualImportResponseType>('/api/appsettings/manual-import/', {
    method: 'POST',
    body: { ignore_error, prefer_local },
  });
};
export default queueManualImport;
