import APIClient from '../../functions/APIClient';
import { ImportFileType } from '../loader/loadImportFiles';

export type ImportMetadataType = {
  video_id: string;
  channel_id: string;
  channel_name: string;
  title: string;
  upload_date: string;
  description?: string;
  thumbnail?: string;
  view_count?: number;
  like_count?: number;
};

const createImportMetadata = async (metadata: ImportMetadataType) => {
  return APIClient<ImportFileType>('/api/appsettings/import-file/metadata/', {
    method: 'POST',
    body: metadata,
  });
};

export default createImportMetadata;
