import APIClient from '../../functions/APIClient';

// aggregated from the video index rather than listed from DownscaleEncoders.ts:
// a remote worker reports its own encoder string
type VideoDownscaleEncoderBucket = {
  key: string;
  doc_count: number;
};

export type VideoDownscaleEncodersType = {
  buckets: VideoDownscaleEncoderBucket[];
};

const loadVideoDownscaleEncoders = async () => {
  return APIClient<VideoDownscaleEncodersType>('/api/video/downscale-encoders/');
};

export default loadVideoDownscaleEncoders;
