import APIClient from '../../functions/APIClient';

export type ArchiveMetadataType = {
  video_id: string;
  title: string;
  channel_id: string;
  channel_name: string;
  upload_date: string;
  description: string;
  thumbnail: string;
  view_count: number | null;
  like_count: number | null;
};

const loadArchiveMetadata = async (videoId: string) => {
  return APIClient<ArchiveMetadataType>(`/api/appsettings/import-file/metadata/lookup/${videoId}/`);
};

export default loadArchiveMetadata;
