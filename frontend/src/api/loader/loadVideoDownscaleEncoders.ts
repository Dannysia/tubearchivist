import APIClient from '../../functions/APIClient';

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
