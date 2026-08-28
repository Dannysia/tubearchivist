import APIClient from '../../functions/APIClient';

export type ChannelVideoType = 'videos' | 'streams' | 'shorts';

export type DeleteChannelVideosResponseType = {
  message: string;
  task_id: string;
};

const deleteChannelVideos = async (
  channelId: string,
  vidType: ChannelVideoType,
  ignore = false,
) => {
  return APIClient<DeleteChannelVideosResponseType>(
    `/api/channel/${channelId}/videos/?vid_type=${vidType}&ignore=${ignore}`,
    { method: 'DELETE' },
  );
};

export default deleteChannelVideos;
