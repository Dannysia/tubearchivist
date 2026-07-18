import APIClient from '../../functions/APIClient';

export type ChannelDownscaleResponseType = {
  queued: string[];
  skipped: { id: string; error: string }[];
};

const startChannelDownscale = async (channelId: string, targetHeight: number) => {
  return APIClient<ChannelDownscaleResponseType>(`/api/channel/${channelId}/downscale/`, {
    method: 'POST',
    body: { target_height: targetHeight },
  });
};

export default startChannelDownscale;
