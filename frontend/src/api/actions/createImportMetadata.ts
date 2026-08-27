import APIClient from '../../functions/APIClient';
import { ImportFileType } from '../loader/loadImportFiles';

// the fields the import path actually reads, see
// ImportFolderFiles.build_info_json - not the whole yt-dlp schema
export type ImportMetadataType = {
  video_id: string;
  channel_id: string;
  channel_name: string;
  title: string;
  // yyyy-mm-dd, the backend spells it yt-dlp's way when it writes
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
