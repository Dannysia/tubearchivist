import APIClient from '../../functions/APIClient';

// what the Wayback Machine had for the video. Same field names
// ImportMetadataType posts back, so a lookup drops straight into the
// form - but only the title is guaranteed, an archived watch page is
// often missing the rest
export type ArchiveMetadataType = {
  video_id: string;
  title: string;
  channel_id: string;
  channel_name: string;
  // iso, or empty when no capture carried a publish date
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
