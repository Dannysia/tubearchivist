import APIClient from '../../functions/APIClient';

export type DownscaleEncoderTestResultType = {
  encoder: string;
  ok: boolean;
  message: string | null;
};

const testDownscaleEncoders = async () => {
  return APIClient<DownscaleEncoderTestResultType[]>('/api/downscale/test-encoders/', {
    method: 'POST',
  });
};

export default testDownscaleEncoders;
