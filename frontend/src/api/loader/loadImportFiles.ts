import APIClient from '../../functions/APIClient';

export type ImportFileType = {
  filename: string;
  size: number;
  category: string;
  video_id: string | null;
};

const loadImportFiles = async () => {
  return APIClient<ImportFileType[]>('/api/appsettings/import-file/');
};

export default loadImportFiles;
