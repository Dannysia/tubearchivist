import APIClient from '../../functions/APIClient';

export type ChannelDownscaleResponseType = {
  message: string;
  task_id: string;
};

const startChannelDownscale = async (
  channelId: string,
  targetHeight: number,
  skipInactive: boolean,
) => {
  return APIClient<ChannelDownscaleResponseType>(`/api/channel/${channelId}/downscale/`, {
    method: 'POST',
    body: { target_height: targetHeight, skip_inactive: skipInactive },
  });
};

export default startChannelDownscale;
