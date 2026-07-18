import APIClient from '../../functions/APIClient';

const startDownscale = async (videoId: string, targetHeight: number) => {
  return APIClient(`/api/video/${videoId}/downscale/`, {
    method: 'POST',
    body: { target_height: targetHeight },
  });
};

export default startDownscale;
